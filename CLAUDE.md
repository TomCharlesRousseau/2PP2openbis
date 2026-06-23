# printjob2openbis Project

## Overview
Python project to parse an Excel spreadsheet and create one openBIS object of type `EXPERIMENTAL_STEP` for each printjob.

## Terminology
- **Substrate** = UV-Sheet (use "Substrate" consistently in code and comments)

## Features

### Feature 1 — Default Parent Object (Instrument) for Every Experimental Step
The instrument permId is stored in settings.json under:
```json
{
  "printer": {
    "permid": "20250804114731151-12961"
  }
}
```

When creating any experimental step object in OpenBIS, always automatically assign this permId as a parent object, loaded from `settings["printer"]["permid"]`. This must happen on every experimental step creation — no user input required.

### Feature 2 — Sample Deduplication per Substrate
Every experimental step generates exactly one sample. If two or more experimental steps share the same Substrate (UV-Sheet) as parent, they must all reference the same single sample — do not create duplicate samples.

**Constraint**: number of samples created ≤ number of experimental steps

When multiple experimental steps share a Substrate, assign the sample number of the lowest-numbered experimental step among them.

**Sample naming convention:**
- Code: `PRINTED_<N>`
- Name: `Printed_<N>`

Where `<N>` is the incrementing number of the Substrate (UV-Sheet) — All experimental steps sharing the same Substrate produce a sample with the same `<N>`.

### Feature 3 — Substrate as Parent of the Sample
When creating a sample, assign the Substrate (UV-Sheet) as its parent object in OpenBIS.

### Summary of Object Relationships
```
Instrument (permId: 20250804114731151-12961)
    ├── Experimental Step 1  (parent: Instrument)
    │       └── Sample: PRINTED_1 / Printed_1  (parent: Substrate A)
    ├── Experimental Step 2  (parent: Instrument)
    │       └── Sample: PRINTED_1 / Printed_1  ← same sample! (same Substrate A)
    └── Experimental Step 3  (parent: Instrument)
            └── Sample: PRINTED_3 / Printed_3  (parent: Substrate B)
```

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
| A | Print # | object name | |
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
- **Name**: Print # (Column A)
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
