---
name: summarize
description: Summarize URLs, local files, and YouTube links with the summarize CLI. Use when the user wants a summary, transcript extraction, or quick understanding of a link or file.
homepage: https://summarize.sh
metadata: {"lemonclaw":{"emoji":"🧾","pattern":"tool-wrapper","requires":{"bins":["summarize"]},"install":[{"id":"brew","kind":"brew","formula":"steipete/tap/summarize","bins":["summarize"],"label":"Install summarize (brew)"}]}}
triggers: "总结网页,总结链接,摘要,summarize,transcript,播客,podcast,总结视频,总结文章,YouTube summary,视频总结,链接总结"
---

# Summarize

This is a `tool-wrapper` skill for the `summarize` CLI.

## Entry Rule

Use this skill when the user wants:
- a summary of a URL or file
- a best-effort transcript from a video URL
- a quick read on a long source before deeper analysis

## Runtime Boundary

- Skill owns: command selection and result-shaping.
- Runtime owns: larger analysis workflows and follow-up tasks.

## Quick Start

```bash
summarize "https://example.com" --model google/gemini-3-flash-preview
summarize "/path/to/file.pdf" --model google/gemini-3-flash-preview
summarize "https://youtu.be/dQw4w9WgXcQ" --youtube auto
```

## Transcript Mode

For best-effort transcript extraction from a video URL:

```bash
summarize "https://youtu.be/dQw4w9WgXcQ" --youtube auto --extract-only
```

If the transcript is too large, summarize first and expand only the requested section.

## Useful Flags

- `--length short|medium|long|xl|xxl|<chars>`
- `--max-output-tokens <count>`
- `--extract-only`
- `--json`
- `--firecrawl auto|off|always`
- `--youtube auto`

## Guardrails

- Prefer concise summaries unless the user asked for detail.
- Treat transcript extraction as best-effort, not guaranteed.
- If the source is blocked, mention the extraction limit rather than pretending the summary is complete.
