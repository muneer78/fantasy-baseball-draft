from pathlib import Path
from duckdb_utils import connect, read_csv, write_csv

BASE = Path(__file__).resolve().parent

def main():
    con = connect()
    read_csv(con, BASE/"mlbbat.csv", "d")
    write_csv(con, """
      SELECT
        rank() OVER (ORDER BY (TB + BB) / 4 DESC) AS Rank,
        Tm, BatAge, "R/G",
        cast((TB + BB) / 4 AS INTEGER) AS OffenseCreated
      FROM d
      ORDER BY OffenseCreated DESC
    """, BASE/"mlb-team-offense-ranks.csv")
    con.close()

if __name__ == "__main__":
    main()
