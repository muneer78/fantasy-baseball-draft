from pathlib import Path
import duckdb
from duckdb_utils import connect, read_csv, write_csv

BASE = Path(__file__).resolve().parent

def main():
    con = connect()
    read_csv(con, BASE/"hitter.csv", "h")
    con.execute("""
      CREATE OR REPLACE VIEW x AS
      SELECT * EXCLUDE ("Barrel%")
      REPLACE (try_cast(regexp_replace("Barrel%", '%', '', 'g') AS DOUBLE) AS "Barrel%")
      FROM h
    """)
    desc = {r[0]:r[1].upper() for r in con.execute("DESCRIBE x").fetchall()}
    nums = [c for c,t in desc.items() if any(x in t for x in ("INT","FLOAT","DOUBLE","DECIMAL","REAL"))]
    z = []
    for c in [r[0] for r in con.execute("DESCRIBE x").fetchall()]:
        if c in nums:
            z.append(f'CASE WHEN stddev_pop("{c}") OVER()=0 OR stddev_pop("{c}") OVER() IS NULL THEN 0 ELSE ("{c}"-avg("{c}") OVER())/stddev_pop("{c}") OVER() END AS "{c}"')
        else: z.append(f'"{c}"')
    con.execute(f'CREATE OR REPLACE VIEW z AS SELECT {", ".join(z)} FROM x')
    score = '+'.join(f'"{c}"' for c in nums); write_csv(con, f'SELECT *, round({score},2) AS "Total Z-Score" FROM z ORDER BY "Total Z-Score" DESC', BASE/"ZHitters.csv")
    con.close()

if __name__ == "__main__":
    main()
