#!/usr/bin/env python3
"""成稿的 AI 味自检。

规则集和人类侧基准来自 https://github.com/larashero3-dotcom/lieflat-less-ai-tone （MIT）。
它用 300 篇五模型生成文本 + 329 篇人类写作（629 篇、95,551 句、45,721 段）逐项检验了
一批"AI 文风"候选特征，只留了真有区分力的那些。这里的正则抄它的 scripts/，
人类侧基准抄它的 RESEARCH.md（那批人类语料没公开，本机复算不了）。

用法：
    python3 check_style.py 成稿.md
    python3 check_style.py 成稿.md --quiet      # 只出结论，不出实例

判断要自己看一眼：正则只看字面。引号里的原话、对话体、顿号列举都会误报。
"""
import argparse
import re
import sys
from pathlib import Path

# name -> (正则, 人类基准/千汉字 或 None, 是否是硬禁项)
RULES = [
    ("破折号", r"—", 0.80, True),
    ("翻案腔（不是X而是Y）", r"(?:不是|并非|不在于)[^，。！？\n]{1,20}[，]?(?:而是|而在于)", 0.22, True),
    ("总结腔", r"(?:本质上|核心是|核心在于|归根结底|综上所述|换句话说|换言之|值得注意的是|值得一提的是|说到底)", None, True),
    ("序数词当小标题", r"(?:^|\n)\s*(?:首先|其次|再次|最后|第一|第二|第三|一方面|另一方面)[，、]", 0.06, False),
    ("提示性冒号", (r"(?:一句话(?:总结|说|概括)|简单说|说白了|总结|小结|结论|核心(?:是|在于|观点)?"
                r"|关键(?:是|在于)?|重点(?:是)?|原因(?:如下|有|在于)?|问题(?:是|在于)?"
                r"|答案(?:是)?|本质(?:是|上)?|定义(?:是)?|具体(?:来说|如下|包括)?"
                r"|举例(?:来说)?|换句话说|也就是说|我的(?:观点|判断|结论)|建议(?:是)?)[：:]"), 0.08, False),
    ("空转句引列表", r"(?:^|\n)([^\n。！？]{0,40})[：:][ \t]*\n\s*[-*\d]", 0.03, False),
    ("拟人化喻体", r"(?:像|相当于|如同|好比)(?:一个|一位|一名|一种)?[^，。\n]{0,6}(?:导师|秘书|助手|顾问|管家|审查员|实习生|教练|伙伴|搭档|同事|专家)", 0.002, False),
    ("替说话人描述态度", r"(?:说|讲|回答|介绍|解释|强调)得(?:很|挺|特别|非常)(?:重|轻|坦白|坦诚|真诚|直接|认真|激动|平静|无奈|克制|小声|大声|慢|快)|(?:他|她|他们|对方|嘉宾|主持人)的(?:语气|神情|表情|态度)", None, True),
    ("动词名词化", r"(?:完成|实现|进行|开展)了?(?:对)?[^，。\n]{0,10}的(?:优化|提升|调整|分析|改造|升级)", 0.005, False),
    ("句首连接词", r"(?:^|\n)\s*(?:然而|因此|此外|与此同时|换言之|总而言之)[，、]", 0.03, False),
    ("这意味着", r"(?:这意味着|这表明|这说明|换句话说)", 0.15, False),
    ("当…时", r"当[^，。\n]{2,20}(?<!的时候)时，", 0.26, False),
    ("前置话题壳", r"(?:对于[^，。\n]{2,15}来说|对[^，。\n]{2,15}而言|就[^，。\n]{2,15}而言|在[^，。\n]{2,12}方面)", 0.22, False),
    ("过长前置定语", r"(?:一个|一种|一套|这种|这个)[^，。、；：！？\n]{15,}的[\u4e00-\u9fff]{2,5}", 0.42, False),
    ("顿号罗列过密", r"[^，。！？；：、\n]{1,14}、[^，。！？；、\n]{1,14}、[^，。！？；：、\n]{1,14}", 1.78, False),
]

