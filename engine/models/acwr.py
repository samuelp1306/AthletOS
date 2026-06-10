"""
Acute:Chronic Workload Ratio (ACWR) — v2.0

Improvements over v1:
1. Combined load: Whoop strain + training_log (RPE × duration / 60)
2. Uncoupled ACWR option (Lolli et al. 2019) — chronic excludes acute window
3. Correct exponential decay: alpha = 1 - exp(-1/window) per Williams et al.
4. Both EWMA and Simple Rolling Average (SRA) for comparison
5. Position-specific spike thresholds
6. Week-over-week load change tracking (>10% = flag per Gabbett)
7. Training monotony and strain calculations (Foster 1998)

Sources:
- Gabbett TJ (2016). The training-injury prevention paradox. BJSM.
- Williams S et al. (2017). EWMA better detects load changes than SRA. BJSM.
- Lolli L et al. (2019). Mathematical coupling in ACWR. IJSPP.
- Foster C (1998). Monitoring training in athletes. MSSE.
- Position thresholds: Position_Specific_Demands.docx
"""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def load_config(path: Path = CONFIG_PATH) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ============================================================
# POSITION-SPECIFIC THRESHOLDS
# ============================================================

# Higher-volume positions tolerate slightly higher ACWR before injury risk
# Source: Position_Specific_Demands.docx + Gabbett 2016
POSITION_THRESHOLDS = {
    "GK":  {"spike": 1.25, "detraining": 0.75},  # low baseline load — spikes hit harder
    "CB":  {"spike": 1.30, "detraining": 0.80},
    "FB":  {"spike": 1.35, "detraining": 0.80},  # high chronic load — slightly more tolerant
    "CM":  {"spike": 1.35, "detraining": 0.80},  # highest total distance — most load-adapted
    "AM":  {"spike": 1.30, "detraining": 0.80},
    "W":   {"spike": 1.30, "detraining": 0.80},  # high sprint load — standard threshold
    "ST":  {"spike": 1.30, "detraining": 0.80},
}

DEFAULT_THRESHOLDS = {"spike": 1.30, "detraining": 0.80}


def get_thresholds(config: dict, position: Optional[str] = None) -> dict:
    """Get spike/detraining thresholds, position-aware if available."""
    cfg = config["acwr"]

    # Use position-specific if available and position is provided
    if position and position in POSITION_THRESHOLDS:
        return POSITION_THRESHOLDS[position]

    # Fall back to config.yaml values
    return {
        "spike": float(cfg["spike_threshold"]),
        "detraining": float(cfg["detraining_threshold"]),
    }


# ============================================================
# LOAD CALCULATION
# ============================================================

def _get_combined_load(db_path: Path) -> pd.DataFrame:
    """
    Combine Whoop strain + training log into a single daily load value.

    Formula: daily_load = whoop_strain + sum(RPE × duration_min / 60) per day
    Source: CLAUDE.md — training.load_formula

    If training_log doesn't exist or has no data, falls back to Whoop-only.
    """
    with sqlite3.connect(db_path) as conn:
        # Whoop strain
        whoop = pd.read_sql_query(
            "SELECT date, strain FROM whoop_daily ORDER BY date",
            conn,
            parse_dates=["date"],
        )

        # Training log (may not exist yet)
        try:
            training = pd.read_sql_query(
                """SELECT date, rpe, duration_min
                   FROM training_log
                   WHERE rpe IS NOT NULL AND duration_min IS NOT NULL""",
                conn,
                parse_dates=["date"],
            )
            # Calculate session load and aggregate per day
            training["session_load"] = training["rpe"] * training["duration_min"] / 60.0
            training_daily = (
                training.groupby("date")["session_load"]
                .sum()
                .reset_index()
                .rename(columns={"session_load": "training_load"})
            )
        except Exception:
            # training_log table doesn't exist yet
            training_daily = pd.DataFrame(columns=["date", "training_load"])

    if whoop.empty:
        return pd.DataFrame(columns=["date", "load"])

    whoop = whoop.set_index("date")
    whoop["strain"] = pd.to_numeric(whoop["strain"], errors="coerce").fillna(0.0)

    # Merge training load if available
    if not training_daily.empty:
        training_daily = training_daily.set_index("date")
        whoop = whoop.join(training_daily, how="left")
        whoop["training_load"] = whoop["training_load"].fillna(0.0)
        whoop["load"] = whoop["strain"] + whoop["training_load"]
    else:
        whoop["load"] = whoop["strain"]

    # Fill date gaps with 0 (strap-off days, missed training)
    full_idx = pd.date_range(whoop.index.min(), whoop.index.max(), freq="D")
    whoop = whoop.reindex(full_idx).rename_axis("date")
    whoop["load"] = whoop["load"].fillna(0.0)

    return whoop[["load"]].reset_index()


