---
name: docx
description: Create, read, edit, or format Word documents. Use when the user needs `.docx` work such as reports, structured Word output, tracked text extraction, or formatting edits.
metadata: {"lemonclaw":{"pattern":"tool-wrapper"}}
triggers: ".docx,.doc,word文档,word文件,word document,word docs,create word document,edit word document,创建word,docx文件,python-docx,写报告,读取word"
---

# DOCX

This is a `tool-wrapper` skill.

## Entry Rule

Use this skill for `.docx` reading, editing, or creation tasks.

## Runtime Boundary

- Skill owns: tool choice and Word-specific gotchas.
- Runtime owns: larger document pipelines, approval checkpoints, and delivery.

## Choose The Tool

| Task | Preferred tool |
|------|----------------|
| Read or inspect existing `.docx` | `python-docx` or `pandoc` |
| Create or edit `.docx` in Python | `python-docx` |
| Generate `.docx` in Node | `docx` (`docx-js`) |

## Inspect First

For existing documents:
- extract structure first
- confirm whether the task is read-only, edit-in-place, or regenerate

## Key Rules

### python-docx

- Best default for creating and editing Word files.
- Good for headings, paragraphs, tables, images, headers, and footers.

### docx-js

- Good for Node-based generation.
- Set page size explicitly.
- Do not rely on `\n` inside one paragraph.
- Keep table widths explicit.

### pandoc

- Good for extracting content to markdown or converting tracked text for review.

## Guardrails

- Preserve editability; do not flatten to another format unless the user wants that.
- If a layout detail is fragile, verify it visually after generation.
- For tracked changes or OOXML-heavy tasks, prefer a cautious extract-and-rebuild workflow over blind XML edits.
