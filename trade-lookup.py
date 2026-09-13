from pathlib import Path
from duckdb_utils import connect, read_csv

BASE = Path(__file__).resolve().parent

def lookup(con, names, side):
    # Exact/partial matching is performed in SQL; each requested name is a
    # parameter, avoiding regex construction from user input.
    rows = []
    for name in names:
        rows.extend(con.execute(
            'SELECT "Name", "Total Z-Score" FROM draft WHERE lower("Name") LIKE lower(?)',
            [f"%{name}%"]
        ).fetchall())
    seen = set()
    rows = [r for r in rows if not (r[0] in seen or seen.add(r[0]))]
    total = sum(float(r[1] or 0) for r in rows)
    print(f"The value for Side {side} is {total:.2f}")
    print(f"Players found in Side {side}:")
    for name, score in rows:
        print(f"{name}: {score}")

def main():
    con = connect()
    read_csv(con, BASE/"draftsheet.csv", "draft")
    n = int(input("How many players to lookup in Side A? "))
    lookup(con, [input(f"Enter name of player {i+1}: ") for i in range(n)], "A")
    n = int(input("How many players to lookup in Side B? "))
    lookup(con, [input(f"Enter name of player {i+1}: ") for i in range(n)], "B")
    con.close()

if __name__ == "__main__":
    main()
