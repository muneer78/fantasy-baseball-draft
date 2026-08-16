"""
Free Agent Z-Score Finder
==========================
Fetches free agents from your Yahoo Fantasy Baseball league via your fork of
yahoo-fantasy-baseball, cross-references them against MLB Stats API z-scores,
and writes a ranked CSV.

Designed to run locally or via GitHub Actions (commits free_agents.csv to repo).

Prerequisites:
  1. Fork & set up yahoo-fantasy-baseball:
       git clone https://github.com/YOUR_USERNAME/yahoo-fantasy-baseball yahoo-repo
       cd yahoo-repo
       python3 yahoo-fantasy-baseball.py --setup
       python3 yahoo-fantasy-baseball.py auth          # one-time OAuth
       python3 yahoo-fantasy-baseball.py config --league YOUR_LEAGUE_ID

  2. Install dependencies:
       pip install mlb-statsapi pandas

Usage:
  python3 free_agent_zscores.py [options]

Options:
  --league ID       Yahoo league ID (overrides stored config; or set YAHOO_LEAGUE_ID env var)
  --season YEAR     MLB season (default: 2026)
  --min-pa INT      Min plate appearances for hitter z-score pool (default: 50)
  --min-ip FLOAT    Min innings pitched for pitcher z-score pool (default: 10)
  --position POS    Filter free agents by position, e.g. OF, SP, RP, 3B
  --status STR      FA=free agents only, W=waivers, A=all available (default: A)
  --count INT       Number of free agents to pull from Yahoo (default: 500)
  --out FILE        Output CSV path (default: free_agents.csv)

CSV layout:
  Hitters  — Last 7 days   (R, HR, RBI, SB, OPS + z-scores)
  <2 blank rows>
  Hitters  — Last 14 days
  <2 blank rows>
  Pitchers — Last 14 days  (W, SV, K, ERA, WHIP + z-scores)
  <2 blank rows>
  Pitchers — Last 30 days
"""

import argparse
import json
import os
import re
import subprocess
import sys
import unicodedata
from datetime import date, timedelta

import statsapi
import pandas as pd

# ── Categories ────────────────────────────────────────────────────────────────
HITTER_CATS   = ["runs", "homeRuns", "rbi", "stolenBases", "ops"]
PITCHER_CATS  = ["wins", "saves", "strikeOuts", "era", "whip"]
NEGATIVE_CATS = {"era", "whip"}


# ── Date helpers ──────────────────────────────────────────────────────────────

def _date_range(days: int) -> tuple[str, str]:
    """Return (startDate, endDate) strings for the last N days."""
    end   = date.today()
    start = end - timedelta(days=days)
    fmt   = "%Y-%m-%d"
    return start.strftime(fmt), end.strftime(fmt)


# ── MLB Stats fetch ───────────────────────────────────────────────────────────

def _parse_hitting_splits(splits: list) -> list[dict]:
    rows = []
    for s in splits:
        p, st = s["player"], s["stat"]
        rows.append(dict(
            playerId    = p["id"],
            name        = p["fullName"],
            pa          = int(st.get("plateAppearances", 0)),
            runs        = int(st.get("runs", 0)),
            homeRuns    = int(st.get("homeRuns", 0)),
            rbi         = int(st.get("rbi", 0)),
            stolenBases = int(st.get("stolenBases", 0)),
            ops         = float(st.get("ops") or 0),
        ))
    return rows


def _parse_pitching_splits(splits: list) -> list[dict]:
    rows = []
    for s in splits:
        p, st = s["player"], s["stat"]
        ip_str = str(st.get("inningsPitched", "0"))
        parts  = ip_str.split(".")
        ip     = int(parts[0]) + (int(parts[1]) / 3 if len(parts) == 2 else 0)
        rows.append(dict(
            playerId   = p["id"],
            name       = p["fullName"],
            ip         = ip,
            wins       = int(st.get("wins", 0)),
            saves      = int(st.get("saves", 0)),
            strikeOuts = int(st.get("strikeOuts", 0)),
            era        = float(st.get("era") or 0),
            whip       = float(st.get("whip") or 0),
        ))
    return rows


