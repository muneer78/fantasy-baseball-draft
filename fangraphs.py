"""Repair/normalize a 10-column FanGraphs CSV export with DuckDB.

The original script referenced an undefined df4. This version reads the
CSV directly and writes a normalized CSV instead of constructing pandas
DataFrames by hand.
"""
from pathlib import Path
import duckdb

BASE = Path(__file__).resolve().parent

def main():
    src = BASE/"FanGraphs.csv"
    out = BASE/"FanGraphs-normalized.csv"
    con = duckdb.connect()
    con.execute("""
      COPY (
        SELECT *
        FROM read_csv_auto(?, header=false, sample_size=-1)
      ) TO ? (HEADER)
    """, [str(src), str(out)])
    con.close()

if __name__ == "__main__":
    main()