# ============================================================
# EWMA CALCULATION
# ============================================================

def _ewma_williams(series: pd.Series, window: int) -> pd.Series:
    """
    EWMA with correct decay constant per Williams et al. (2017).

    Alpha = 1 - exp(-1/window)

    This differs from pandas default (alpha = 2/(span+1)):
    - Window 7:  Williams alpha = 0.1331 vs pandas alpha = 0.2500
    - Window 28: Williams alpha = 0.0351 vs pandas alpha = 0.0690

    Williams decay is more conservative and better matches the
    physiological time constants of fitness and fatigue adaptation.
    """
    alpha = 1 - math.exp(-1 / window)
    return series.ewm(alpha=alpha, adjust=False).mean()


def _sra(series: pd.Series, window: int) -> pd.Series:
    """Simple Rolling Average — for comparison with EWMA."""
    return series.rolling(window=window, min_periods=1).mean()


# ============================================================
# ACWR COMPUTATION
# ============================================================

def compute(
    db_path: Path,
    config: dict,
    method: str = "ewma",
    coupled: bool = False,
    position: Optional[str] = None,
) -> pd.DataFrame:
    """
    Compute ACWR for all days in the database.

    Parameters:
        db_path: Path to SQLite database
        config: Parsed config.yaml
        method: "ewma" (Williams et al.) or "sra" (simple rolling average)
        coupled: If False (default), use uncoupled ACWR (Lolli et al. 2019)
                 Chronic window excludes acute window to avoid mathematical coupling
        position: Athlete position for position-specific thresholds

    Returns:
        DataFrame with columns: date, load, acute_load, chronic_load, acwr, zone,
                                acwr_sra (if method=ewma, for comparison),
                                weekly_change_pct, monotony, strain_index
    """
    cfg = config["acwr"]
    acute_w = int(cfg["acute_window"])
    chronic_w = int(cfg["chronic_window"])
    thresholds = get_thresholds(config, position)
    spike = thresholds["spike"]
    detraining = thresholds["detraining"]

    # Get combined load data
    df = _get_combined_load(db_path)

    if df.empty:
        return pd.DataFrame(columns=[
            "date", "load", "acute_load", "chronic_load", "acwr", "zone",
            "weekly_change_pct", "monotony", "strain_index"
        ])

    df = df.set_index("date")

    # --- Acute load ---
    if method == "ewma":
        df["acute_load"] = _ewma_williams(df["load"], acute_w)
    else:
        df["acute_load"] = _sra(df["load"], acute_w)

    # --- Chronic load ---
    if coupled:
        # Coupled: chronic includes acute window (traditional, simpler)
        if method == "ewma":
            df["chronic_load"] = _ewma_williams(df["load"], chronic_w)
        else:
            df["chronic_load"] = _sra(df["load"], chronic_w)
    else:
        # Uncoupled (Lolli et al. 2019): chronic = days (acute_w+1) to (chronic_w)
        # This avoids the mathematical coupling artifact
        shifted = df["load"].shift(acute_w)  # shift by acute window
        if method == "ewma":
            df["chronic_load"] = _ewma_williams(shifted.fillna(0), chronic_w - acute_w)
        else:
            df["chronic_load"] = shifted.rolling(
                window=chronic_w - acute_w, min_periods=1
            ).mean()

    # --- ACWR ---
    df["acwr"] = df["acute_load"] / df["chronic_load"].where(df["chronic_load"] > 0.001)

    # Warmup period: not enough data for reliable chronic load
    warmup_days = chronic_w
    df.iloc[:warmup_days, df.columns.get_loc("acwr")] = pd.NA

    # --- Zone classification ---
    df["zone"] = df["acwr"].apply(
        lambda x: _classify(x, spike, detraining)
    )

    # --- Comparison: always compute SRA alongside EWMA ---
    if method == "ewma":
        sra_acute = _sra(df["load"], acute_w)
        sra_chronic = _sra(df["load"], chronic_w)
        df["acwr_sra"] = sra_acute / sra_chronic.where(sra_chronic > 0.001)
        df.iloc[:warmup_days, df.columns.get_loc("acwr_sra")] = pd.NA

    # --- Week-over-week load change ---
    # Source: Gabbett 2016 — >10% weekly increase = elevated injury risk
    df["weekly_load"] = df["load"].rolling(window=7, min_periods=1).sum()
    df["prev_weekly_load"] = df["weekly_load"].shift(7)
    df["weekly_change_pct"] = (
        (df["weekly_load"] - df["prev_weekly_load"])
        / df["prev_weekly_load"].where(df["prev_weekly_load"] > 0)
        * 100
    )

    # --- Training Monotony (Foster 1998) ---
    # Monotony = mean daily load / SD of daily load over 7 days
    # High monotony (>2.0) = repetitive loading pattern = injury risk
    rolling_mean = df["load"].rolling(window=7, min_periods=7).mean()
    rolling_std = df["load"].rolling(window=7, min_periods=7).std()
    df["monotony"] = rolling_mean / rolling_std.where(rolling_std > 0.001)

    # --- Training Strain (Foster 1998) ---
    # Strain = weekly_load × monotony
    # High strain (>monotony × load) indicates both high volume AND repetitive pattern
    df["strain_index"] = df["weekly_load"] * df["monotony"]

    # Format output
    df = df.reset_index()
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")

    output_cols = [
        "date", "load", "acute_load", "chronic_load", "acwr", "zone",
        "weekly_change_pct", "monotony", "strain_index"
    ]
    if "acwr_sra" in df.columns:
        output_cols.insert(6, "acwr_sra")

    return df[output_cols]


