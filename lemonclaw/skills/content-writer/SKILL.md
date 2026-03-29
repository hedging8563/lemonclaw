---
name: content-writer
description: Write articles, blog posts, launch copy, technical docs, research summaries, and social posts that sound intentional rather than generic. Use when the user explicitly asks for substantial content creation or rewriting.
metadata: {"lemonclaw":{"pattern":"generator"}}
triggers: "写文章,写博客,写文案,内容创作,写报告,写稿子,长文,撰写,起草,技术文档,研究报告,产品更新,公众号文章,朋友圈文案,推文,邮件简报,blog post,write article,write copy,linkedin post,social media post,technical doc,technical docs,research report,newsletter,product update,twitter thread,x thread,launch announcement,launch copy,press release"
---

# Content Writer

This is a `generator` skill. It should produce a clear point of view, not just fluent filler.

## Entry Rule

Use this skill when the user wants a real piece of content written or substantially rewritten.

Do not use it for:
- short factual answers
- code comments
- pure proofreading without meaningful rewriting

## Runtime Boundary

- Skill owns: thesis, structure, tone, evidence, self-review.
- Runtime owns: task state, approvals, and long multi-step publishing workflows.

## Workflow

1. Find the thesis.
2. Build the structure around that thesis.
3. Write the draft.
4. Self-review for specificity and rhythm.
5. Tighten weak sections before delivering.

## Thesis Gate

Before writing, answer:

`After reading this, what will the reader remember?`

If that cannot be stated in one sentence, stop and sharpen the thesis first.

## Writing Rules

- Prefer evidence over adjectives.
- Prefer a clear judgment over a broad overview.
- Vary sentence length and paragraph length.
- Cut stock AI phrasing and soft filler.
- Use specifics: numbers, dates, examples, consequences.

## Avoid

- “In today’s rapidly evolving…”
- “This article will explore…”
- “It is worth noting that…”
- generic escalation like “not only X, but Y”
- empty claims like “revolutionary”, “game-changing”, “powerful”

## Verify Before Delivering

- Thesis is visible in the first section.
- Core claims have support.
- The draft has at least some short sentences and some long ones.
- The close ends with an action, implication, or concrete next step.