def fetch_hitting_stats(season: int, days: int) -> pd.DataFrame:
    start, end = _date_range(days)
    print(f"⏬  MLB hitting stats — last {days} days ({start} → {end}) …")
    data   = statsapi.get('stats', {
        'stats': 'season', 'season': season,
        'group': 'hitting', 'sportId': 1, 'limit': 2000,
        'startDate': start, 'endDate': end,
    })
    splits = data["stats"][0]["splits"]
    df = pd.DataFrame(_parse_hitting_splits(splits))
    print(f"   → {len(df)} hitters fetched")
    return df


def fetch_pitching_stats(season: int, days: int) -> pd.DataFrame:
    start, end = _date_range(days)
    print(f"⏬  MLB pitching stats — last {days} days ({start} → {end}) …")
    data   = statsapi.get('stats', {
        'stats': 'season', 'season': season,
        'group': 'pitching', 'sportId': 1, 'limit': 2000,
        'startDate': start, 'endDate': end,
    })
    splits = data["stats"][0]["splits"]
    df = pd.DataFrame(_parse_pitching_splits(splits))
    print(f"   → {len(df)} pitchers fetched")
    return df


def add_zscores(df: pd.DataFrame, cats: list) -> pd.DataFrame:
    """Add per-category z-scores and z_total. Returns sorted copy."""
    df = df.copy()
    for cat in cats:
        mu, sigma = df[cat].mean(), df[cat].std(ddof=0)
        z = (df[cat] - mu) / sigma if sigma > 0 else 0.0
        df[f"z_{cat}"] = -z if cat in NEGATIVE_CATS else z
    df["z_total"] = df[[f"z_{c}" for c in cats]].sum(axis=1)
    df["rank"]    = df["z_total"].rank(ascending=False).astype(int)
    return df.sort_values("z_total", ascending=False).reset_index(drop=True)


# ── Yahoo free agent fetch ────────────────────────────────────────────────────

def _yahoo_python(repo_dir: str) -> str:
    bin_dir = "Scripts" if sys.platform == "win32" else "bin"
    exe     = "python.exe" if sys.platform == "win32" else "python3"
    path    = os.path.join(repo_dir, ".deps", bin_dir, exe)
    if not os.path.isfile(path):
        script = os.path.join(repo_dir, "yahoo-fantasy-baseball.py")
        sys.exit(
            f"❌  venv not found at: {path}\n"
            f"    Run:  python3 {script} --setup"
        )
    return path


def fetch_free_agents(
    repo_dir: str,
    league_id: str | None,
    status: str,
    count: int,
    position: str | None,
) -> list[dict]:
    script = os.path.join(repo_dir, "yahoo-fantasy-baseball.py")
    if not os.path.isfile(script):
        sys.exit(f"❌  yahoo-fantasy-baseball.py not found in: {repo_dir}")

    cmd = [
        _yahoo_python(repo_dir), script,
        "players", "--format", "json",
        "--status", status,
        "--count", str(count),
    ]
    if league_id:
        cmd += ["--league", league_id]
    if position:
        cmd += ["--position", position]

    print(f"⏬  Yahoo free agents (status={status}, count={count}) …")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("Yahoo CLI stderr:\n", result.stderr, file=sys.stderr)
        sys.exit(f"❌  Yahoo CLI exited with code {result.returncode}")

    raw = result.stdout
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("[")
        if start == -1:
            sys.exit(f"❌  Could not parse Yahoo CLI output:\n{raw[:500]}")
        data = json.loads(raw[start:])

    players = data if isinstance(data, list) else data.get("players", [])
    print(f"   → {len(players)} free agents returned from Yahoo")
    return players


# ── Name matching ─────────────────────────────────────────────────────────────

def _normalize(name: str) -> str:
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z ]", "", name.lower()).strip()


def match_players(fa_list: list[dict], zscore_df: pd.DataFrame) -> pd.DataFrame:
    lookup = zscore_df.copy()
    lookup["_norm"] = lookup["name"].map(_normalize)

    rows = []
    for fa in fa_list:
        yahoo_name = fa.get("name") or fa.get("full_name", "")
        norm  = _normalize(yahoo_name)
        match = lookup[lookup["_norm"] == norm]
        if match.empty:
            last  = norm.split()[-1] if norm else ""
            match = lookup[lookup["_norm"].str.endswith(f" {last}")]
        if not match.empty:
            row = match.iloc[0].drop("_norm").to_dict()
            row["yahoo_name"]   = yahoo_name
            row["pct_owned"]    = fa.get("percent_owned") or fa.get("pct_owned", 0)
            row["yahoo_team"]   = fa.get("team") or fa.get("editorial_team_abbr", "")
            row["positions"]    = fa.get("positions") or fa.get("eligible_positions", "")
            row["yahoo_status"] = fa.get("status", "")
            rows.append(row)

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def split_by_position(fa_players: list[dict]) -> tuple[list, list]:
    pitcher_pos = {"SP", "RP", "P"}
    hitters, pitchers = [], []
    for p in fa_players:
        pos_raw = p.get("positions") or p.get("eligible_positions", "")
        pos_set = set(pos_raw) if isinstance(pos_raw, list) \
                  else {x.strip() for x in str(pos_raw).split(",")}
        (pitchers if pos_set & pitcher_pos else hitters).append(p)
    return hitters, pitchers


