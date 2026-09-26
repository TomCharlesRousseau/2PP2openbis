# printjob2openbis Project

## Overview
Python CLI that reads the 2PP print protocol (Excel workbook, layout **v5**), checks it,
and creates the openBIS objects of every print and its post-processing:
print steps, printed samples, washing / CPD / sintering runs, sintered samples, imaging steps.

> Real URLs, usernames, space / project / collection codes, permIds and paths go in the
> git-ignored `config/settings.json`, never in tracked files (this one included).

## Terminology
- **Substrate** = UV-Sheet (use "Substrate" consistently in code and comments)
- **Print** = one PrintJobs row = one structure printed with the Femtika printer
- **Run** = one washing / CPD / sintering batch, shared by several prints (same Run ID)

## Command Line
Run from `printjob2openbis/`:
```
python main.py check  [--offline] [--excel PATH]
python main.py upload [--dry-run] [--update] [--excel PATH]
```
- `check`: validates the workbook, writes nothing. Online (default) it also logs in and
  verifies that every referenced permId exists and that `bam_oe` is a BAM_OE term.
  `--offline`: Excel checks only.
- `upload`: runs the online check, then creates the objects.
  - `--dry-run`: reads openBIS, writes nothing, logs what would happen.
  - `--update`: also overwrites properties of existing objects that differ from the Excel
    (empty cells never clear a stored value).
- Login: `openbis_utils.connect_openbis` (keyring PAT, password prompt fallback).
- End report: CSV `code, type, permId, status, origin` in `output.report_dir` (git-ignored).

## Configuration (`config/settings.json`, git-ignored)
Template: `config/settings.json.example`. Keys:
- `openbis.api_url`, `openbis.username`, `openbis.space`, `openbis.project`
- `collections.printjobs | samples | washing | cpd | sintering | imaging`: collection codes
- `printer.permid`: instrument, parent of every print step
- `properties.bam_oe`: mandatory `bam_oe` of every SAMPLE
- `excel.file_path` (default `2PP_print_protocol_v5.xlsx`), `output.report_dir` (default `reports`)
- `version`: written in the footer of every description

## Excel Workbook (layout v5)
- The real workbook `2PP_print_protocol_v5.xlsx` is git-ignored. Shareable header-only copy:
  `example.xlsx`, built / verified with `tools/make_example_workbook.py` (run `--check` before every commit).
- The layout is final; change it only on user request.
- Sheets: **PrintJobs**, **Imaging**, **Lists** (required); README / Model / Columns (documentation, optional).
- Row 1 = section band, row 2 = headers, data from row 3.
- Columns are found **by header name, never by letter**. `excel/column_mapping.py` is the source of truth.
- Grey formula columns are read from Excel's cached values: the file must be saved by Excel
  (the checker detects a file that was not recalculated).
- `openBIS upload` column: empty / `Yes` = upload, `No` = row ignored everywhere.

### PrintJobs (one row per print; key column = Print code)
| Section | Headers (formula columns in *italics*) |
|---------|---------|
| General | Print code, *Print name*, Print date, Print operator, Design, 3DPoli job file, Purpose, Print status (`OK` / `Partial` / `Failed`) |
| Materials | Resin name, *Resin permId*, Substrate name, Substrate permId, Spacer type, Spacer count, Spacer thickness [mm] |
| Printer files | Femtika output folder |
| Printer settings | Objective, R, Max laser power (calibration) [mW], Laser power [mW], Scan speed [mm/s], Slicing distance [µm], Hatching distance [µm], Infinite FOV, Tilt compensation, Tilt alpha [°], Tilt beta [°], Print duration [min] |
| Print geometry | z start [µm], z end [µm], *z height [µm]*, x start [µm], x end [µm], *x width [µm]*, y start [µm], y end [µm], *y depth [µm]* |
| Washing | Washing date, Washing run ID (`WASH-…`), Washing operator, Washing solvent, Washing duration [min] |
| Drying (CPD) | CPD date, CPD run ID (`CPD-…`), CPD operator, CPD program |
| Sintering | Sintering date, Sintering run ID (`SINT-…`), Sintering operator, Furnace name, *Furnace permId*, Furnace program, Max temperature [°C], Dwell time [h], Sintering profile file |
| openBIS / Notes | openBIS upload, Comments |

### Imaging (one row per imaging event)
Print code, *Print name*, *Substrate permId*, Technique, Sample state (`Green` / `Sintered`),
Imaging date, Imaging operator, *Instrument permId*, Image folder, Notes, openBIS upload.

