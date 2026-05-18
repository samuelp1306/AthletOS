"""Orchestrator fuer Layer 1.

Bringt fuer einen gegebenen Tag alle Engine-Module zusammen und liefert das
strukturierte Dict, das Layer 2 (Coach / Claude) als Input erhaelt.

Quellen:
    whoop_daily        -- Whoop-Werte (Pflicht; ohne diese Zeile bricht der Lauf ab)
    yazio_daily        -- Ernaehrung; fehlend -> deficit_detected=False, weiter
    daily_checkin      -- Subjektives Check-in; fehlend -> checkin=None, weiter

Aufrufe:
    acwr.compute()        ueber den gesamten Verlauf, dann Zeile fuer date picken
    nutrition.compute()   pure function, dict in/out
    readiness.compute()   pure function, dict in/out

Output (exakt die Felder aus der Aufgabe):
    date, whoop_recovery, adjusted_readiness, corrections_applied,
    acwr, acwr_zone, deficit_detected, protein_ok, checkin, checkin_reason
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from engine.models import acwr, nutrition, readiness

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def load_config(path: Path = CONFIG_PATH) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    )
    return cur.fetchone() is not None


def _fetch_row(conn: sqlite3.Connection, table: str, date: str) -> dict | None:
    """Eine Zeile aus `table` mit date=date. None wenn Tabelle fehlt oder Zeile leer."""
    if not _table_exists(conn, table):
        return None
    conn.row_factory = sqlite3.Row
    cur = conn.execute(f"SELECT * FROM {table} WHERE date = ?", (date,))
    row = cur.fetchone()
    return dict(row) if row else None


def calculate(date: str, config: dict | None = None) -> dict[str, Any]:
    """Berechnet den vollstaendigen Tagesoutput fuer Layer 2.

    Args:
        date:   Datum als YYYY-MM-DD.
        config: optional vorab geladene config.yaml.
    """
    cfg = config or load_config()
    db_path = PROJECT_ROOT / cfg["paths"]["database"]

    with sqlite3.connect(db_path) as conn:
        whoop = _fetch_row(conn, "whoop_daily", date)
        yazio = _fetch_row(conn, "yazio_daily", date)
        checkin = _fetch_row(conn, "daily_checkin", date)

    if whoop is None:
        raise ValueError(
            f"No whoop_daily entry for {date}. "
            "Cannot compute readiness without Whoop recovery."
        )

    # --- Nutrition (Yazio fehlt -> deficit_detected=False, protein_ok=False) ---
    weight_kg = float(cfg["athlete"]["weight_kg"])
    protein_target_g = float(cfg["nutrition"]["protein_target_per_kg"]) * weight_kg
    nutrition_day = {
        "calories": yazio.get("calories") if yazio else None,
        "protein": yazio.get("protein") if yazio else None,
        "carbs": yazio.get("carbs") if yazio else None,
        "tdee": cfg["nutrition"]["tdee"],
        "protein_target_g": protein_target_g,
    }
    nut = nutrition.compute(nutrition_day, cfg)

    # --- Readiness ---
    readiness_day = {
        "recovery_score": whoop.get("recovery_score"),
        "deficit_detected": nut["deficit_detected"],
        "checkin": checkin.get("readiness") if checkin else None,
        "sleep_efficiency": whoop.get("sleep_efficiency"),
        "sleep_hours": whoop.get("sleep_hours"),
    }
    rd = readiness.compute(readiness_day, cfg)

    # --- ACWR (ueber den Verlauf, dann Zeile fuer date picken) ---
    acwr_df = acwr.compute(db_path, cfg)
    acwr_row = acwr_df[acwr_df["date"] == date]
    if acwr_row.empty:
        acwr_value: float | None = None
        acwr_zone: str | None = None
    else:
        v = acwr_row.iloc[0]["acwr"]
        z = acwr_row.iloc[0]["zone"]
        acwr_value = None if pd.isna(v) else float(v)
        acwr_zone = None if z is None or (isinstance(z, float) and pd.isna(z)) else str(z)

    return {
        "date": date,
        "whoop_recovery": whoop.get("recovery_score"),
        "adjusted_readiness": rd["adjusted_readiness"],
        "corrections_applied": rd["corrections_applied"],
        "acwr": acwr_value,
        "acwr_zone": acwr_zone,
        "deficit_detected": nut["deficit_detected"],
        "protein_ok": nut["protein_ok"],
        "checkin": checkin.get("readiness") if checkin else None,
        "checkin_reason": checkin.get("reason") if checkin else None,
    }


if __name__ == "__main__":
    import json

    cfg = load_config()
    target_date = "2026-05-04"
    try:
        out = calculate(target_date, cfg)
    except ValueError as e:
        print(f"Fehler: {e}")
        raise SystemExit(1)

    print(f"Layer-1-Output fuer {target_date}:")
    print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