# ── Column specs ──────────────────────────────────────────────────────────────

HITTER_COLS = [
    ("rank",          "Rank"),
    ("yahoo_name",    "Name"),
    ("yahoo_team",    "Team"),
    ("pct_owned",     "%Own"),
    ("pa",            "PA"),
    ("runs",          "R"),
    ("homeRuns",      "HR"),
    ("rbi",           "RBI"),
    ("stolenBases",   "SB"),
    ("ops",           "OPS"),
    ("z_runs",        "zR"),
    ("z_homeRuns",    "zHR"),
    ("z_rbi",         "zRBI"),
    ("z_stolenBases", "zSB"),
    ("z_ops",         "zOPS"),
    ("z_total",       "Z_Total"),
]

PITCHER_COLS = [
    ("rank",          "Rank"),
    ("yahoo_name",    "Name"),
    ("yahoo_team",    "Team"),
    ("pct_owned",     "%Own"),
    ("ip",            "IP"),
    ("wins",          "W"),
    ("saves",         "SV"),
    ("strikeOuts",    "K"),
    ("era",           "ERA"),
    ("whip",          "WHIP"),
    ("z_wins",        "zW"),
    ("z_saves",       "zSV"),
    ("z_strikeOuts",  "zK"),
    ("z_era",         "zERA"),
    ("z_whip",        "zWHIP"),
    ("z_total",       "Z_Total"),
]

HIT_ROUND = {"OPS": 3}
PIT_ROUND = {"ERA": 2, "WHIP": 3, "IP": 1}


# ── Shared table builder ──────────────────────────────────────────────────────

def _build_table(df: pd.DataFrame, cols: list[tuple], top: int,
                 rounding: dict) -> pd.DataFrame:
    src   = [s for s, _ in cols if s in df.columns]
    names = [d for s, d in cols if s in df.columns]
    out   = df[src].head(top).copy()
    out.columns = names
    for col, places in rounding.items():
        if col in out.columns:
            out[col] = out[col].round(places)
    for col in out.columns:
        if col.startswith("z") or col == "Z_Total":
            out[col] = out[col].round(2)
    return out


def _section(df: pd.DataFrame, cols: list[tuple], rounding: dict,
             top: int = 15) -> pd.DataFrame:
    """Return shaped table or empty DataFrame."""
    return _build_table(df, cols, top, rounding) if not df.empty else pd.DataFrame()


# ── CSV output ────────────────────────────────────────────────────────────────

