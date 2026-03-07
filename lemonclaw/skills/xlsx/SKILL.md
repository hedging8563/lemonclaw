---
name: xlsx
description: "Use this skill for any spreadsheet task — reading, creating, editing .xlsx/.csv/.tsv files, data analysis, formatting, formulas, charts, or cleaning messy tabular data. Triggers when user mentions spreadsheet files or wants tabular data output. Also triggers on 处理Excel、表格、数据分析、电子表格."
triggers: ".xlsx,.xls,.csv,.tsv,excel,spreadsheet,表格,电子表格,数据分析,处理excel,openpyxl,pandas,力学实验"
---

# Excel / Spreadsheet Guide

## Library Selection

| Task | Best Tool |
|------|-----------|
| Data analysis, bulk ops, simple export | pandas |
| Formulas, formatting, Excel-specific features | openpyxl |
| Read calculated values (no formulas) | `openpyxl` with `data_only=True` |

## CRITICAL: Use Formulas, Not Hardcoded Values

Always use Excel formulas instead of computing in Python and writing static values. The spreadsheet must remain dynamic.

```python
# BAD — hardcoded
sheet['B10'] = df['Sales'].sum()

# GOOD — Excel formula
sheet['B10'] = '=SUM(B2:B9)'
sheet['C5'] = '=(C4-C2)/C2'
sheet['D20'] = '=AVERAGE(D2:D19)'
```

## pandas — Data Analysis

```python
import pandas as pd

# Read
df = pd.read_excel('file.xlsx')
all_sheets = pd.read_excel('file.xlsx', sheet_name=None)

# Analyze
df.head()
df.info()
df.describe()

# Write
df.to_excel('output.xlsx', index=False)
```

Tips:
- Specify dtypes: `pd.read_excel('f.xlsx', dtype={'id': str})`
- Read specific columns: `pd.read_excel('f.xlsx', usecols=['A', 'C'])`
- Parse dates: `pd.read_excel('f.xlsx', parse_dates=['date_col'])`

## openpyxl — Create New Files

```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

wb = Workbook()
sheet = wb.active

sheet['A1'] = 'Header'
sheet['A1'].font = Font(bold=True, color='FF0000')
sheet['A1'].fill = PatternFill('solid', start_color='FFFF00')
sheet['A1'].alignment = Alignment(horizontal='center')
sheet.column_dimensions['A'].width = 20

sheet.append(['Row', 'of', 'data'])
sheet['B5'] = '=SUM(B2:B4)'

wb.save('output.xlsx')
```

## openpyxl — Edit Existing Files

```python
from openpyxl import load_workbook

wb = load_workbook('existing.xlsx')
sheet = wb.active  # or wb['SheetName']

sheet['A1'] = 'New Value'
sheet.insert_rows(2)
sheet.delete_cols(3)

new_sheet = wb.create_sheet('NewSheet')
new_sheet['A1'] = 'Data'

wb.save('modified.xlsx')
```

## openpyxl Pitfalls

- Cell indices are 1-based (row=1, column=1 = A1)
- `data_only=True` reads calculated values but **if you save, formulas are permanently lost**
- For large files: `read_only=True` for reading, `write_only=True` for writing
- Formulas are stored as strings, not evaluated — open in Excel/LibreOffice to see computed values
- Row offset: DataFrame row 5 = Excel row 6 (header row)

## Common Workflow

1. Choose tool: pandas for data, openpyxl for formulas/formatting
2. Create or load workbook
3. Add/edit data, formulas, formatting
4. Save file
5. Verify: open in Excel/LibreOffice to check formulas evaluate correctly

## Formula Verification Checklist

- Test 2-3 sample references before building full model
- Confirm column mapping (column 64 = BL, not BK)
- Check for NaN with `pd.notna()`
- Division by zero: check denominators
- Cross-sheet refs: use `Sheet1!A1` format
- Test edge cases: zero, negative, large values

## Financial Model Standards

When building financial models:

### Color Coding
- Blue text (0,0,255): Hardcoded inputs
- Black text (0,0,0): Formulas
- Green text (0,128,0): Cross-sheet links
- Yellow background (255,255,0): Key assumptions

### Number Formatting
- Years: text format ("2024" not "2,024")
- Currency: `$#,##0` with units in headers
- Zeros: show as "-" (`$#,##0;($#,##0);-`)
- Percentages: `0.0%`
- Negatives: parentheses `(123)` not `-123`

### Formula Rules
- Place ALL assumptions in separate cells, reference them
- Use `=B5*(1+$B$6)` not `=B5*1.05`
- Document hardcoded values with source and date

## Install Dependencies
```bash
pip install openpyxl pandas
```
