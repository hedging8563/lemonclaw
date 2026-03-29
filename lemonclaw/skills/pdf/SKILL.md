---
name: pdf
description: Read, extract, split, merge, rotate, create, or OCR PDF files. Use when the user asks to inspect or produce `.pdf` documents.
metadata: {"lemonclaw":{"pattern":"tool-wrapper"}}
triggers: ".pdf,pdf文件,pdfs,merge pdf,merge pdfs,combine pdfs,create pdf,create a pdf,create pdf report,pdf report,make pdf,处理pdf,合并pdf,拆分pdf,pdf转,创建pdf,pypdf,pdfplumber,ocr,读取pdf,提取pdf"
---

# PDF

This is a `tool-wrapper` skill.

## Entry Rule

Use this skill for PDF manipulation or extraction.

## Runtime Boundary

- Skill owns: tool choice and PDF-specific processing advice.
- Runtime owns: long workflows, retries, and handoff state.

## Choose The Tool

| Task | Preferred tool |
|------|----------------|
| Merge / split / rotate / encrypt | `pypdf` or `qpdf` |
| Text extraction | `pdfplumber` |
| Table extraction | `pdfplumber` |
| Create new PDFs | `reportlab` |
| OCR scanned PDFs | `pytesseract` + `pdf2image` |

## Inspect First

- Determine whether the PDF is digital text or scanned.
- Determine whether the goal is extraction, transformation, or generation.

## Key Rules

- Use `pdfplumber` when extraction quality matters.
- Use `pypdf` for page-level document surgery.
- Use `reportlab` for generated reports.
- For OCR, convert pages to images first.

## Guardrails

- Verify page count after merge/split/rotate.
- For generated PDFs, visually inspect layout if formatting matters.
- For scanned PDFs, do not promise clean text extraction without OCR.