COMMENT = re.compile(
    r"^(?:听起来|看起来|看上去|听上去|说白了|说到底|换句话说|意味着|值得注意|"
    r"不难看出|细看|再看|回过头看|问题在于|原因在于|结果是|有意思的是|"
    r"更重要的是|关键在于|真正的)")
ANAPHOR = re.compile(r"^(?:这|那|其|此|上面|前面|刚才|以上|该|它|他|她|它们|他们|同样|类似|相比|反过来|但|不过|所以|因此|于是|而|另|除此|与此)")
METAPHOR = re.compile(r"^(?:像|就像|好比|好像|仿佛|如同|这就像)")

STRUCT_HUMAN = {
    "段首零回指评论/非首段%": 0.14,
    "连续两句同构/百段": 4.81,
    "比喻起段/百段": 0.38,
}

# 段首自足判断句：主谓完整的论断，不接上文。实录体里这类段首一多，全篇读起来像口号集。
ASSERT_START = re.compile(r"^[^，。！？；\n“”\"：]{2,14}(?:是|不是|在|有|没有|会|能|要|应该|等于|属于)")
# 直接引语（中英文引号都算，引号内至少两个字）
QUOTE = re.compile(r"[“\"]([^”\"]{2,})[”\"]")

OK, WARN, BAD = "✅", "⚠️", "❌"


def zh(t):
    return len(re.findall(r"[\u4e00-\u9fff]", t))


def paragraphs(text):
    out = []
    for p in text.split("\n"):
        p = p.strip()
        if len(p) < 8 or p.startswith(("#", "|", "```", ">", "- ", "* ", "!")):
            continue
        out.append(p)
    return out


