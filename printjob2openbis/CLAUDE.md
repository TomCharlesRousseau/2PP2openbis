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
- `collections.printjobs | samples | washing | cpd | sintering | imaging | poli`: collection codes (`poli` = 3DPoli job objects)
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
Resin ──────────────┤
3DPoli job (opt.) ──┼─> Print step  2PP-000001                  (EXPERIMENTAL_STEP, one per print)
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
| 3DPoli job `2PP_POLI_<file name>` (GENERAL_PROTOCOL, one per job file) | `$name` = file name, `general_protocol.protocol_type` = `3DPoli job file (Femtika 2PP)`, `notes` (job file path); dataset `RAW_DATA` = the job `.txt` |
| Imaging step | `$name` = code, `start_date`, `operator`, `notes`, `experimental_step.experimental_description` (Technique, Sample state, Image folder) |

Descriptions are HTML: one `<p>` per Excel section with `Header: value` lines. Empty values and
columns that have their own property or parent link are left out. Footer:
`Uploaded using 2PP2openbis version <version>`.

### Upload Behaviour
- Order: 3DPoli job objects → print steps → printed samples → washing → CPD → sintering → sintered samples → imaging.
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

### Next Step 1: 3DPoli Job File as Dataset on a GENERAL_PROTOCOL Object
The PrintJobs column **3DPoli job file** holds the path of the 3DPoli job `.txt`
(the script run on the Femtika printer, stored on the network share under
`2PP/Experimente chronologisch/`). Today the path only appears in the print step description.

For each distinct job file:
- Create one openBIS object of type `GENERAL_PROTOCOL` in the 3DPoli collection
  (a job file is a fabrication recipe, not material; `SAMPLE` was the first idea)
  (new key `collections.poli` in the private settings.json).
- Upload the `.txt` file as a **dataset** of type `RAW_DATA` linked to that object (not an
  attachment: datasets are the BAM Data Store standard and the only option of the later
  bam-masterdata parser, see the last section).
- No mandatory property on `GENERAL_PROTOCOL` (verified); no `description` property, the path goes to `notes`.
- Deduplicate: several prints using the same job file share one object.
- Dry mode and update mode apply as for the other objects.

Decisions:
- **Code from the file name**: `2PP_POLI_<file name without .txt>`, uppercased, spaces → `_`,
  characters outside `A-Z 0-9 _ - .` removed (umlauts transliterated: Ä → AE …).
  Example: `20260303_Array mit Text Logo und QR Code-fix2.txt`
  → `2PP_POLI_20260303_ARRAY_MIT_TEXT_LOGO_UND_QR_CODE-FIX2`.
  `$name` = the original file name. Renaming the file creates a new object (accepted).
- **Parent of the print step**: Printer + Resin + Substrate + 3DPoli job → Print step.
  The job object is therefore created *before* the print steps.

- **Changed job file**: compared by **content**, not by name or date (details in Step 3).
  - Same content as a dataset already on the object → nothing uploaded (no duplicates).
  - Different content, default mode → WARNING `job file changed since upload; run with --update`, nothing uploaded.
  - Different content, `--update` → WARNING `job file changed, uploading a new dataset`, new dataset
    uploaded; the old dataset is kept (history of the job file).

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
- Do not copy NAS credentials or local user paths from `3DPoliFabrication.ini` anywhere.

Decision: **standalone module** (e.g. `femtika_fill/`), no openBIS login, no import from `openbis/`
or `config/settings.py`; callable alone (`python -m femtika_fill <excel>`), `python main.py fill`
only delegates to it. Built generically (source folder → file inventory → mapping table as data →
writer → summary) but kept in this repo; move it to its own repo once a second use case exists.
Summary per row and total, e.g. `Row 5: 9/12 cells filled, 2 already filled (kept),
1 missing (calibration.json not found)`.
Workflow: the fill command It writes the values into the Excel file;
the user opens it in Excel, checks the values, saves (Excel recalculates the formula caches
that openpyxl drops), then runs `check` / `upload`. `check` / `upload` never read the Femtika folder.

