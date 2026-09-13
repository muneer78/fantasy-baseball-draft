from __future__ import annotations

import re
from pathlib import Path
import duckdb


def connect(database: str = ":memory:") -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(database)
    con.execute("SET threads = 4")
    return con


def qi(name: str) -> str:
    """Quote an SQL identifier."""
    return '"' + name.replace('"', '""') + '"'


def read_csv(con, path: str | Path, view_name: str):
    path = str(path).replace("\\", "/").replace("'", "''")
    con.execute(
        f"CREATE OR REPLACE VIEW {qi(view_name)} AS "
        f"SELECT * FROM read_csv_auto('{path}', header=true, sample_size=-1)"
    )
    return view_name


def write_csv(con, query: str, path: str | Path):
    path = str(path).replace("\\", "/").replace("'", "''")
    con.execute(
        f"COPY ({query}) TO '{path}' (HEADER, DELIMITER ',')"
    )


def normalize_name_sql(expr: str) -> str:
    # Matches the repo's existing "first 3 chars of each word" key closely,
    # while also stripping punctuation and suffixes first.
    cleaned = (
        f"regexp_replace(regexp_replace(regexp_replace("
        f"lower(coalesce({expr}, '')), '[^a-z0-9 ]', '', 'g'), "
        f"'\\b(jr|ii|iii)\\b', '', 'g'), '\\s+', ' ', 'g')"
    )
    return (
        "array_to_string("
        f"list_transform(string_split(trim({cleaned}), ' '), x -> left(x, 3)), "
        "''"
        ")"
    )


def numeric_columns(con, view: str, exclude: tuple[str, ...] = ()) -> list[str]:
    rows = con.execute(f"DESCRIBE {qi(view)}").fetchall()
    excluded = {x.lower() for x in exclude}
    return [
        r[0] for r in rows
        if r[1].upper() in {
            "TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT",
            "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT", "UHUGEINT",
            "FLOAT", "DOUBLE", "DECIMAL", "REAL"
        } and r[0].lower() not in excluded
    ]


def zscore_select(con, view: str, id_columns: tuple[str, ...] = ()) -> str:
    """
    Build a SELECT that z-scores every numeric column in a relation.
    This replaces scipy.stats.zscore with DuckDB's stddev_pop().
    """
    nums = numeric_columns(con, view, id_columns)
    allcols = [r[0] for r in con.execute(f"DESCRIBE {qi(view)}").fetchall()]
    parts = []
    for c in allcols:
        if c in nums:
            parts.append(
                f"CASE WHEN stddev_pop({qi(c)}) OVER () = 0 OR "
                f"stddev_pop({qi(c)}) OVER () IS NULL THEN 0 "
                f"ELSE ({qi(c)} - avg({qi(c)}) OVER ()) / "
                f"stddev_pop({qi(c)}) OVER () END AS {qi(c)}"
            )
        else:
            parts.append(qi(c))
    return ", ".join(parts)
