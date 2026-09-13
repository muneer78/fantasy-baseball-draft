"""DuckDB-backed Yahoo draft sheet builder.

This keeps the original CSV inputs/outputs but moves parsing, joins,
windowed z-scores, ranking and scoring into DuckDB.
"""
from pathlib import Path
from duckdb_utils import connect, read_csv, write_csv, normalize_name_sql

BASE = Path(__file__).resolve().parent

def main():
    con = connect()
    read_csv(con, BASE / "pitcher.csv", "p")
    read_csv(con, BASE / "hitter.csv", "h")
    read_csv(con, BASE / "FantasyPros_Fantasy_Baseball_Rankings_ALL.csv", "adp")
    read_csv(con, BASE / "laghezza.csv", "lag")

    con.execute("""
    CREATE OR REPLACE VIEW pitchers AS
    SELECT *,
      CASE WHEN coalesce("G",0)=0 OR coalesce("ER",0)=0 THEN 0
      ELSE ("GS"/("ER"*("GS"/"G"))) *
           ("IP"*("GS"/"G")) *
           power(("GS"+"G")/(2.0*"G"),2) END AS "EstimatedQS"
    FROM p
    """)
    desc = {r[0]: r[1].upper() for r in con.execute("DESCRIBE pitchers").fetchall()}
    nums = [c for c,t in desc.items() if c not in {"PlayerId","Name","GS","G","ER"} and any(x in t for x in ("INT","FLOAT","DOUBLE","DECIMAL","REAL"))]
    zexpr = []
    for c in [r[0] for r in con.execute("DESCRIBE pitchers").fetchall()]:
        if c in {"GS","G","ER"}: continue
        if c in nums:
            zexpr.append(f"CASE WHEN stddev_pop(\"{c}\") OVER()=0 OR stddev_pop(\"{c}\") OVER() IS NULL THEN 0 ELSE (\"{c}\"-avg(\"{c}\") OVER())/stddev_pop(\"{c}\") OVER() END AS \"{c}\"")
        else:
            zexpr.append(f'"{c}"')
    con.execute(f'CREATE OR REPLACE VIEW pz AS SELECT {", ".join(zexpr)} FROM pitchers')
    d = {r[0]: r[1].upper() for r in con.execute("DESCRIBE pz").fetchall()}
    nums = [c for c,t in d.items() if any(x in t for x in ("INT","FLOAT","DOUBLE","DECIMAL","REAL"))]
    score_parts = [f'"{c}" * {5 if c in {"K%+","BB%+","EstimatedQS"} else 1.5 if c in {"SV","Barrel%","xFIP-","SwStr%","F-Strike%","CSW%"} else 1}' for c in nums]
    write_csv(con, f'SELECT *, round({"+".join(score_parts)},2) AS "Total Z-Score_Pitcher" FROM pz ORDER BY "Total Z-Score_Pitcher" DESC', BASE/"ZPitchers.csv")

    con.execute("""
    CREATE OR REPLACE VIEW hz AS
    SELECT *,
      row_number() OVER () AS _rn
    FROM h
    """)
    d = {r[0]: r[1].upper() for r in con.execute("DESCRIBE hz").fetchall()}
    nums = [c for c,t in d.items() if c not in {"PlayerId","_rn"} and any(x in t for x in ("INT","FLOAT","DOUBLE","DECIMAL","REAL"))]
    zexpr = []
    for c in [r[0] for r in con.execute("DESCRIBE hz").fetchall()]:
        if c == "_rn": continue
        if c in nums:
            zexpr.append(f"CASE WHEN stddev_pop(\"{c}\") OVER()=0 OR stddev_pop(\"{c}\") OVER() IS NULL THEN 0 ELSE (\"{c}\"-avg(\"{c}\") OVER())/stddev_pop(\"{c}\") OVER() END AS \"{c}\"")
        else: zexpr.append(f'"{c}"')
    con.execute(f'CREATE OR REPLACE VIEW hz2 AS SELECT {", ".join(zexpr)} FROM hz')
    d = {r[0]: r[1].upper() for r in con.execute("DESCRIBE hz2").fetchall()}
    nums = [c for c,t in d.items() if any(x in t for x in ("INT","FLOAT","DOUBLE","DECIMAL","REAL"))]
    score = '+'.join(f'"{c}"' for c in nums); write_csv(con, f'SELECT *, round({score},2) AS "Total Z-Score_Hitter" FROM hz2 ORDER BY "Total Z-Score_Hitter" DESC', BASE/"ZHitters.csv")

    read_csv(con, BASE/"ZPitchers.csv", "zp")
    read_csv(con, BASE/"ZHitters.csv", "zh")
    con.execute('CREATE OR REPLACE VIEW a AS SELECT *, "Player" AS "Name" FROM adp')
    con.execute('CREATE OR REPLACE VIEW ak AS SELECT *, ' + normalize_name_sql('"Name"') + ' AS "Key" FROM a')
    for view in ["zp","zh","lag"]:
        namecol = '"Name"'
        if view == "lag":
            con.execute(f'CREATE OR REPLACE VIEW {view}k AS SELECT *, {normalize_name_sql(namecol)} AS "Key" FROM {view}')
        else:
            con.execute(f'CREATE OR REPLACE VIEW {view}k AS SELECT *, {normalize_name_sql(namecol)} AS "Key" FROM {view}')
    con.execute("""
      CREATE OR REPLACE VIEW final AS
      SELECT a.* EXCLUDE ("Key"),
             zp."Total Z-Score_Pitcher",
             zh."Total Z-Score_Hitter",
             lag."Rank" AS "LRank"
      FROM ak a
      LEFT JOIN zpk zp USING ("Key")
      LEFT JOIN zhk zh USING ("Key")
      LEFT JOIN lagk lag USING ("Key")
    """)
    write_csv(con, """
      SELECT
        "Name", "Team",
        coalesce(nullif("Total Z-Score_Pitcher",0),"Total Z-Score_Hitter",0) AS "Total Z-Score",
        try_cast("Rank" AS DOUBLE) - coalesce(nullif(try_cast("LRank" AS DOUBLE),0), try_cast("Rank" AS DOUBLE)) AS "RankDiff",
        coalesce(nullif(try_cast("LRank" AS DOUBLE),0), try_cast("Rank" AS DOUBLE)) AS "LRank",
        try_cast("Rank" AS DOUBLE) AS "ADP"
      FROM final
    """, BASE/"draftsheet.csv")
    con.close()

if __name__ == "__main__":
    main()
