# printjob2openbis Project

## Overview
Python project to parse an Excel spreadsheet and create one openBIS object of type `EXPERIMENTAL_STEP` for each printjob.

## Reference Project
- **uvsheet2openbis** - Use as reference
- Reuse/copy from:
  - openbis/connection.py
  - openbis/object_manager.py
- Study and replicate parsing logic from: uvsheet2openbis/excel/excel_parser.py

## Project Structure
```
printjob2openbis/
├── main.py
├── config/
│   └── settings.py
├── openbis/
│   ├── connection.py
│   └── object_manager.py
├── excel/
│   ├── excel_parser.py
│   ├── column_mapping.py
│   └── description_builder.py
├── models/
│   └── printjob.py
├── utils/
│   ├── validators.py
│   └── logger.py
├── tests/
├── requirements.txt
└── README.md
```

## Excel File Format
- Headers: Row 2
- Data starts: Row 3

### Columns (A-AC)
| Col | Header | Usage | Notes |
|-----|--------|-------|-------|
| A | Printjob Name # | object name | |
| B | Code | object code | |
| C | Print date | description | already formatted |
| D | Responsible person | description | |
| E | Design | description | |
| F | 3DPoli path | **IGNORE** | |
| G | Resin Name | **IGNORE** | |
| H | Resin ID | parent (permId) | validate with object_exists() |
| I | Substrate Name | **IGNORE** | |
| J | Substrate ID | parent (permId) | validate with object_exists() |
| K | Spacer | description | |
| L | Empty | **IGNORE** | |
| M | F path | **IGNORE** | |
| N | zmin | description | |
| O | zmax | description | |
| P | max z height [µm] | description | |
| Q | xmin | description | |
| R | xmax | description | |
| S | max x height [µm] | description | |
| T | ymin | description | |
| U | ymax | description | |
| V | max y height [µm] | description | |
| W | Lense | description | |
| X | R | description | |
| Y | Max power from calibration | description | |
| Z | Infinite FOV | description | |
| AA | Tilt alpha degree | description | |
| AB | Tilt beta degree | description | |
| AC | Tilt compensation | description | |

## Object Creation
- **Type**: EXPERIMENTAL_STEP
- **Name**: Printjob Name # (Column A)
- **Code**: Code (Column B)
- **Parents**: Resin ID (H), Substrate ID (J)

### Duplicate Handling
- Duplicate codes should NOT raise exception
- If object with same code exists: log INFO and skip
- Example: `INFO: EXPERIMENTAL_STEP PJ001 already exists. Skipping.`

### Parent Validation
- Validate Resin ID and Substrate ID with `object_exists()`
- If parent missing: log ERROR, skip row, continue
- Example: `ERROR: Parent Resin ID {resin_id} does not exist. Skipping row.`

## Description Format
```
Responsible person: Tom Rousseau
Design: Test design
Spacer: 50

zmin: ...
zmax: ...
max z height [µm]: ...

xmin: ...
xmax: ...
max x height [µm]: ...

ymin: ...
ymax: ...
max y height [µm]: ...

Lense: ...
R: ...
Max power from calibration: ...
Infinite FOV: ...
Tilt alpha degree: ...
Tilt beta degree: ...
Tilt compensation: ...
```
- Empty values omitted
- Organized by sections

## Implementation Order

- [x] Step 1: Folder structure and requirements.txt
- [x] Step 2: PrintJob dataclass model
- [x] Step 3: column_mapping.py
- [x] Step 4: excel_parser.py
- [x] Step 5: description_builder.py
- [x] Step 6: Reuse connection.py and object_manager.py from uvsheet2openbis
- [x] Step 7: Create EXPERIMENTAL_STEP objects with parent relationships
- [x] Step 8: Duplicate detection and logging
- [x] Step 9: Validate Resin ID and Substrate ID with object_exists()
- [x] Step 10: Unit tests (39 tests passing)

## Dependencies
- pandas
- openpyxl
- python-dotenv (for settings)
- requests (for openBIS API)

## Code Quality
- Type hints required
- Docstrings required
- Modular and extensible
- No Streamlit interface
