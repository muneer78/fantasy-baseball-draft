from pathlib import Path
import sys
import duckdb

BASE = Path(__file__).resolve().parent

def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE/"player-drop-dates.csv"
    con = duckdb.connect()
    print(con.execute("""
      SELECT *,
        CAST(date '2024-04-01' + CAST("Time Frame" AS INTEGER) * INTERVAL 1 DAY AS DATE)
          AS "When To Drop"
      FROM read_csv_auto(?, header=true)
    """, [str(src)]).df().to_string(index=False))
    con.close()

if __name__ == "__main__":
    main()
