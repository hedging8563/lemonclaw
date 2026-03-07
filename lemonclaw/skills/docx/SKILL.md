---
name: docx
description: "Use this skill for any Word document task — creating, reading, editing .docx files, formatting with headings/tables/images, tracked changes, or converting content to polished Word documents. Also triggers on 创建Word、Word文档、docx文件."
triggers: ".docx,.doc,word文档,word文件,创建word,docx文件,python-docx,写报告,读取word"
---

# Word Document (.docx) Guide

## Quick Reference

| Task | Approach |
|------|----------|
| Read/extract content | pandoc or python-docx |
| Create new document | docx-js (Node) or python-docx (Python) |
| Edit existing document | python-docx or unpack XML |

## Reading Content

```bash
# Convert to markdown
pandoc document.docx -o output.md

# With tracked changes
pandoc --track-changes=all document.docx -o output.md
```

```python
from docx import Document

doc = Document('document.docx')
for para in doc.paragraphs:
    print(para.text)

for table in doc.tables:
    for row in table.rows:
        print([cell.text for cell in row.cells])
```

## python-docx — Create and Edit (Python)

```python
from docx import Document
from docx.shared import Inches, Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

doc = Document()

# Title and headings
doc.add_heading('Document Title', level=0)
doc.add_heading('Section 1', level=1)

# Paragraph with formatting
para = doc.add_paragraph()
run = para.add_run('Bold and colored text')
run.bold = True
run.font.color.rgb = RGBColor(0x00, 0x00, 0xFF)
run.font.size = Pt(14)

# Bullet list
doc.add_paragraph('First item', style='List Bullet')
doc.add_paragraph('Second item', style='List Bullet')

# Numbered list
doc.add_paragraph('Step one', style='List Number')
doc.add_paragraph('Step two', style='List Number')

# Table
table = doc.add_table(rows=3, cols=3, style='Table Grid')
table.cell(0, 0).text = 'Header 1'
table.cell(0, 1).text = 'Header 2'
table.cell(0, 2).text = 'Header 3'

# Image
doc.add_picture('image.png', width=Inches(4))

# Page break
doc.add_page_break()

doc.save('output.docx')
```

### Edit Existing
```python
doc = Document('existing.docx')

# Modify paragraphs
for para in doc.paragraphs:
    if 'old text' in para.text:
        for run in para.runs:
            run.text = run.text.replace('old text', 'new text')

# Add content
doc.add_paragraph('New paragraph at the end')

doc.save('modified.docx')
```

### Page Setup
```python
from docx.shared import Inches

section = doc.sections[0]
section.page_width = Inches(8.5)
section.page_height = Inches(11)
section.top_margin = Inches(1)
section.bottom_margin = Inches(1)
section.left_margin = Inches(1)
section.right_margin = Inches(1)
```

### Headers and Footers
```python
section = doc.sections[0]
header = section.header
header.paragraphs[0].text = "Document Header"

footer = section.footer
footer.paragraphs[0].text = "Page Footer"
```

## docx-js — Create Documents (Node.js)

Install: `npm install docx`

```javascript
const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
        ImageRun, Header, Footer, AlignmentType, HeadingLevel, BorderStyle,
        WidthType, ShadingType, PageNumber, PageBreak, LevelFormat } = require('docx');
const fs = require('fs');

const doc = new Document({
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 }, // US Letter in DXA
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 }
      }
    },
    headers: {
      default: new Header({
        children: [new Paragraph({ children: [new TextRun("Header")] })]
      })
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          children: [new TextRun("Page "), new TextRun({ children: [PageNumber.CURRENT] })]
        })]
      })
    },
    children: [
      new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("Title")] }),
      new Paragraph({ children: [new TextRun({ text: "Bold text", bold: true })] }),
      new Paragraph({ children: [new PageBreak()] }),
    ]
  }]
});

Packer.toBuffer(doc).then(buffer => fs.writeFileSync("doc.docx", buffer));
```

### docx-js Critical Rules

- Set page size explicitly (defaults to A4, not US Letter)
- Never use `\n` — use separate Paragraph elements
- Never use unicode bullets — use `LevelFormat.BULLET` with numbering config
- `PageBreak` must be inside a `Paragraph`
- `ImageRun` requires `type` parameter (png/jpg/etc)
- Tables: always use `WidthType.DXA` (not PERCENTAGE), set both `columnWidths` and cell `width`
- Table shading: use `ShadingType.CLEAR` not `SOLID`
- Don't use tables as dividers — use paragraph borders instead

### Tables (docx-js)
```javascript
const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };

new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [4680, 4680],
  rows: [
    new TableRow({
      children: [
        new TableCell({
          borders,
          width: { size: 4680, type: WidthType.DXA },
          shading: { fill: "D5E8F0", type: ShadingType.CLEAR },
          margins: { top: 80, bottom: 80, left: 120, right: 120 },
          children: [new Paragraph({ children: [new TextRun("Cell")] })]
        }),
        new TableCell({
          borders,
          width: { size: 4680, type: WidthType.DXA },
          children: [new Paragraph({ children: [new TextRun("Cell 2")] })]
        })
      ]
    })
  ]
})
```

### Images (docx-js)
```javascript
new Paragraph({
  children: [new ImageRun({
    type: "png",
    data: fs.readFileSync("image.png"),
    transformation: { width: 200, height: 150 },
    altText: { title: "Title", description: "Desc", name: "Name" }
  })]
})
```

## Install Dependencies
```bash
# Python
pip install python-docx

# Node.js
npm install docx

# CLI
# apt install pandoc  (or brew install pandoc on macOS)
```
