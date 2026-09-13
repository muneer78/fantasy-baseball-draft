from pathlib import Path
import duckdb

BASE = Path(__file__).resolve().parent

def main():
    con = duckdb.connect()
    con.execute("CREATE OR REPLACE VIEW h AS SELECT * FROM read_xlsx(?, header=true)", [str(BASE/"Hitters.xlsx")])
    con.execute("CREATE OR REPLACE VIEW p AS SELECT * FROM read_xlsx(?, header=true)", [str(BASE/"Pitchers.xlsx")])
    con.execute("""
      COPY (
        SELECT "Name", "Total Z-Score" FROM h
        UNION ALL
        SELECT "Name", "Total Z-Score" FROM p
        ORDER BY "Total Z-Score" DESC
      ) TO ? (HEADER)
    """, [str(BASE/"TotalZScore.csv")])
    con.close()

if __name__ == "__main__":
    main()
