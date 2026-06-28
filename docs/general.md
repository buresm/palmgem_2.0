# General

## Architecture

PALM-GeM runs a configurable sequence of tasks. Each task extends `BaseTask` and operates on the same PostGIS database connection. Tasks are registered in `TaskFactory` and executed in order by `main.py`.

`setup` and `finalize` always run implicitly (first and last). Only the tasks listed in `run_tasks` in your user config run in between.

See [CLAUDE.md](../CLAUDE.md) or the source in `src/tasks/` for the full task list.

---

## Logging

Six log levels control how much output is printed to the terminal and written to `logs/<name><scenario>.log`.

Configure with `logs.level` in your YAML (use the numeric value):

| Level | Numeric value | When to use |
|:------|:-------------:|:------------|
| EXTRA_VERBOSE | 5 | Every SQL query; heavy loop output. Development only. |
| DEBUG | 10 | Detailed step-by-step progress inside functions. |
| VERBOSE | 15 | Notable sub-steps, useful for tracing slow runs. |
| PROGRESS | 25 | High-level task progress. **Default for production runs.** |
| WARNING | 30 | Non-fatal issues (missing optional data, fallback used). |
| ERROR | 40 | Fatal errors that abort the run. |

A lower number means more output. Set `logs.level: 25` for normal runs; set `logs.level: 10` or `logs.level: 5` when debugging.

---

## Surface types

PALM-GeM uses integer codes to identify PALM surface types. The ranges are:

| Category | Range |
|:---------|:------|
| vegetation_type | 100 – 199 |
| pavement_type | 200 – 299 |
| water_type | 300 – 399 |
| building_type | 900 – 999 |

---

## UrbanAtlas → PALM type mapping

The table below shows the default mapping from UrbanAtlas codes to PALM types. The mapping can be overridden in your user config via the `mt` dictionary.

UA = UrbanAtlas / OSM = OpenStreetMap

| **UrbanAtlas type** | **PALM type (no OSM)** | **PALM type (with OSM)** |
|:------------------|:----------------|:----------------|
| 11100 | 203 | 901 |
| 11210 | 203 | 902 |
| 11220 | 203 | 903 |
| 11230 | 203 | 902 |
| 11240 | 203 | 903 |
| 11300 | 203 | 903 |
| 12100 | 203 | 906 |
| 12210 | 201 | 906 |
| 12220 | 202 | 906 |
| 12230 | 209 | 906 |
| 12300 | 203 | 906 |
| 12400 | 103 | 906 |
| 13100 | 101 | 906 |
| 13300 | 101 | 906 |
| 13400 | 108 | 906 |
| 14100 | 118 | 906 |
| 14200 | 103 | 906 |
| 21000 | 102 | 906 |
| 22000 | 101 | 906 |
| 23000 | 103 | 906 |
| 24000 | 102 | 906 |
| 25000 | 102 | 906 |
| 31000 | 117 | 906 |
| 32000 | 110 | 906 |
| 33000 | 112 | 906 |
| 40000 | 110 | 906 |
| 50000 | 301 | 906 |