def _classify(acwr: float, spike: float, detraining: float) -> Optional[str]:
    """ACWR value -> zone."""
    if acwr is None or pd.isna(acwr):
        return None
    if acwr > spike:
        return "spike"
    if acwr < detraining:
        return "detraining"
    return "optimal"


# ============================================================
# CONVENIENCE FUNCTIONS
# ============================================================

def latest(
    db_path: Path,
    config: dict,
    position: Optional[str] = None
) -> dict[str, Any]:
    """ACWR value + zone + extras for the most recent day."""
    df = compute(db_path, config, position=position)

    if df.empty:
        return {
            "date": None, "acwr": None, "acwr_zone": None,
            "weekly_change_pct": None, "monotony": None,
        }

    row = df.iloc[-1]
    return {
        "date": row["date"],
        "acwr": None if pd.isna(row["acwr"]) else round(float(row["acwr"]), 2),
        "acwr_zone": row["zone"],
        "acwr_sra": None if "acwr_sra" not in row or pd.isna(row.get("acwr_sra"))
                    else round(float(row["acwr_sra"]), 2),
        "weekly_change_pct": None if pd.isna(row["weekly_change_pct"])
                             else round(float(row["weekly_change_pct"]), 1),
        "monotony": None if pd.isna(row["monotony"])
                    else round(float(row["monotony"]), 2),
    }


def weekly_summary(db_path: Path, config: dict) -> dict:
    """Summary of the last 7 days for the weekly report."""
    df = compute(db_path, config)

    if df.empty or len(df) < 7:
        return {"days": 0, "avg_load": 0, "total_load": 0}

    last_7 = df.tail(7)
    return {
        "days": 7,
        "avg_load": round(float(last_7["load"].mean()), 1),
        "total_load": round(float(last_7["load"].sum()), 1),
        "avg_acwr": round(float(last_7["acwr"].dropna().mean()), 2) if last_7["acwr"].notna().any() else None,
        "monotony": round(float(last_7["monotony"].iloc[-1]), 2) if pd.notna(last_7["monotony"].iloc[-1]) else None,
        "spike_days": int((last_7["zone"] == "spike").sum()),
        "detraining_days": int((last_7["zone"] == "detraining").sum()),
        "max_weekly_change": round(float(last_7["weekly_change_pct"].dropna().max()), 1) if last_7["weekly_change_pct"].notna().any() else None,
    }


