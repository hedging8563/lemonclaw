---
name: xlsx
description: Read, create, edit, and analyze spreadsheets. Use when the user asks for `.xlsx`, `.csv`, `.tsv`, Excel modeling, spreadsheet cleanup, formulas, or tabular exports.
metadata: {"lemonclaw":{"pattern":"tool-wrapper"}}
triggers: ".xlsx,.xls,.csv,.tsv,excel,spreadsheet,表格,电子表格,数据分析,处理excel,openpyxl,pandas,力学实验"
---

# XLSX

This is a `tool-wrapper` skill.

## Entry Rule

Use this skill for spreadsheet work, especially when formulas, formatting, or tabular cleanup matter.

## Runtime Boundary

- Skill owns: tool choice and spreadsheet-specific pitfalls.
- Runtime owns: larger task pipelines and approvals.

## Choose The Tool

| Task | Preferred tool |
|------|----------------|
| Data analysis, filtering, reshaping | `pandas` |
| Excel formatting, formulas, workbook edits | `openpyxl` |
| Read computed values only | `openpyxl(..., data_only=True)` |

## Key Rule

Prefer spreadsheet formulas over hardcoded computed values whenever the workbook should stay editable.

## Workflow

1. Decide whether the task is analysis or workbook editing.
2. Load the file with the right tool.
3. Apply data changes, formulas, or formatting.
4. Save the workbook.
5. Verify references and formulas.

## Guardrails

- `data_only=True` reads computed values but can destroy formulas if you save carelessly.
- Remember Excel indices are 1-based.
- Check cross-sheet references and denominator safety before shipping a model.
