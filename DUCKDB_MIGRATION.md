# DuckDB migration

This branch/rewrite uses DuckDB for the parts of the repository that are
relational/analytical:

- CSV ingestion
- filtering
- joins
- aggregation
- ranking
- window functions
- z-score calculations
- sorting
- CSV output

Pandas is intentionally not used for the core transformations. DuckDB can
query CSV/Parquet directly and can also query Pandas/Polars objects when those
libraries are needed elsewhere.

## Main entry point

Run:

```bash
python baseballdraftsheet.py
```

It produces:

- `ZPitchers.csv`
- `ZHitters.csv`
- `draftsheet.csv`

The Fantrax wrapper runs the same DuckDB pipeline:

```bash
python baseballdraft-fantrax.py
```

The Yahoo script keeps its original CSV-oriented workflow:

```bash
python baseballdraft-yahoo.py
```

## Why DuckDB here?

The repository repeatedly loads CSVs into pandas, mutates columns, performs
multiple joins, and writes intermediate CSVs only to read them again. DuckDB
can execute those operations directly against the CSV relations, avoiding
many Python-level materialization and intermediate round trips.

The migration deliberately does **not** force DuckDB into API calls, string
formatting, interactive prompts, or other areas where it provides little
benefit.

## Notes

The original repository contains several old/experimental scripts and
notebooks. The rewritten versions preserve the existing filenames where
practical, but some original behaviors were clearly bugs (for example,
`player-drop-dates.py` assigns `pd.read_csv` itself rather than reading a
file, and `fangraphs.py` references `df4` without defining it). Those are
made executable rather than reproduced.
