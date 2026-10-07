#!/usr/bin/env python3
"""把播客字幕清成能读的连续文本。

做四件事：
  1. 去掉序号行、时间轴、VTT/HTML 标签、重复行
  2. 把碎片化的字幕行拼回句子
  3. 按时间间隔和标点切段落
  4. 顺手报一份统计（汉字数、段落数、时长估算）

用法：
    python3 prep_transcript.py 输入.srt
    python3 prep_transcript.py 输入.srt -o 清洗稿.md
    python3 prep_transcript.py 输入.txt --speakers      # 只列说话人标签

支持 SRT / VTT（带时间轴）和 txt / md。带空行的纯文本会尊重原有的空行分段。
"""
import argparse
import re
import sys
from pathlib import Path

TS = re.compile(r"^\s*\d{1,2}:\d{2}(:\d{2})?[.,]\d{1,3}\s*-->")
NUM = re.compile(r"^\s*\d+\s*$")
TAG = re.compile(r"<[^>]{1,40}>")
SPEAKER = re.compile(
    r"^\s*\*{0,2}\s*(?:\[|【)?\s*([\u4e00-\u9fffA-Za-z0-9 _\-]{1,8}?)\s*(?:\]|】)?\s*[:：]\s*\*{0,2}\s*")
NO_LABEL = ("说", "道", "问", "答", "是", "有", "我见", "注意")   # 这些不像人名，别当说话人
HEADING = ("#", ">", "---", "|")   # 原样保留的块，不参与合并
PARA_GAP = 1.5     # 秒，大于这个间隔视为换段
PARA_CHARS = 140   # 段落软上限，到句末且超过它就断开
HARD_CHARS = 300   # 硬上限，没标点的 ASR 稿也按这个断


def parse_time(s):
    s = (s or "").strip().replace(",", ".")
    if not s:
        return None
    parts = [x for x in re.split(r"[:.]", s) if x != ""]
    try:
        n = [float(x) for x in parts]
    except ValueError:
        return None
    if len(n) >= 4:
        h, m, sec, ms = n[:4]
        return h * 3600 + m * 60 + sec + ms / 1000
    if len(n) == 3:
        h, m, sec = n
        return h * 3600 + m * 60 + sec
    if len(n) == 2:
        m, sec = n
        return m * 60 + sec
    return n[0] if n else None


def parse(text):
    """返回 [(start, end, text), ...]"""
    cues = []
    if "-->" in text:
        for block in re.split(r"\n\s*\n", text):
            lines = [l for l in block.split("\n") if l.strip()]
            if not lines:
                continue
            i = 0
            if NUM.match(lines[0]):
                i = 1
            if i < len(lines) and "-->" in lines[i]:
                a, _, b = lines[i].partition("-->")
                start, end = parse_time(a), parse_time(b.split()[0] if b.split() else "")
                body = " ".join(lines[i + 1:])
                if body.strip():
                    cues.append((start, end, TAG.sub("", body).strip()))
                continue
            cues.append((None, None, TAG.sub("", " ".join(lines)).strip()))
        return cues

    # 纯文本：一行一条，交给 build() 按标点和说话人合并
    for line in text.split("\n"):
        line = TAG.sub("", line).strip()
        if line and not TS.match(line) and not NUM.match(line):
            cues.append((None, None, line))
    return cues


def speaker_of(txt):
    m = SPEAKER.match(txt)
    if not m:
        return None
    label = m.group(1).strip()
    if label.endswith(NO_LABEL) or len(label) > 8:
        return None
    return label


def join_fragments(a, b):
    if not a:
        return b
    if re.search(r"[A-Za-z0-9]$", a) and re.match(r"^[A-Za-z0-9]", b):
        return a + " " + b
    return a + b


def is_standalone(txt):
    return txt.lstrip().startswith(HEADING)


