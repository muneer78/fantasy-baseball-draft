from pathlib import Path
import duckdb
from duckdb_utils import connect, read_csv, write_csv, qi, normalize_name_sql, zscore_select

BASE = Path(__file__).resolve().parent

def main():
    con = connect()

    # Pitcher z-scores.  Keep the same scoring weights as the original script,
    # but do the parsing, window statistics and arithmetic inside DuckDB.
    read_csv(con, BASE / "pitcher.csv", "pitchers_raw")
    pitcher_numeric = """
        try_cast(regexp_replace("F-Strike%", '%', '', 'g') AS DOUBLE) AS "F-Strike%",
        try_cast(regexp_replace("Barrel%", '%', '', 'g') AS DOUBLE) AS "Barrel%",
        try_cast(regexp_replace("CSW%", '%', '', 'g') AS DOUBLE) AS "CSW%",
        try_cast(regexp_replace("SwStr%", '%', '', 'g') AS DOUBLE) AS "SwStr%",
        try_cast(regexp_replace("HardHit%", '%', '', 'g') AS DOUBLE) AS "HardHit%"
    """
    con.execute(f"""
        CREATE OR REPLACE VIEW pitchers AS
        SELECT *,
          CASE WHEN coalesce("G",0)=0 OR coalesce("ER",0)=0 THEN 0
               ELSE ("GS" / ("ER" * ("GS"/"G"))) *
                    ("IP" * ("GS"/"G")) *
                    power(("GS"+"G")/(2.0*"G"), 2)
          END AS "EstimatedQS",
          {pitcher_numeric}
        FROM pitchers_raw
    """)
    # Replace the string percentage columns with parsed values.
    con.execute("""
        CREATE OR REPLACE VIEW pitcher_clean AS
        SELECT * EXCLUDE ("F-Strike%", "Barrel%", "CSW%", "SwStr%", "HardHit%")
        REPLACE (
          "F-Strike%" AS "F-Strike%",
          "Barrel%" AS "Barrel%",
          "CSW%" AS "CSW%",
          "SwStr%" AS "SwStr%",
          "HardHit%" AS "HardHit%"
        )
        FROM pitchers
    """)
    # DuckDB cannot conveniently mutate a view in place, so explicitly project
    # the scored columns.
    cols = [r[0] for r in con.execute("DESCRIBE pitcher_clean").fetchall()]
    exclude = {"ER", "GS", "G", "playerid"}
    numeric = []
    for c in cols:
        typ = con.execute(f'DESCRIBE pitcher_clean').fetchall()
    numeric = [c for c in cols if c not in {"playerid", "Name"}]
    # Use a whitelist based on runtime types.
    desc = {r[0]: r[1].upper() for r in con.execute("DESCRIBE pitcher_clean").fetchall()}
    numeric = [c for c,t in desc.items() if c not in exclude and any(x in t for x in ("INT","FLOAT","DOUBLE","DECIMAL","REAL"))]
    exprs = []
    for c in cols:
        if c in {"ER","GS","G"}:
            continue
        if c in numeric:
            exprs.append(
                f"CASE WHEN stddev_pop({qi(c)}) OVER () IS NULL OR stddev_pop({qi(c)}) OVER ()=0 "
                f"THEN 0 ELSE ({qi(c)}-avg({qi(c)}) OVER())/stddev_pop({qi(c)}) OVER() END AS {qi(c)}"
            )
        else:
            exprs.append(qi(c))
    scored = ", ".join(exprs)
    con.execute(f"""
        CREATE OR REPLACE VIEW zpitchers AS
        SELECT {scored}
        FROM pitcher_clean
    """)
    # Apply scoring weights and sum only numeric scored fields.
    desc = {r[0]: r[1].upper() for r in con.execute("DESCRIBE zpitchers").fetchall()}
    numeric2 = [c for c,t in desc.items() if any(x in t for x in ("INT","FLOAT","DOUBLE","DECIMAL","REAL"))]
    weighted = []
    for c in numeric2:
        factor = 1
        if c in {"SV","Barrel%","xFIP-","SwStr%","F-Strike%","CSW%"}: factor = 1.5
        if c in {"K%+","BB%+","EstimatedQS"}: factor = 5
        weighted.append(f"{qi(c)} * {factor}")
    score_expr = " + ".join(weighted) if weighted else "0"
    write_csv(con, f"""
        SELECT *, round(({score_expr}), 2) AS "Total Z-Score"
        FROM zpitchers
        ORDER BY "Total Z-Score" DESC
    """, BASE / "ZPitchers.csv")

    # Hitters.
    read_csv(con, BASE / "hitter.csv", "hitters_raw")
    con.execute("""
        CREATE OR REPLACE VIEW hitters_clean AS
        SELECT * EXCLUDE ("Barrel%")
        REPLACE (try_cast(regexp_replace("Barrel%", '%', '', 'g') AS DOUBLE) AS "Barrel%")
        FROM hitters_raw
    """)
    desc = {r[0]: r[1].upper() for r in con.execute("DESCRIBE hitters_clean").fetchall()}
    numeric = [c for c,t in desc.items() if c.lower() != "playerid" and any(x in t for x in ("INT","FLOAT","DOUBLE","DECIMAL","REAL"))]
    exprs = []
    for c in [r[0] for r in con.execute("DESCRIBE hitters_clean").fetchall()]:
        if c in numeric:
            exprs.append(
                f"CASE WHEN stddev_pop({qi(c)}) OVER () IS NULL OR stddev_pop({qi(c)}) OVER ()=0 "
                f"THEN 0 ELSE ({qi(c)}-avg({qi(c)}) OVER())/stddev_pop({qi(c)}) OVER() END AS {qi(c)}"
            )
        else:
            exprs.append(qi(c))
    con.execute(f"CREATE OR REPLACE VIEW zhitters AS SELECT {', '.join(exprs)} FROM hitters_clean")
    desc = {r[0]: r[1].upper() for r in con.execute("DESCRIBE zhitters").fetchall()}
    numeric = [c for c,t in desc.items() if any(x in t for x in ("INT","FLOAT","DOUBLE","DECIMAL","REAL"))]
    score = " + ".join(qi(c) for c in numeric) if numeric else "0"
    write_csv(con, f"""
        SELECT *, round(({score}), 2) AS "Total Z-Score"
        FROM zhitters
        ORDER BY "Total Z-Score" DESC
    """, BASE / "ZHitters.csv")

    # Final draft sheet: keep all joins in DuckDB and avoid repeated CSV round trips.
    for fn, view in [
        ("fg2.csv","fgpit"), ("stuffplus.csv","stuff"), ("adp.csv","adp"),
        ("ZPitchers.csv","zpit"), ("ZHitters.csv","zhit"),
        ("fg.csv","fghit"), ("laghezza.csv","laghezza")
    ]:
        read_csv(con, BASE / fn, view)

    # Name-key views.
    con.execute(f"""
        CREATE OR REPLACE VIEW adp_k AS
        SELECT *, {normalize_name_sql('"Player"')} AS "Key" FROM adp
    """)
    for view, namecol in [
        ("fgpit","Name"),("stuff","player_name"),("zpit","Name"),
        ("zhit","Name"),("fghit","Name"),("laghezza","Name")
    ]:
        con.execute(f"""
            CREATE OR REPLACE VIEW {view}_k AS
            SELECT *, {normalize_name_sql(qi(namecol))} AS "Key" FROM {view}
        """)
    con.execute("""
        CREATE OR REPLACE VIEW draft_join AS
        SELECT
          a.* EXCLUDE ("ESPN","CBS","RTS","NFBC","FT"),
          f.* EXCLUDE ("Key"),
          s."STUFFplus", s."LOCATIONplus", s."PITCHINGplus",
          p."Total Z-Score" AS "Pitcher Z",
          h."Total Z-Score" AS "Hitter Z",
          l."LaghezzaRank"
        FROM adp_k a
        LEFT JOIN fgpit_k f USING ("Key")
        LEFT JOIN stuff_k s USING ("Key")
        LEFT JOIN zpit_k p USING ("Key")
        LEFT JOIN zhit_k h USING ("Key")
        LEFT JOIN fghit_k fh USING ("Key")
        LEFT JOIN laghezza_k l USING ("Key")
    """)
    # Prefer pitcher z-score when present, otherwise hitter z-score.
    write_csv(con, """
        WITH x AS (
          SELECT *,
            coalesce(nullif("Pitcher Z", 0), "Hitter Z", 0) AS "Total Z-Score",
            coalesce(nullif(try_cast("LaghezzaRank" AS DOUBLE), 0), try_cast("Rank" AS DOUBLE)) AS "LaghezzaRank2"
          FROM draft_join
        )
        SELECT
          "Player", "Team", "Total Z-Score",
          try_cast("Rank" AS DOUBLE) AS "ADP",
          "LaghezzaRank2" AS "LaghezzaRank",
          try_cast("Rank" AS DOUBLE) - "LaghezzaRank2" AS "RankDiff"
        FROM x
        QUALIFY row_number() OVER (
          PARTITION BY "Player", "Rank" ORDER BY "Player"
        ) = 1
    """, BASE / "draftsheet.csv")

    con.close()

if __name__ == "__main__":
    main()