## openBIS Object Model
```
Printer (settings) ─┐
Resin ──────────────┼─> Print step  2PP-000001                  (EXPERIMENTAL_STEP, one per print)
Substrate ──────────┘        │
     │                       v
     └─────────────────> Printed sample  2PP_PRINTED_2PP-000001 (SAMPLE, not for Failed prints)
                             │
                             v
                         Washing run    2PP_WASH-0012   (EXPERIMENTAL_STEP shared by all prints with this run ID)
                             v
                         CPD run        2PP_CPD-0007
                             v
          Furnace ─────> Sintering run  2PP_SINT-0003
                             │     + printed sample
                             v
                         Sintered sample  2PP_SINTERED_2PP-000001 (SAMPLE)

Imaging step  2PP_IMG_<print code>_<technique>_<state>_<YYYYMMDD>  (EXPERIMENTAL_STEP)
    parents: printed (Green) or sintered sample, + instrument if filled
```
- One sample **per print** (not per substrate).
- Run steps: parents = de-duplicated union of the previous objects of all prints in the run.
- Samples are always washed, then dried, then sintered (order enforced by the checker).
- Codes are uppercased. Each group goes to its own collection from `settings.collections`.

### Properties (verified codes, see the openbis-properties skill)
| Object | Properties |
|--------|-----------|
| Print step | `$name` = Print name, `start_date` = Print date, `operator` = Print operator, `experimental_step.experimental_goals` = Purpose, `experimental_step.experimental_results` = Print status, `notes` = Comments, `experimental_step.experimental_description` |
| Run step | `$name` = code, `start_date`, `operator`, `experimental_step.experimental_description` (the step's own columns) |
| Sample | `$name` = code, `bam_oe`, `description` (Print code, Design, Substrate name, Resin name) |
| Imaging step | `$name` = code, `start_date`, `operator`, `notes`, `experimental_step.experimental_description` (Technique, Sample state, Image folder) |

Descriptions are HTML: one `<p>` per Excel section with `Header: value` lines. Empty values and
columns that have their own property or parent link are left out. Footer:
`Uploaded using 2PP2openbis version <version>`.

### Upload Behaviour
- Order: print steps → printed samples → washing → CPD → sintering → sintered samples → imaging.
- Existing code: log `INFO: <TYPE> <CODE> already exists. Skipping.`, add missing parent
  links (never remove), update properties only with `--update`.
- Existing code with another type: ERROR, print blocked.
- A print that fails at one stage is blocked for every later stage; a failed run blocks all its prints.
- Missing collection: nothing uploaded.

## Checks (`checks/checker.py`)
ERRORs block the row from the affected stage on; WARNINGs do not (unless marked blocking).
- File: required sheets / headers present, no duplicate headers, formula cache present,
  `printer.permid` is a permId, `bam_oe` is a BAM_OE term (online).
- Print: Print code unique and valid in a code. Required: Print date, Print operator, Design,
  Resin name, Resin permId, Substrate permId, Objective. Print status in the list (empty = blocking).
  Dates are dates; permIds well-formed and (online) existing. `Failed` → post-processing ignored.
- Steps: once a step date is filled, its Run ID and operator are required (+ solvent for washing,
  furnace for sintering). Run ID prefix. Order Washing → CPD → Sintering with non-decreasing dates.
  A Run ID is used for one step kind only. All prints of a run have identical values in the step's
  columns. WARNING if prints on one substrate have different step dates.
- Imaging: Print code exists in PrintJobs (not `No`, not Failed); required values; `Sintered`
  only if the print was sintered; (Print code, Technique, Sample state, Imaging date) unique.

## Project Structure
```
printjob2openbis/
├── main.py                     # CLI: check / upload
├── config/settings.py          # Settings singleton (settings.json)
├── excel/
│   ├── column_mapping.py       # v5 headers → model fields, sections
│   ├── excel_reader.py         # workbook → ProtocolData
│   └── description_builder.py  # HTML descriptions, value formatting
├── models/                     # PrintJob, ImagingEvent, StepKind / Run, CellValue
├── checks/                     # checker.py, issues.py (Issue, Stage, CheckResult)
├── openbis/
│   ├── object_builders.py      # models → NewObject (pure, no openBIS access)
│   ├── object_manager.py       # pybis gateway (find, create, link, update, dry-run)
│   ├── uploader.py             # upload order, blocking, CSV report
│   └── lookup.py               # permId / vocabulary lookups
├── tools/make_example_workbook.py
├── private/                    # git-ignored (template generator with real Lists data)
├── utils/logger.py
└── tests/                      # pytest; workbook_builder.py builds test workbooks
```

## Dependencies
- openpyxl, pybis, requests
- openbis_utils (not on PyPI; `pip install -e ../openbis-utils`)

## Code Quality
- Type hints and docstrings required
- Modular and extensible
- No Streamlit interface

## Next Steps

### Next Step 1: 3DPoli Job File as Attachment on a SAMPLE Object
The PrintJobs column **3DPoli job file** holds the path of the 3DPoli job `.txt`
(the script run on the Femtika printer, stored on the network share under
`2PP/Experimente chronologisch/`). Today the path only appears in the print step description.

For each distinct job file:
- Create one openBIS object of type `SAMPLE` in the 3DPoli collection
  (new key `collections.poli` in settings.json: the `3DPOLI` collection of the 2PP project).
- Attach the `.txt` file to that object as an **attachment** (not a dataset).
- `bam_oe` is mandatory on `SAMPLE`.
- Deduplicate: several prints using the same job file share one object.
- Dry mode and update mode apply as for the other objects.

Open questions (decide before implementing):
- Code / name convention of the 3DPoli object (e.g. from the job file name).
- Relationship to the print: 3DPoli object as parent of the print step?
- Update mode: replace the attachment if the file content changed?

### Next Step 2: Auto-fill the Excel Sheet from the Femtika Output Folder
Fill PrintJobs columns automatically instead of by hand, by reading the folder given in
**Femtika output folder**. Manual entry stays the fallback.

Each print run creates one folder `<job name>_<YYYYMMDD>_<HHMMSS>/` in the
"3DPoli fabrication logs" directory (network share). Local copy for development:
`printjob2openbis/Femtika output example/` (git-ignored, do not commit).

#### Files in a run folder
| File | Content |
|------|---------|
| `timing.json` | `start`, `end` (ISO), `duration_s`, `aborted` |
| `structure.json` | `est_time_s`, `tilt_alpha_deg`, `tilt_beta_deg`, `rotation_gamma_deg`; per stage (`ST1` = XYZ, `ST2` = galvo ABC, `TOT` = sum, `ATT` = attenuator) the `SO_min/max_um`, `SC_min/max_um`, velocities; `TOT.building_volume_um3` |
| `structure.txt` | Same as `structure.json`, human-readable (use the JSON) |
| `calibration.json` | `max_power_mW`, `p_axis_at_run_start`, `voltage[]` / `power_mW[]` curve |
| `Script.txt` | Compiled job script; line 1 `{ <job name> }`, line 2 `{ Source: <path of the 3DPoli job .txt on the printer PC> }` |
| `3DPoliFabrication.ini` | Software settings: `Sample alpha/beta/gamma deg`, `Sample enable TC` (tilt compensation), `Sample enable ROT` |
| `*.ini` (AC, AF, ATT, LI12, PM, ST12) | Device settings (aberration controller, autofocus, attenuator, LED, powermeter, stages) |
| `Calibration.dat` | Binary calibration table: ignore |
| `FC0.PGM` | Compiled program (~5 MB): ignore |

#### Column mapping (proposal, to confirm)
| PrintJobs column | Source |
|------------------|--------|
| Print date | `timing.json` → `start` |
| Print duration [min] | `timing.json` → `duration_s / 60` |
| Print status | `timing.json` → `aborted` = true suggests `Failed` / `Partial` (operator decides; never set `OK` automatically?) |
| 3DPoli job file | `Script.txt` line 2 `Source:` (printer-PC path → map to network path?) |
| Max laser power (calibration) [mW] | `calibration.json` → `max_power_mW` |
| Laser power [mW] | `structure.json` → `ATT.SC_max_um.Z` / W axis in `structure.txt` (to confirm) |
| Scan speed [mm/s] | `structure.json` → `ST2.vel_SC_max_umps / 1000` (to confirm) |
| Tilt alpha [°] / Tilt beta [°] | `structure.json` → `tilt_alpha_deg` / `tilt_beta_deg` |
| Tilt compensation | `3DPoliFabrication.ini` → `Sample enable TC` (1 = yes) |
| x/y/z start/end [µm] | `structure.json` → `TOT.SC_min_um` / `SC_max_um` (to confirm: TOT vs ST2, SC vs SO) |
| Objective, R, Infinite FOV, Slicing / Hatching distance | Not found in the output folder: stay manual |

#### Rules
- Only fill empty cells; if a filled cell differs from the file value, log a WARNING and keep the cell.
- Never write formula (grey) columns.
- openpyxl drops cached formula values on save and the parser reads those caches:
  write to a copy or let Excel recalculate before parsing (decide the approach).
- Do not copy NAS credentials or local user paths from `3DPoliFabrication.ini` anywhere.

#### Open questions
- Separate command (e.g. `python main.py fill`) or automatic during `check` / `upload`?
- Which rows to fill: all rows with a Femtika output folder, or only rows not yet uploaded?

### Implementation Order (Next Steps)
- [ ] Step 1: Femtika output folder reader (`femtika/` module) + unit tests on the example folder
- [ ] Step 2: Excel auto-fill of printer settings / geometry from the reader
- [ ] Step 3: 3DPoli SAMPLE object creation in the 3DPOLI collection
- [ ] Step 4: Job file attachment + deduplication per job file