def write_combined_csv(
    hit7:  pd.DataFrame, hit14: pd.DataFrame,
    pit14: pd.DataFrame, pit30: pd.DataFrame,
    path: str, top: int = 15,
):
    """
    Write four sections to a single CSV, each separated by 2 blank rows:
      Hitters  last 7 days
      Hitters  last 14 days
      Pitchers last 14 days
      Pitchers last 30 days
    Each section has its own header row.
    """
    sections = [
        ("HITTERS — Last 7 Days",   hit7,  HITTER_COLS,  HIT_ROUND),
        ("HITTERS — Last 14 Days",  hit14, HITTER_COLS,  HIT_ROUND),
        ("PITCHERS — Last 14 Days", pit14, PITCHER_COLS, PIT_ROUND),
        ("PITCHERS — Last 30 Days", pit30, PITCHER_COLS, PIT_ROUND),
    ]

    with open(path, "w", newline="", encoding="utf-8") as f:
        for i, (label, df, cols, rounding) in enumerate(sections):
            if i > 0:
                f.write("\n\n")
            f.write(f"{label}\n")
            tbl = _section(df, cols, rounding, top)
            if not tbl.empty:
                tbl.to_csv(f, index=False)
            else:
                f.write("No data\n")

    print(f"✅  {path} written")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Yahoo Fantasy Baseball Free Agent Z-Score Finder")
    ap.add_argument("--league",   default=os.environ.get("YAHOO_LEAGUE_ID"),
                    help="Yahoo league ID (or set YAHOO_LEAGUE_ID env var)")
    ap.add_argument("--season",   type=int,   default=2026)
    ap.add_argument("--min-pa",   type=int,   default=5,   dest="min_pa",
                    help="Min plate appearances for hitter z-score pool (default: 5)")
    ap.add_argument("--min-ip",   type=float, default=1,   dest="min_ip",
                    help="Min innings pitched for pitcher z-score pool (default: 1)")
    ap.add_argument("--position", default=None,
                    help="Filter free agents by position: OF, SP, RP, 3B …")
    ap.add_argument("--status",   default="A",
                    help="FA=free agents, W=waivers, A=all available (default: A)")
    ap.add_argument("--count",    type=int,   default=500,
                    help="Number of free agents to pull from Yahoo (default: 500)")
    ap.add_argument("--out",      default="free_agents.csv",
                    help="Output CSV path (default: free_agents.csv)")
    args = ap.parse_args()

    # ── 1. Fetch MLB stats for each window ────────────────────────────────────
    hit7_df  = fetch_hitting_stats(args.season, 7)
    hit7_df  = hit7_df[hit7_df["pa"] >= args.min_pa].reset_index(drop=True)
    hit7_df  = add_zscores(hit7_df, HITTER_CATS)

    hit14_df = fetch_hitting_stats(args.season, 14)
    hit14_df = hit14_df[hit14_df["pa"] >= args.min_pa].reset_index(drop=True)
    hit14_df = add_zscores(hit14_df, HITTER_CATS)

    pit14_df = fetch_pitching_stats(args.season, 14)
    pit14_df = pit14_df[pit14_df["ip"] >= args.min_ip].reset_index(drop=True)
    pit14_df = add_zscores(pit14_df, PITCHER_CATS)

    pit30_df = fetch_pitching_stats(args.season, 30)
    pit30_df = pit30_df[pit30_df["ip"] >= args.min_ip].reset_index(drop=True)
    pit30_df = add_zscores(pit30_df, PITCHER_CATS)

    # ── 2. Fetch Yahoo free agents ────────────────────────────────────────────
    fa_players = fetch_free_agents(
        os.path.abspath("yahoo-fantasy-baseball"),
        args.league, args.status, args.count, args.position
    )

    fa_hitters, fa_pitchers = split_by_position(fa_players)
    print(f"   → {len(fa_hitters)} hitters / {len(fa_pitchers)} pitchers among free agents")

    # ── 3. Match names into each window ───────────────────────────────────────
    def matched_sorted(fa_list, zscore_df):
        df = match_players(fa_list, zscore_df)
        if not df.empty:
            df = df.sort_values("z_total", ascending=False).reset_index(drop=True)
        return df

    hit7_fa  = matched_sorted(fa_hitters,  hit7_df)
    hit14_fa = matched_sorted(fa_hitters,  hit14_df)
    pit14_fa = matched_sorted(fa_pitchers, pit14_df)
    pit30_fa = matched_sorted(fa_pitchers, pit30_df)

    # ── 4. Console summary ────────────────────────────────────────────────────
    for label, df, cols, rounding in [
        ("HITTERS — Last 7 Days",   hit7_fa,  HITTER_COLS,  HIT_ROUND),
        ("HITTERS — Last 14 Days",  hit14_fa, HITTER_COLS,  HIT_ROUND),
        ("PITCHERS — Last 14 Days", pit14_fa, PITCHER_COLS, PIT_ROUND),
        ("PITCHERS — Last 30 Days", pit30_fa, PITCHER_COLS, PIT_ROUND),
    ]:
        print(f"\n{'═'*72}")
        print(f"  {label}")
        print(f"{'═'*72}")
        if df.empty:
            print("  No matches found — try expanding --count or lowering --min-pa/--min-ip")
        else:
            print(_build_table(df, cols, 15, rounding).to_string(index=False))

    # ── 5. Write CSV ──────────────────────────────────────────────────────────
    print()
    write_combined_csv(hit7_fa, hit14_fa, pit14_fa, pit30_fa, args.out, top=15)


if __name__ == "__main__":
    main()