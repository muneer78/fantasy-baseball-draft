from pathlib import Path
from duckdb_utils import connect, read_csv, write_csv

BASE = Path(__file__).resolve().parent

def main():
    con = connect()
    read_csv(con, BASE/"draftsheet.csv", "d")
    read_csv(con, BASE/"sleepers.csv", "s")
    write_csv(con, """
      SELECT DISTINCT d.*, s."Sleeper Count", s."Overrated Count", s."Experts"
      FROM d INNER JOIN s USING ("Player")
    """, BASE/"finaldraftsheet.csv")
    con.close()

if __name__ == "__main__":
    main()
