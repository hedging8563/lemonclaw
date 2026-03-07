---
name: content-writer
description: Write high-quality content that doesn't read like AI slop. Use when the user asks to write articles, blog posts, marketing copy, technical docs, social media posts, research reports, or any long-form content. Also triggers on 写文章、写博客、写文案、内容创作、写报告、写稿子.
triggers: "写文章,写博客,写文案,内容创作,写报告,写稿子,blog post,write article,write copy,长文,撰写,起草"
---

# Content Writer

Write content that reads like a human expert wrote it — not like an AI generated it. The core enemy is statistical uniformity: the flat, predictable rhythm that makes AI text instantly recognizable.

## Before Writing: The Thesis Gate

Every piece of content must pass one test before a single word is written:

**"After reading this, what will the reader remember?"**

Not "an overview of X" — that's a topic, not a thesis. A thesis is a judgment:
- "Switching from OpenAI's API to a proxy saves 40% with one line of code"
- "Portugal's drug decriminalization didn't increase usage — it halved overdose deaths"
- "React Server Components solve a problem most apps don't have"

If you can't state the thesis in one sentence, you're not ready to write.

### Thesis Validation

1. Remove all data and examples — does the thesis alone have value?
2. Has the reader seen this argument elsewhere? What's the delta?
3. What action will the reader take after reading? (If none, rethink the thesis)

## The Pipeline

```
Research → Thesis → Structure → Write → Self-Review → Rewrite
```

**Research is collecting. Thesis is judging.** Don't filter during research. Don't add new research during writing. Each stage has one job.

**Upstream quality determines the ceiling.** Weak research → weak thesis → weak article. You cannot fix a bad thesis with good prose.

## Writing Rules

### Kill the AI Fingerprint

AI text has a statistical signature: uniform sentence length, uniform paragraph size, uniform information density, predictable transitions. Break all of these.

| Dimension | AI Pattern (bad) | Human Pattern (good) |
|-----------|-----------------|---------------------|
| Sentence length | Clusters around 25-40 words | 8-word punches mixed with 60-word deep dives |
| Paragraphs | Every paragraph 3-5 sentences | 1-sentence paragraphs next to 8-sentence blocks |
| Info density | Even distribution | Dense data clusters + breathing room |
| Transitions | "Furthermore" "Moreover" "Additionally" | Logic carries the reader — no signposts needed |

### Hard Limits

| Metric | Limit | Fix |
|--------|-------|-----|
| Em dashes (——/—) | ≤3 per article | Replace with colon, comma, or period |
| Bold (**) | ≤3 per article | Only for the single most important judgment |
| Signpost words (首先/其次/最后 / Firstly/Secondly/Finally) | 0 | Use narrative progression instead |
| Meta-narrative (让我们/本文/This article explores) | 0 | Delete. The content speaks for itself |
| "此外" / "Furthermore" / "Moreover" | 0 | Delete or restructure |
| "值得注意的是" / "It's worth noting" | 0 | Delete — if it's worth noting, just note it |
| "至关重要" / "crucial" / "paramount" | 0 | Use "key" or "core", or just state why it matters |

### Banned AI Patterns

**Chinese:**
- 「在当今...时代」— AI opening fingerprint. Cut straight to the point.
- 「随着...的发展」— AI transition. Use a specific event instead.
- 「这不是X，这是Y」— AI reversal. Just state Y.
- 「不仅...而且...更...」— AI triple escalation. Split into independent points.
- 「一站式/全方位/赋能」— Marketing AI slop. Use specifics.
- 揭示了/佐证了/印证了/昭示了 — Delete or replace with plain verbs.

**English:**
- "In today's rapidly evolving..." — Delete the entire sentence.
- "Let's dive into..." / "In this guide, we'll explore..." — Delete.
- "Revolutionary" / "Game-changing" / "Transformative" / "Paradigm shift" — 100% AI markers in technical writing.
- "It's important to note that..." — If it's important, just say it.
- "This is not just X — it's Y" — State Y directly.

### Evidence Over Assertion

Every core claim needs support. Specifics beat adjectives.

| Bad (assertion) | Good (evidence) |
|----------------|-----------------|
| "Much cheaper" | "GPT-4o input: $2.5/M tokens, 40% below official pricing" |
| "Supports many models" | "300+ models across 15 providers (OpenAI, Anthropic, Google...)" |
| "Very fast" | "First token latency < 200ms (Singapore node, measured 2026-03)" |
| "A company" | "Cursor's engineering team in Q4 2025" |

### Opening Rules

Start with one of:
- A verifiable fact or data point
- A specific pain point the reader recognizes
- A counterintuitive finding

Never start with:
- Grand statements about the era we live in
- Questions ("Have you ever wondered...?")
- Self-referential meta ("This article will cover...")
- Fictional characters or scenarios

### Closing Rules

Never end with:
- "In conclusion" / "综上所述"
- "I hope this was helpful" / "希望对你有帮助"
- Summary bullet points that repeat the article

End with:
- A call to action (what should the reader do next?)
- An open question that invites thought
- A forward-looking statement grounded in specifics

## Content Types

| Type | Length | Key Requirement |
|------|--------|----------------|
| Technical blog | 1500-3000 words | Code examples that actually run |
| Comparison/review | 1000-2000 words | Fair data, dated sources |
| Tutorial/guide | 800-1500 words | Step-by-step, copy-paste ready |
| Social post | 100-500 words | Hook in first 2 lines |
| Research report | 3000+ words | Citations, counter-arguments |
| Product update | 300-800 words | What changed + why it matters |

## Self-Review Checklist

Before delivering any content, verify:

- [ ] Thesis is clear in one sentence
- [ ] No banned AI patterns (run through the lists above)
- [ ] Hard limits respected (em dashes ≤3, bold ≤3, zero signposts)
- [ ] Sentence length varies (check: do you have both <10 word and >40 word sentences?)
- [ ] Paragraph length varies (check: do you have both 1-sentence and 5+ sentence paragraphs?)
- [ ] Every core claim has evidence (data, source, date)
- [ ] Opening hooks with a specific fact, not a grand statement
- [ ] Closing drives action, not summary
- [ ] No fictional characters or unverifiable anecdotes
- [ ] Code examples (if any) are runnable as-is

## Model-Specific Pitfalls

If you're aware of which model is generating content:

- **Claude**: Watch for excessive em dashes (typically 8-15 per article), over-polite hedging ("Of course, X also has its merits"), and the word "但" appearing 10+ times
- **GPT**: Watch for "delve", "landscape", "tapestry", "multifaceted", and the pattern "Not just X, but Y"
- **Gemini**: Adequate formatting but shallow analysis. Focus rewrites on adding depth, not fixing structure

## Multilingual Notes

- Chinese and English have different rhythms. A translated article is not a localized article.
- Chinese punctuation: use 「」for quotes in casual writing, ""for formal. Em dash is ——(double).
- Don't mix terminology inconsistently: pick either 「大模型」or "LLM" and stick with it throughout.
- English articles for Chinese products: keep product names and technical terms in English, explain concepts in context.