# ============================================================
# FLAGS
# ============================================================

def generate_acwr_flags(
    acwr_data: dict,
    config: dict,
    position: Optional[str] = None
) -> list[str]:
    """
    Generate warning flags based on ACWR data.
    Called by protocol.py or calculate.py.
    """
    flags = []
    thresholds = get_thresholds(config, position)

    acwr = acwr_data.get("acwr")
    zone = acwr_data.get("acwr_zone")
    weekly_change = acwr_data.get("weekly_change_pct")
    monotony = acwr_data.get("monotony")

    if acwr is None:
        return flags

    # ACWR zone flags
    if zone == "spike":
        if acwr > 1.5:
            flags.append(
                f"ACWR DANGER: {acwr:.2f} — well above spike threshold "
                f"({thresholds['spike']:.2f}). Very high injury risk. "
                f"Reduce load immediately."
            )
        else:
            flags.append(
                f"ACWR ELEVATED: {acwr:.2f} — above spike threshold "
                f"({thresholds['spike']:.2f}). Monitor closely, reduce volume."
            )
    elif zone == "detraining":
        flags.append(
            f"ACWR LOW: {acwr:.2f} — below detraining threshold "
            f"({thresholds['detraining']:.2f}). Gradually increase load "
            f"to avoid deconditioning. Max +10% per week."
        )

    # Week-over-week change (Gabbett 2016)
    if weekly_change is not None:
        if weekly_change > 15:
            flags.append(
                f"LOAD SPIKE: Weekly load increased {weekly_change:.0f}% vs last week. "
                f"Maximum safe increase is 10-15%. Injury risk significantly elevated."
            )
        elif weekly_change > 10:
            flags.append(
                f"LOAD INCREASE: Weekly load up {weekly_change:.0f}% vs last week. "
                f"Approaching the 10-15% safe limit. Be cautious adding more."
            )
        elif weekly_change < -30:
            flags.append(
                f"SHARP LOAD DROP: Weekly load decreased {abs(weekly_change):.0f}%. "
                f"If returning to full training, ramp up gradually (max +10%/week)."
            )

    # Monotony (Foster 1998)
    if monotony is not None and monotony > 2.0:
        flags.append(
            f"HIGH MONOTONY: {monotony:.1f} — training pattern is too repetitive. "
            f"Vary session types and intensities to reduce overuse risk. "
            f"Source: Foster 1998 — monotony >2.0 correlates with illness/injury."
        )

    return flags


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    cfg = load_config()
    db = PROJECT_ROOT / "db" / "performance.db"

    print("=== ACWR v2.0 ===\n")

    # Latest values
    result = latest(db, cfg, position="FB")
    print(f"Date:           {result['date']}")
    print(f"ACWR (EWMA):    {result['acwr']}")
    print(f"ACWR (SRA):     {result.get('acwr_sra')}")
    print(f"Zone:           {result['acwr_zone']}")
    print(f"Weekly change:  {result['weekly_change_pct']}%")
    print(f"Monotony:       {result['monotony']}")

    # Weekly summary
    print(f"\n=== WEEKLY SUMMARY ===")
    ws = weekly_summary(db, cfg)
    for k, v in ws.items():
        print(f"  {k}: {v}")

    # Flags
    print(f"\n=== FLAGS ===")
    flags = generate_acwr_flags(result, cfg, position="FB")
    if flags:
        for f in flags:
            print(f"  ⚠ {f}")
    else:
        print("  ✓ No flags — load management looks good.")

    # Full table (last 14 days)
    print(f"\n=== LAST 14 DAYS ===")
    df = compute(db, cfg, position="FB")
    if not df.empty:
        print(df.tail(14).to_string(index=False))
