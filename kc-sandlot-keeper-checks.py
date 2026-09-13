from pathlib import Path
from duckdb_utils import connect, read_csv

BASE = Path(__file__).resolve().parent

def main():
    con = connect()
    read_csv(con, BASE/"sandlotkeeperlist.csv", "k")
    a, ap, b, total = con.execute("""
      SELECT
        count(*) FILTER (WHERE "Group"='A'),
        count(*) FILTER (WHERE "Group"='A' AND "Position" IN ('SP','RP')),
        count(*) FILTER (WHERE "Group"='B'),
        count(*)
      FROM k WHERE "Name" IS NOT NULL
    """).fetchone()
    messages = []
    if a > 7: messages.append(f"You have {a} A keepers. You can have up to 7")
    if ap > 4: messages.append(f"You have {ap} pitchers in group A. You can have up to 4")
    if b > 6: messages.append(f"You have {b} B keepers. You can have up to 6")
    if total > 15: messages.append("You have too many keepers listed")
    for m in messages: print(m)
    print(con.execute("""
      SELECT "Group", count(*) AS "Name"
      FROM k WHERE "Name" IS NOT NULL
      GROUP BY "Group" ORDER BY "Group"
    """).df().to_string(index=False))
    con.close()

if __name__ == "__main__":
    main()
