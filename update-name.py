from pathlib import Path
from duckdb_utils import connect, read_csv, write_csv

BASE = Path(__file__).resolve().parent

def main():
    con = connect()
    read_csv(con, BASE/"fbexcluded.csv", "x")
    write_csv(con, """
      SELECT regexp_replace("PLAYER NAME", '[^a-zA-Z0-9 ]| Jr| III', '', 'g') AS "PLAYER NAME"
      FROM x
    """, BASE/"fbexcluded.csv")
    con.close()

if __name__ == "__main__":
    main()