- Rows to fill: all rows with a Femtika output folder

## Implementation Plan (Next Steps)
Order decided: 3DPoli job file first (Steps 1–3), then Femtika auto-fill (Steps 4–6).
Each step ends with all tests passing and is committed separately.

### Step 1: 3DPoli job model and checks (done)
- `models/printjob.py`: `PrintJob.poli_job_code` property (code from the file name, rule above)
  in a helper `poli_code_from_filename(name) -> str`, next to the other code properties.
- `checks/checker.py`, when **3DPoli job file** is filled (the column stays optional):
  - file name ends in `.txt`, derived code valid (`CODE_PATTERN`) → else ERROR, print blocked (Stage.PRINT);
  - file exists and is readable → else ERROR, print blocked (the job is a parent of the print step);
  - two different paths giving the same code (same file name in two folders) → ERROR on both rows.
- Tests: `tests/test_models.py` (code rule, umlauts, spaces, example above),
  `tests/test_checker.py` (each new ERROR, empty column = no issue). Use `tmp_path` files, not the share.

### Step 2: 3DPoli object creation + parent link (done)
- `config/settings.py`: `"poli"` added to `COLLECTION_GROUPS`; `main.UPLOAD_GROUPS` too;
  `settings.json.example` gets `collections.poli`.
- `openbis/object_builders.py`: `poli_job(job, collection_path) -> NewObject`
  (type `GENERAL_PROTOCOL`, `$name` = file name, protocol type, `notes` = job file path + footer).
- `openbis/uploader.py`:
  - new level `_upload_poli_jobs` run **before** `_upload_print_steps`, one object per distinct code
    (deduplicated like runs); a failure blocks every print using that job (Stage.PRINT);
  - `print_step` parents gain the job permId when the column is filled;
    existing print steps get the link through the existing `add_parents` logic.
  - `_candidate_codes` includes the job codes.
- Tests: `tests/test_uploader.py` with the fake manager: one object for two prints sharing a file,
  print step parents include the job, failed job blocks its prints, dry-run writes nothing.

### Step 3: Job file dataset (done)
- `NewObject` gets `dataset_files: List[Path]` (default empty); `poli_job` sets it to the job file.
- `ObjectManager.upload_dataset(permid, code, files)` and `dataset_files(permid)`: after the object exists,
  `openbis.new_dataset(type="RAW_DATA", sample=<object>, files=[...]).save()`.
  Dry-run logs `would upload dataset <file name>`. `RAW_DATA` exists on the instance (verified).
- Existing job object: list the files of **all** its datasets and compare with the local file:
  1. **Checksum from openBIS, no download** (verified on our instance, pybis 1.37.5):
     `dataset.get_files()` returns a DataFrame with columns `isDirectory`, `pathInDataSet`,
     `fileSize`, `crc32Checksum` (hex text, e.g. `9686806d`; no SHA-256). Files sit under
     `original/<file name>`. Compare `fileSize` and CRC32 with the local file:
     `int(crc32Checksum, 16) == zlib.crc32(data)` (compare as integers, leading zeros may be missing).
  2. **Checksum empty / 0** (not seen on our instance): WARNING, nothing uploaded (no risk of a
     duplicate). Downloading and comparing bytes was considered but not implemented.
  - Match with any dataset (also an older one) → skip. No dataset → upload (covers an earlier run
    where the object was created but the upload failed). No match → rules of "Changed job file" above.
- A failed dataset upload: ERROR in the log and report, the object and the prints stay valid
  (the print step link does not depend on the file).
- Report status shows the dataset (`created + dataset`).
- Tests: fake manager records dataset uploads (new object; existing object with no dataset,
  same content, changed content with and without `--update`; dry-run); one manual test upload in a test collection
  (ask the user which project / collection before writing to openBIS).

