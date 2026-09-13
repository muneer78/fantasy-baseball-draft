from pathlib import Path
from duckdb_utils import connect, read_csv, write_csv, normalize_name_sql

BASE = Path(__file__).resolve().parent

def main():
    con = connect()
    read_csv(con, BASE/"sandlot-keepers.csv", "k")
    read_csv(con, BASE/"draftsheet.csv", "d")
    con.execute(f"""
      CREATE OR REPLACE VIEW kk AS
      SELECT *, CASE
        WHEN "Service Time" = 0 THEN 'C'
        WHEN "Service Time" BETWEEN 1 AND 4 THEN 'B'
        ELSE 'A' END AS "Group",
        {normalize_name_sql('"Name"')} AS "Key"
      FROM k WHERE "Name" IS NOT NULL
    """)
    con.execute(f'CREATE OR REPLACE VIEW dk AS SELECT *, {normalize_name_sql("\"Name\"")} AS "Key" FROM d WHERE "Name" IS NOT NULL')
    write_csv(con, """
      SELECT kk."Group", kk."Name", d."Team", kk."Position", kk."Service Time",
             d."Total Z-Score", d."LRank", d."ADP"
      FROM kk
      LEFT JOIN dk d USING ("Key")
      ORDER BY kk."Group", d."Total Z-Score" DESC
    """, BASE/"sandlotkeeperlist.csv")
    con.close()

if __name__ == "__main__":
    main()