def build(cues, split_speaker=True):
    """把 cue 拼成段落。

    规则：同一说话人的连续片段合并（ASR 常把一句话切成好几条）；说话人变了、
    时间断档超过 PARA_GAP 秒、或者同一个人的话已经堆到 PARA_CHARS 字并在句末，
    就断开。标题与引用行前后都断开，自己成段。
    """
    paras, buf, buf_start, last_end, cur = [], "", None, None, None
    for start, end, txt in cues:
        txt = txt.strip()
        if not txt:
            continue
        if is_standalone(txt):
            if buf:
                paras.append((buf_start, buf))
            buf, buf_start, cur = "", None, None
            paras.append((start, txt))
            last_end = end
            continue
        at_end = bool(re.search(r"[。！？!?]\s*$", buf))
        me = speaker_of(txt)
        brk = False
        if buf:
            if split_speaker and me and cur and me != cur:
                brk = True
            if last_end is not None and start is not None and start - last_end > PARA_GAP:
                brk = True
            if at_end and len(buf) >= PARA_CHARS:
                brk = True
            if len(buf) >= HARD_CHARS:
                brk = True
        if brk:
            paras.append((buf_start, buf))
            buf, buf_start = "", None
        if me:
            cur = me
        if buf_start is None:
            buf_start = start
        buf = join_fragments(buf, txt)
        if end is not None:
            last_end = end
    if buf:
        paras.append((buf_start, buf))
    return [p for p in paras if p[1].strip()]


def split_long(para, limit=260):
    """超长段落按句末断开。"""
    if len(para) <= limit:
        return [para]
    out, buf = [], ""
    for sent in re.findall(r"[^。！？!?]*[。！？!?]|[^。！？!?]+$", para):
        if not sent:
            continue
        buf += sent
        if len(buf) >= limit:
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


def fmt_time(sec):
    if sec is None:
        return "—"
    return f"{int(sec // 60):02d}:{int(sec % 60):02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("-o", "--out")
    ap.add_argument("--no-split-speaker", action="store_true",
                    help="不因为说话人变化而断段")
    ap.add_argument("--speakers", action="store_true", help="只列说话人标签")
    args = ap.parse_args()

    raw = Path(args.path).read_text(encoding="utf-8", errors="replace")
    cues = parse(raw)
    if not cues:
        sys.exit(f"没解析出内容：{args.path}")

    if args.speakers:
        found = {}
        for _, _, t in cues:
            m = SPEAKER.match(t)
            if m:
                found[m.group(1)] = found.get(m.group(1), 0) + 1
        print(f"解析出 {len(cues)} 条")
        for k, v in sorted(found.items(), key=lambda x: -x[1]):
            print(f"  {k}  {v}")
        return

    paras = []
    for start, body in build(cues, not args.no_split_speaker):
        for chunk in split_long(body):
            paras.append((start, chunk))

    zh = len(re.findall(r"[\u4e00-\u9fff]", "".join(p for _, p in paras)))
    last = cues[-1][1] or cues[-1][0]
    dur = fmt_time(last)

    # 去重相邻重复段（ASR 常见）
    dedup = []
    for s, p in paras:
        if dedup and dedup[-1][1].strip() == p.strip():
            continue
        dedup.append((s, p))
    dropped = len(paras) - len(dedup)
    paras = dedup

    lines = []
    for s, p in paras:
        p = re.sub(r"\s*\n\s*", " ", p).strip()
        lines.append(f"[{fmt_time(s)}] {p}" if s is not None and not is_standalone(p) else p)
    body = "\n\n".join(lines)

    heads = sum(1 for _, p in paras if p.lstrip().startswith("#"))
    punct = len(re.findall(r"[。！？!?]", "".join(p for _, p in paras)))
    stats = (f"# 统计：汉字 {zh}，段落 {len(paras)}，原始片段 {len(cues)}，章节标题 {heads}，"
             f"时长约 {dur}，去重 {dropped} 段")
    if punct < 0.5 * len(paras):
        stats += ("\n# 注意：句末标点少（取决于 ASR），段落边界是按长度切的。"
                  "下一步做要点梳理之前先补标点、逐条断句。")
    if args.out:
        Path(args.out).write_text(body + "\n", encoding="utf-8")
        print(stats, file=sys.stderr)
        print(f"已写入 {args.out}", file=sys.stderr)
    else:
        print(body)
        print("\n" + stats, file=sys.stderr)


if __name__ == "__main__":
    main()