### Step 4: Femtika output folder reader
- New package `femtika/`: `reader.py` with a `FemtikaRun` dataclass (typed fields for every value
  in the column mapping, `None` if a file / key is missing) and `read_run_folder(path) -> FemtikaRun`.
  Reads only `timing.json`, `structure.json`, `calibration.json`, `Script.txt` (first 2 lines),
  `3DPoliFabrication.ini` (only the `Sample …` keys). JSON files start with a UTF-8 BOM: open with `utf-8-sig`.
- A missing or unreadable file → WARNING and the fields stay `None`; never an exception for one run.
- Tests: small **synthetic** fixture folder `tests/fixtures/femtika_run/` (made-up values;
  the real example folder is git-ignored and must not be copied into tests).

### Step 5: Column mapping + `fill` command
- `femtika/fill.py`: `FILL_MAP` (PrintJobs field → function of `FemtikaRun`), only the rows of the
  confirmed mapping table; `fill_workbook(excel_path, dry_run) -> FillReport`.
- Writes with openpyxl by header name (reuse `column_mapping`), only empty non-formula cells;
  differing filled cells → WARNING, kept.
- Before writing: refuse if the file is open in Excel (`~$` lock file), save a backup copy
  `<name>_backup_<timestamp>.xlsx`. Check first on a copy of the template that an openpyxl
  round-trip keeps data validation, comments, colours and formulas.
- `main.py`: subcommand `fill [--dry-run] [--excel PATH]`; prints per row what was / would be filled,
  and reminds the user to open and save the file in Excel.
- The **Femtika output folder** cell: full path, or folder name relative to a new setting
  `femtika.logs_dir` (to decide).
- Tests: build a workbook with `tests/workbook_builder.py`, run `fill` against the fixture folder,
  re-read the cells; filled cells untouched; formula columns untouched.

### Step 6: Link the two features
- `fill` also fills **3DPoli job file** from `Script.txt` `Source:` once the path mapping
  printer PC → network share is known (setting, e.g. `femtika.job_path_map`).

### Before starting Step 4 (information needed from the user)
- Confirm the "to confirm" rows of the column mapping (laser power, scan speed, geometry: which stage, SC or SO).
- Units of the geometry columns: absolute stage positions (e.g. z = 59764 µm) or relative to the start?
- How Femtika output folder cells are filled today (example value, anonymised).
- Printer-PC path → network path rule for the 3DPoli job file.

## Later: bam-masterdata Parser for the openBIS Upload Helper
Decision: **finish this CLI first**, exactly as designed. A second solution that follows
`bam-masterdata` / `openbis-upload-helper` (BAMresearch on GitHub) is built later, so colleagues
can keep using it with the BAM app. Do not restructure this project for it now.

How that framework works (checked in the `bam-masterdata` source):
- Parser class inherits `AbstractParser`, implements `parse(files, collection, logger)`;
  new package from the `openbis-parser-example` template, registered by entry point, bundled in app releases.
- The parser only builds objects (`ExperimentalStep`, `Sample` …) and relationships in memory;
  the app logs in and writes. The parser gets **no openBIS session**: no lookups, no online checks.
- Existing code → properties always updated (no skip, no dry-run). Missing parent → warning, link skipped.
- Files: datasets only (`add_dataset`, type `RAW_DATA`), no attachments. The selected input files
  are also uploaded as a dataset into the chosen collection.
- Existing parents can be referenced as `{"permId": ...}` in `add_relationship`.

Keep the later migration cheap while finishing this project:
- Keep openBIS access only in `openbis/` (connection, object_manager, uploader, lookup);
  reader, models, checks (offline part), descriptions and `object_builders` stay free of pybis.
- Keep codes deterministic (`2PP_…`), as the framework finds existing objects by code.
- Keep `fill` a separate command (a parser must not modify its input file).

Planned shape of the later solution: a new parser repo holds the shared core (reader, models,
offline checks, builders → masterdata objects); this CLI may then depend on it for its extras
(online check, dry-run, skip / `--update`, CSV report, `fill`). Project settings (collections,
printer permId, `bam_oe`) would move into the workbook (Settings / Lists sheet) instead of code.
