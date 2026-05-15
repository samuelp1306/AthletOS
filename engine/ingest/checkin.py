"""Daily Check-in JSON -> SQLite ingest.

Liest data/raw/checkin.json und schreibt jede Check-in-Zeile in `daily_checkin`.

Erwartetes Format -- entweder ein einzelnes Objekt:
    {"date": "2026-05-15", "readiness": "limited", "reason": "fatigue"}

oder eine Liste solcher Objekte (typischer Fall, weil mehrere Tage in einer Datei):
    [
        {"date": "2026-05-15", "readiness": "limited", "reason": "fatigue"},
        {"date": "2026-05-16", "readiness": "yes",     "reason": "none"}
    ]

Felder:
    date       (Pflicht, YYYY-MM-DD)
    readiness  (Pflicht: 'yes' | 'limited' | 'no')
    reason     (optional: 'soreness' | 'fatigue' | 'mental' | 'deficit' | 'none' | None)

Idempotent: ON CONFLICT(date) DO UPDATE -- erneutes Einspielen ueberschreibt einfach.
Fehlt die JSON-Datei, gibt das Modul 0 zurueck und meldet das (kein Crash).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"

VALID_READINESS = {"yes", "limited", "no"}
VALID_REASONS = {"soreness", "fatigue", "mental", "deficit", "none"}

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS daily_checkin (
    date TEXT PRIMARY KEY,
    readiness TEXT NOT NULL,
    reason TEXT
)
"""


def load_config(path: Path = CONFIG_PATH) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _normalize(raw: Any) -> list[dict]:
    """Akzeptiert dict ODER list[dict] -- normalisiert auf list[dict]."""
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return [r for r in raw if isinstance(r, dict)]
    raise ValueError(f"checkin.json muss dict oder list sein, ist {type(raw).__name__}")


def _validate(entry: dict) -> tuple[str, str, str | None] | None:
    """Validiert eine Entry-Zeile. Returns (date, readiness, reason) oder None bei Skip."""
    date = entry.get("date")
    readiness = entry.get("readiness")
    reason = entry.get("reason")

    if not date or not isinstance(date, str):
        print(f"  skip: 'date' fehlt oder kein String -> {entry}")
        return None
    if readiness not in VALID_READINESS:
        print(f"  skip: readiness '{readiness}' nicht in {VALID_READINESS} -> {entry}")
        return None

    if reason in ("", None):
        reason = None
    elif reason not in VALID_REASONS:
        # Wert behalten, aber warnen -- haerter blockieren waere uebergriffig.
        print(f"  warn: reason '{reason}' nicht in {VALID_REASONS}, wird trotzdem gespeichert")

    return date, readiness, reason


def upsert(rows: list[tuple[str, str, str | None]], db_path: Path) -> int:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(CREATE_TABLE_SQL)
        conn.executemany(
            """
            INSERT INTO daily_checkin (date, readiness, reason)
            VALUES (?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                readiness = excluded.readiness,
                reason    = excluded.reason
            """,
            rows,
        )
        conn.commit()
    return len(rows)


def ingest(config: dict | None = None) -> int:
    cfg = config or load_config()
    json_path = PROJECT_ROOT / cfg["paths"]["raw_data"] / "checkin.json"
    db_path = PROJECT_ROOT / cfg["paths"]["database"]

    if not json_path.exists():
        print(f"  hinweis: {json_path} existiert nicht -- 0 Check-ins eingespielt")
        return 0

    with json_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    entries = _normalize(raw)
    rows: list[tuple[str, str, str | None]] = []
    for entry in entries:
        validated = _validate(entry)
        if validated:
            rows.append(validated)

    if not rows:
        return 0
    return upsert(rows, db_path)


if __name__ == "__main__":
    cfg = load_config()
    db_path = PROJECT_ROOT / cfg["paths"]["database"]

    n = ingest(cfg)
    print(f"Eingespielt: {n} Check-ins -> {db_path}")

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        # Tabelle anlegen, falls noch nie ein Import lief (sonst wirft das SELECT).
        conn.execute(CREATE_TABLE_SQL)
        cur = conn.execute("SELECT * FROM daily_checkin ORDER BY date DESC LIMIT 3")
        rows = cur.fetchall()

    print("\nLetzte 3 Zeilen aus daily_checkin:")
    for r in rows:
        print(dict(r))
