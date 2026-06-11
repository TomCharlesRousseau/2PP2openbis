# printjob2openbis

Python parser that reads a 3D-printing job Excel spreadsheet and creates one
`EXPERIMENTAL_STEP` object per print job in openBIS.

## Project structure

```
printjob2openbis/
├── main.py                     # Entry point / orchestrator
├── config/
│   ├── settings.py             # Settings class
│   └── settings.json           # Configuration values (not committed)
├── openbis/
│   ├── connection.py           # openBIS connection handler
│   └── object_manager.py       # Object creation and validation
├── excel/
│   ├── excel_parser.py         # Excel parsing logic
│   ├── column_mapping.py       # Column name definitions
│   └── description_builder.py  # Description text generator
├── models/
│   └── printjob.py             # PrintJob dataclass
├── utils/
│   ├── logger.py               # Logging configuration
│   └── validators.py           # Input validation helpers
├── tests/                      # Unit tests
├── requirements.txt
└── README.md
```

## Setup

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Create `config/settings.json` (see `config/settings.json.example`):

```json
{
  "openbis": {
    "api_url": "https://your-openbis-instance/",
    "username": "your_username",
    "space": "YOUR_SPACE",
    "project_name": "YOUR_PROJECT",
    "collection": "PRINTJOB_EXP_STEP"
  },
  "excel": {
    "file_path": "printjobs.xlsx"
  }
}
```

## Usage

```bash
python main.py
```

## Excel file format

Headers must be on **row 2**. Supported columns:

| Column | Field |
|--------|-------|
| A | Printjob Name # |
| B | Code |
| C | Print date |
| D | Responsible person |
| E | Design |
| F | 3DPoli path |
| H | Resin ID (permId) |
| J | Substrate ID (permId) |
| K | Spacer |
| N | zmin |
| O | zmax |
| P | max z height [µm] |
| Q | xmin |
| R | xmax |
| S | max x height [µm] |
| T | ymin |
| U | ymax |
| V | max y height [µm] |
| W | Lense |
| X | R |
| Y | Max power from calibration |
| Z | Infinite FOV |
| AA | Tilt alpha degree |
| AB | Tilt beta degree |
| AC | Tilt compensation |

Columns G (Resin Name), I (Substrate Name), L (empty), and M (F path) are ignored.

## Behaviour

- One `EXPERIMENTAL_STEP` object is created per print job row.
- **Object name**: Printjob Name #  
- **Object code**: Code  
- **Parents**: Resin ID and Substrate ID (openBIS permIds)
- Duplicate codes are skipped with an INFO log message.
- Missing parent objects cause the row to be skipped with an ERROR log message.
