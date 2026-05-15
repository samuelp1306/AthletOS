"""Acute:Chronic Workload Ratio (ACWR).

Berechnet pro Tag:
    acute_load   = `acute_window`-Tage-EWMA der Tagesbelastung (strain)
    chronic_load = `chronic_window`-Tage-EWMA der Tagesbelastung
    acwr         = acute_load / chronic_load
    zone         = optimal | spike | detraining (Schwellen aus config.yaml)

V0.1: Tagesbelastung = nur Whoop `strain`. Sobald `training_log` existiert,
wird hier zusaetzlich `(rpe * duration_min / 60)` addiert (siehe CLAUDE.md).

EWMA wird mit `adjust=False` berechnet (kausale Form y_t = (1-a)*y_{t-1} + a*x_t),
weil ACWR per Definition nur Vergangenheit kennen darf.

Fehlende Tage im Datumsraum (Strap-Off etc.) werden mit strain=0 aufgefuellt,
sodass die EWMA nicht ueber Luecken hinwegrutscht.

Die ersten `chronic_window` Tage werden als Warmup markiert: acwr=NaN, zone=None.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def load_config(path: Path = CONFIG_PATH) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def classify(acwr: float, spike: float, detraining: float) -> str | None:
    """ACWR-Wert -> Zone."""
    if acwr is None or pd.isna(acwr):
        return None
    if acwr > spike:
        return "spike"
    if acwr < detraining:
        return "detraining"
    return "optimal"


def compute(db_path: Path, config: dict) -> pd.DataFrame:
    """Liest whoop_daily und berechnet ACWR pro Tag.

    Returns:
        DataFrame mit Spalten: date (str YYYY-MM-DD), strain, acute_load,
        chronic_load, acwr, zone.
    """
    cfg = config["acwr"]
    acute_w = int(cfg["acute_window"])
    chronic_w = int(cfg["chronic_window"])
    spike = float(cfg["spike_threshold"])
    detraining = float(cfg["detraining_threshold"])

    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(
            "SELECT date, strain FROM whoop_daily ORDER BY date",
            conn,
            parse_dates=["date"],
        )

    if df.empty:
        return pd.DataFrame(
            columns=["date", "strain", "acute_load", "chronic_load", "acwr", "zone"]
        )

    # Luecken in der Datumsreihe schliessen, sonst rutscht die EWMA ueber Luecken.
    df = df.set_index("date")
    full_idx = pd.date_range(df.index.min(), df.index.max(), freq="D")
    df = df.reindex(full_idx).rename_axis("date").reset_index()
    df["strain"] = pd.to_numeric(df["strain"], errors="coerce").fillna(0.0)

    df["acute_load"] = df["strain"].ewm(span=acute_w, adjust=False).mean()
    df["chronic_load"] = df["strain"].ewm(span=chronic_w, adjust=False).mean()
    df["acwr"] = df["acute_load"] / df["chronic_load"].where(df["chronic_load"] != 0)

    # Warmup: ohne chronic_window Tage Historie ist der Wert nicht aussagekraeftig.
    warmup = df.index < chronic_w
    df.loc[warmup, "acwr"] = pd.NA

    df["zone"] = df["acwr"].apply(lambda x: classify(x, spike, detraining))
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")

    return df[["date", "strain", "acute_load", "chronic_load", "acwr", "zone"]]


def latest(db_path: Path, config: dict) -> dict[str, Any]:
    """Konvenienz: ACWR-Wert + Zone fuer den letzten Tag in der DB.

    Passt zum DailyData-Protocol in engine/models/protocol.py (Felder acwr, acwr_zone).
    """
    df = compute(db_path, config)
    if df.empty:
        return {"date": None, "acwr": None, "acwr_zone": None}
    row = df.iloc[-1]
    return {
        "date": row["date"],
        "acwr": None if pd.isna(row["acwr"]) else float(row["acwr"]),
        "acwr_zone": row["zone"],
    }


if __name__ == "__main__":
    cfg = load_config()
    db_path = PROJECT_ROOT / cfg["paths"]["database"]
    df = compute(db_path, cfg)

    print(f"Datenfenster: {df['date'].iloc[0]} -> {df['date'].iloc[-1]} ({len(df)} Tage)")
    print(
        f"Thresholds: spike > {cfg['acwr']['spike_threshold']}, "
        f"detraining < {cfg['acwr']['detraining_threshold']}"
    )
    print("\nACWR letzte 7 Tage:")
    tail = df.tail(7).copy()
    tail["strain"] = tail["strain"].round(2)
    tail["acute_load"] = tail["acute_load"].round(2)
    tail["chronic_load"] = tail["chronic_load"].round(2)
    tail["acwr"] = tail["acwr"].astype(float).round(3)
    print(tail.to_string(index=False))
