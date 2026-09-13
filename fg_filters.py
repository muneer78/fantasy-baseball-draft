from pathlib import Path
import duckdb
from duckdb_utils import connect, read_csv

BASE = Path(__file__).resolve().parent

def run_hitter(input_file, output_file, off_min):
    con = connect()
    read_csv(con, BASE/input_file, "d")
    con.execute("""
      CREATE OR REPLACE VIEW x AS
      SELECT * EXCLUDE (Barrel)
      REPLACE (try_cast(regexp_replace(Barrel, '%', '', 'g') AS DOUBLE) AS Barrel)
      FROM d
    """)
    con.execute("""
      COPY (
        SELECT * FROM x
        WHERE wRC > 135
          AND OPS > 0.8
          AND K < 95
          AND BB > 100
          AND Off > ?
          AND Barrel > 10
        ORDER BY Off DESC
      ) TO ? (HEADER)
    """, [off_min, str(BASE/output_file)])
    con.close()

def run_pitcher(input_file, sp_output, rp_output):
    con = connect()
    read_csv(con, BASE/input_file, "d")
    con.execute("""
      CREATE OR REPLACE VIEW x AS
      SELECT * EXCLUDE (Barrel, CSW)
      REPLACE (
        try_cast(regexp_replace(Barrel, '%', '', 'g') AS DOUBLE) AS Barrel,
        try_cast(regexp_replace(CSW, '%', '', 'g') AS DOUBLE) AS CSW
      )
      FROM d
    """)
    con.execute("""
      COPY (
        SELECT * EXCLUDE (Relieving, SV)
        FROM x
        WHERE xERA < 3 AND Barrel < 7 AND Starting > 5 AND GS > 1
        ORDER BY Starting DESC
      ) TO ? (HEADER)
    """, [str(BASE/sp_output)])
    con.execute("""
      COPY (
        SELECT * EXCLUDE (Starting, GS)
        FROM x
        WHERE xERA < 3 AND Barrel < 7 AND Relieving > 1
        ORDER BY Relieving DESC
      ) TO ? (HEADER)
    """, [str(BASE/rp_output)])
    con.close()