def signature(s):
    return (s.count("，"), "：" in s, ("（" in s or "(" in s), len(s) // 15)


def iso_pairs(para):
    sents = [s.strip() for s in re.split(r"[。！？]", para) if len(s.strip()) > 10]
    out = []
    for i in range(len(sents) - 1):
        if signature(sents[i]) == signature(sents[i + 1]) and signature(sents[i])[0] >= 1:
            out.append((sents[i], sents[i + 1]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    text = Path(args.path).read_text(encoding="utf-8")
    n = zh(text)
    if n < 200:
        sys.exit("汉字太少，测不出东西")
    k = n / 1000

    print(f"# {Path(args.path).name}")
    print(f"汉字 {n}，段落 {len(paragraphs(text))}\n")

    print("## 句层（每千汉字）")
    print(f"{'规则':<22}{'命中':>6}{'每千字':>9}{'人类基准':>10}{'倍率':>8}   判定")
    print("-" * 66)
    fails, warns = [], []
    for name, pat, human, hard in RULES:
        hits = re.findall(pat, text)
        c = len(hits)
        per = c / k
        ratio = f"{per / human:.1f}x" if human else "—"
        base = f"{human}" if human else "—"
        if hard and c:
            verdict = BAD
            fails.append(name)
        elif human and per > human * 3:
            verdict = WARN
            warns.append(name)
        else:
            verdict = OK
        print(f"{name:<22}{c:>6}{per:>9.2f}{base:>10}{ratio:>8}   {verdict}")
        if c and not args.quiet and verdict != OK:
            for h in hits[:8]:
                s = h if isinstance(h, str) else h[0]
                print(f"      · {re.sub(chr(10), ' ', str(s))[:70]}")
    if not fails and not warns:
        print(f"\n{OK} 句层全过")

    print("\n## 段落层")
    ps = paragraphs(text)
    nonfirst = max(len(ps) - 1, 1)
    zero = [(i, p) for i, p in enumerate(ps) if i and COMMENT.match(p) and not ANAPHOR.match(p)]
    iso2 = [(i, a, b) for i, p in enumerate(ps) for a, b in iso_pairs(p)]
    meta = [p for p in ps if METAPHOR.match(p)]
    for label, val, count in [
        ("段首零回指评论/非首段%", len(zero) / nonfirst * 100, zero),
        ("连续两句同构/百段", len(iso2) / len(ps) * 100, iso2),
        ("比喻起段/百段", len(meta) / len(ps) * 100, meta),
    ]:
        base = STRUCT_HUMAN[label]
        ratio = val / base if base else 0
        v = OK if ratio <= 3 else (WARN if ratio <= 6 else BAD)
        print(f"{label:<22}本稿 {val:>6.2f}   人类 {base:>5.2f}   {ratio:>5.1f}x   {v}")
        if count and not args.quiet and v != OK:
            for item in count[:6]:
                shown = item[-1] if isinstance(item, tuple) else item
                print(f"      · {shown[:70]}")
    # 引语：记者式实录的肉。占比太低说明原话被改写成概述了。
    quotes = QUOTE.findall(text)
    quote_zh = sum(zh(q) for q in quotes)
    qp = quote_zh / n * 100
    qv = OK if 15 <= qp <= 45 else WARN
    print(f"\n{'直接引语汉字占比%':<22}本稿 {qp:>6.2f}   参考 20-40   {'':>5}   {qv}（{len(quotes)} 处）")

    # 段首自足判断句
    asserts = []
    for p in ps:
        first = re.split(r"[。！？]", p)[0].strip()
        if not first or first[0] in "“\"":
            continue
        if ANAPHOR.match(first) or re.match(r"^(?:他|她|它|他们|我们|你|我|Noah|主持人)", first):
            continue
        if re.match(r"^[A-Za-z\u4e00-\u9fff]{2,6}(?:说|问|答|介绍|形容)", first):
            continue
        if ASSERT_START.match(first):
            asserts.append(first)
    ra = len(asserts) / len(ps) * 100
    av = OK if ra <= 30 else (WARN if ra <= 50 else BAD)
    print(f"{'段首自足判断句/段%':<22}本稿 {ra:>6.2f}   参考 <=30   {'':>5}   {av}")
    if asserts and not args.quiet and av != OK:
        for s in asserts[:6]:
            print(f"      · {s[:70]}")

    print(f"{'平均段长（汉字）':<22}{n / len(ps):>6.1f}")

    print("\n## 结构层")
    bold = len(re.findall(r"\*\*[^*\n]+\*\*", text))
    bullets = len(re.findall(r"(?:^|\n)\s*(?:[-*+]|\d+\.)\s+\S", text))
    digits = len(re.findall(r"[0-9]", text))
    latin = len(re.findall(r"[A-Za-z][A-Za-z0-9.\-]{1,}", text))
    print(f"加粗块 {bold}  {OK if bold == 0 else WARN}   项目符号行 {bullets}  {OK if bullets == 0 else WARN}")
    print(f"阿拉伯数字字符 {digits}（每千汉字 {digits / k:.1f}）   英文字母词 {latin}（每千汉字 {latin / k:.1f}）")
    print("材料密度（数字、专名、时间、数量，每千汉字）：人类基准 17.92。本脚本只数得出阿拉伯")
    print("数字和英文词两种，中文数字和中文专名数不了，这一项要人工看一眼——具体材料少的稿子才是")
    print("最难救的。")

    print("\n## 结论")
    if fails:
        print(f"{BAD} 硬禁项命中：{'、'.join(fails)}。这些是字面违禁，逐条改掉。")
    if warns:
        print(f"{WARN} 需要逐条看一眼（可能是误报）：{'、'.join(warns)}")
    if not fails and not warns:
        print(f"{OK} 句层没有需要处理的项目。别忘了人工通读一遍：脚本管不了省略宾语、换同义词、丢材料。")
    print("人工再核四条：每节标题能不能预判内容；随手挑三句引语对着逐字稿核一遍；")
    print("有没有句子说话人认不出是自己说的；有没有哪一整段回答的是别的问题。")


if __name__ == "__main__":
    main()
