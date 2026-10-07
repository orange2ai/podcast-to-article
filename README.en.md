# podcast-to-article

Turn a multi-speaker podcast transcript into a publishable long-form article.

A transcript is organized around **who spoke and when**. An article is organized around **what the topic is and what the takeaway is**. This skill does that re-axis.

## The problem it solves

Ask a model to "write the transcript up as an article" and you get one of two failures. Either it keeps the relay structure ("Alice said… Bob said… Carol said…") and reads like meeting minutes, or it abstracts everything away — no numbers, no product details, just smooth sentences carrying no new information.

The rule is therefore two-directional: **tear down the speaker scaffolding, keep the grain of the facts.**

## Install

```bash
git clone https://github.com/orange2ai/podcast-to-article.git
ln -s "$(pwd)/podcast-to-article" ~/.cola/skills/podcast-to-article
```

`SKILL.md` is the agent-facing manual. No platform dependency — pure python3 standard library.

## Usage

```bash
python3 scripts/prep_transcript.py episode.srt -o cleaned.md   # strip timestamps, merge by speaker
python3 scripts/check_style.py draft.md                        # AI-tone self-check
```

Then ask your agent: *"turn this transcript into an article, Next Token style"*. It walks six steps: clean → extract a fact ledger → re-axis into sections → attribute names correctly → cut a third → self-check.

Supports SRT, VTT, and pre-converted `.md` / `.txt` transcripts (including `**Speaker:**` markers).

## What's inside

```
SKILL.md                       the workflow and its criteria
references/style-rules.md      hard language rules, each with human/AI measured baselines
references/example.md          the same transcript passage, raw vs published
scripts/prep_transcript.py     transcript cleaner
scripts/check_style.py         draft checker
```

## Where the rules come from

The language numbers come from [lieflat-less-ai-tone](https://github.com/larashero3-dotcom/lieflat-less-ai-tone) (MIT): 300 model-generated articles plus 329 human-written ones — 629 articles, 95,551 sentences, 45,721 paragraphs. Three of its findings run against common advice: humans use **2.4x more** metaphors than models, humans use rhetorical questions **17x more** often in body text, and sentence-length evenness shows **no** difference.

The workflow and the name-attribution rules come from the real editing passes on the Next Token podcast (episode 004).

## License

MIT
