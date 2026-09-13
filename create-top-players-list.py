from pathlib import Path
from duckdb_utils import connect, read_csv, write_csv, normalize_name_sql

BASE = Path(__file__).resolve().parent

def main():
    con = connect()
    read_csv(con, BASE/"fg.csv", "hit")
    read_csv(con, BASE/"fg2.csv", "pit")
    read_csv(con, BASE/"adp.csv", "adp")
    con.execute(f'CREATE OR REPLACE VIEW hk AS SELECT *, {normalize_name_sql("\"Name\"")} AS "Key" FROM hit')
    con.execute(f'CREATE OR REPLACE VIEW pk AS SELECT *, {normalize_name_sql("\"Name\"")} AS "Key" FROM pit')
    con.execute(f'CREATE OR REPLACE VIEW ak AS SELECT *, {normalize_name_sql("\"Player\"")} AS "Key" FROM adp')
    write_csv(con, """
      SELECT coalesce(try_cast(pk."playerid" AS BIGINT), try_cast(hk."playerid" AS BIGINT)) AS playerid,
             a."Player"
      FROM ak a
      LEFT JOIN pk USING ("Key")
      LEFT JOIN hk USING ("Key")
      WHERE coalesce(try_cast(pk."playerid" AS BIGINT), try_cast(hk."playerid" AS BIGINT)) IS NOT NULL
      LIMIT 75
    """, BASE/"excluded.csv")
    con.close()

if __name__ == "__main__":
    main()
