---
name: pdf
description: Use this skill for any PDF task — reading, extracting text/tables, merging, splitting, rotating, watermarking, creating, encrypting, or OCR. Triggers when user mentions .pdf files or asks to produce one. Also triggers on 处理PDF、合并PDF、拆分PDF、PDF转文字、创建PDF.
triggers: ".pdf,pdf文件,处理pdf,合并pdf,拆分pdf,pdf转,创建pdf,pypdf,pdfplumber,ocr,读取pdf,提取pdf"
---

# PDF Processing Guide

## Quick Start

```python
from pypdf import PdfReader, PdfWriter

reader = PdfReader("document.pdf")
print(f"Pages: {len(reader.pages)}")

text = ""
for page in reader.pages:
    text += page.extract_text()
```

## Quick Reference

| Task | Best Tool | Key API |
|------|-----------|---------|
| Merge PDFs | pypdf | `writer.add_page(page)` |
| Split PDFs | pypdf | One page per writer |
| Extract text | pdfplumber | `page.extract_text()` |
| Extract tables | pdfplumber | `page.extract_tables()` |
| Create PDFs | reportlab | Canvas or Platypus |
| CLI merge | qpdf | `qpdf --empty --pages ...` |
| OCR scanned | pytesseract + pdf2image | Convert to image first |

## pypdf — Read, Merge, Split, Rotate

### Merge
```python
from pypdf import PdfWriter, PdfReader

writer = PdfWriter()
for pdf_file in ["doc1.pdf", "doc2.pdf"]:
    reader = PdfReader(pdf_file)
    for page in reader.pages:
        writer.add_page(page)

with open("merged.pdf", "wb") as f:
    writer.write(f)
```

### Split
```python
reader = PdfReader("input.pdf")
for i, page in enumerate(reader.pages):
    writer = PdfWriter()
    writer.add_page(page)
    with open(f"page_{i+1}.pdf", "wb") as f:
        writer.write(f)
```

### Rotate
```python
reader = PdfReader("input.pdf")
writer = PdfWriter()
page = reader.pages[0]
page.rotate(90)
writer.add_page(page)
with open("rotated.pdf", "wb") as f:
    writer.write(f)
```

### Metadata
```python
reader = PdfReader("document.pdf")
meta = reader.metadata
print(f"Title: {meta.title}, Author: {meta.author}")
```

### Password Protection
```python
reader = PdfReader("input.pdf")
writer = PdfWriter()
for page in reader.pages:
    writer.add_page(page)
writer.encrypt("userpassword", "ownerpassword")
with open("encrypted.pdf", "wb") as f:
    writer.write(f)
```

### Watermark
```python
watermark = PdfReader("watermark.pdf").pages[0]
reader = PdfReader("document.pdf")
writer = PdfWriter()
for page in reader.pages:
    page.merge_page(watermark)
    writer.add_page(page)
with open("watermarked.pdf", "wb") as f:
    writer.write(f)
```

## pdfplumber — Text and Table Extraction

### Extract Text
```python
import pdfplumber

with pdfplumber.open("document.pdf") as pdf:
    for page in pdf.pages:
        print(page.extract_text())
```

### Extract Tables
```python
with pdfplumber.open("document.pdf") as pdf:
    for page in pdf.pages:
        for table in page.extract_tables():
            for row in table:
                print(row)
```

### Tables to DataFrame
```python
import pandas as pd

with pdfplumber.open("document.pdf") as pdf:
    all_tables = []
    for page in pdf.pages:
        for table in page.extract_tables():
            if table:
                df = pd.DataFrame(table[1:], columns=table[0])
                all_tables.append(df)
    if all_tables:
        combined = pd.concat(all_tables, ignore_index=True)
        combined.to_excel("extracted.xlsx", index=False)
```

## reportlab — Create PDFs

### Basic
```python
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

c = canvas.Canvas("output.pdf", pagesize=letter)
width, height = letter
c.drawString(100, height - 100, "Hello World!")
c.line(100, height - 120, 400, height - 120)
c.save()
```

### Multi-page with Platypus
```python
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet

doc = SimpleDocTemplate("report.pdf", pagesize=letter)
styles = getSampleStyleSheet()
story = [
    Paragraph("Report Title", styles['Title']),
    Spacer(1, 12),
    Paragraph("Body text here. " * 20, styles['Normal']),
    PageBreak(),
    Paragraph("Page 2", styles['Heading1']),
]
doc.build(story)
```

### Subscripts/Superscripts
Never use Unicode subscript/superscript characters in ReportLab — they render as black boxes. Use XML tags:
```python
Paragraph("H<sub>2</sub>O", styles['Normal'])
Paragraph("x<super>2</super>", styles['Normal'])
```

## CLI Tools

```bash
# pdftotext (poppler-utils)
pdftotext input.pdf output.txt
pdftotext -layout input.pdf output.txt
pdftotext -f 1 -l 5 input.pdf output.txt

# qpdf
qpdf --empty --pages file1.pdf file2.pdf -- merged.pdf
qpdf input.pdf --pages . 1-5 -- pages1-5.pdf
qpdf input.pdf output.pdf --rotate=+90:1
qpdf --password=pass --decrypt encrypted.pdf decrypted.pdf

# Extract images (poppler-utils)
pdfimages -j input.pdf output_prefix
```

## OCR Scanned PDFs
```python
import pytesseract
from pdf2image import convert_from_path

images = convert_from_path('scanned.pdf')
text = ""
for i, image in enumerate(images):
    text += f"Page {i+1}:\n{pytesseract.image_to_string(image)}\n\n"
```

## Install Dependencies
```bash
pip install pypdf pdfplumber reportlab
# For OCR: pip install pytesseract pdf2image
# CLI: apt install poppler-utils qpdf  (or brew install on macOS)
```
