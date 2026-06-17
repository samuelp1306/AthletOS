"""Validierungs-Layer: schreibt die drei unabhaengigen Tagessignale in `daily_validation`.

Diese Tabelle ist die Datengrundlage fuer engine/validate.py (prospektive Validierung:
schlaegt der Adjusted Score den rohen Recovery-Wert gegen das blinde Bauchgefuehl?).

Drei Signale, drei NARROW upserts -- jeder fasst nur seine eigenen Spalten an, damit ein
spaeterer Aufruf die anderen Signale nie ueberschreibt:

    upsert_perceived  -> perceived_readiness, readiness_ts   (blindes 1-10, VOR allem)
    upsert_hooper     -> hooper_* (5 Items), hooper_total, wellness_score
    upsert_scores     -> raw_recovery, adjusted_readiness     (am Ende, aus Layer 1)

WICHTIG -- Vertrag mit engine/validate.py:
    validate_scores() liest `SELECT date, perceived_readiness, raw_recovery,
    adjusted_readiness FROM daily_validation`. Diese vier Spaltennamen sind FIX.

Gespiegelt von engine/ingest/checkin.py: CREATE TABLE IF NOT EXISTS, additive
PRAGMA-Migration, ON CONFLICT(date) DO UPDATE, kein ORM. Idempotent.

Trennung der Layer (siehe CLAUDE.md): perceived_readiness, die Hooper-Werte und
wellness_score sind ein DRITTES, unabhaengiges Signal. Sie fliessen NIE in
calculate()/compute() ein und beeinflussen adjusted_readiness nicht.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS daily_validation (
    date TEXT PRIMARY KEY,
    perceived_readiness INTEGER,
    readiness_ts TIMESTAMP,
    raw_recovery REAL,
    adjusted_readiness INTEGER,
    hooper_sleep INTEGER,
    hooper_fatigue INTEGER,
    hooper_soreness INTEGER,
    hooper_stress INTEGER,
    hooper_mood INTEGER,
    hooper_total INTEGER,
    wellness_score INTEGER
)
"""

# Alle Nicht-PK-Spalten -- Basis fuer die additive Migration.
_COLUMNS: dict[str, str] = {
    "perceived_readiness": "INTEGER",
    "readiness_ts": "TIMESTAMP",
    "raw_recovery": "REAL",
    "adjusted_readiness": "INTEGER",
    "hooper_sleep": "INTEGER",
    "hooper_fatigue": "INTEGER",
    "hooper_soreness": "INTEGER",
    "hooper_stress": "INTEGER",
    "hooper_mood": "INTEGER",
    "hooper_total": "INTEGER",
    "wellness_score": "INTEGER",
}


def _ensure_table(conn: sqlite3.Connection) -> None:
    """Additive Migration -- mirrors migrate_add_rpe_column in checkin.py.

    CREATE IF NOT EXISTS deckt frische DBs ab. Fuer eine evtl. aeltere, partielle
    daily_validation werden fehlende Spalten per ALTER ergaenzt. Idempotent."""
    conn.execute(CREATE_TABLE_SQL)
    existing = {row[1] for row in conn.execute("PRAGMA table_info(daily_validation)")}
    for col, coltype in _COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE daily_validation ADD COLUMN {col} {coltype}")
    conn.commit()


def upsert_perceived(
    date: str,
    perceived_readiness: int,
    readiness_ts: str,
    db_path: Path,
) -> None:
    """Schreibt NUR das blinde 1-10-Bauchgefuehl + Zeitstempel fuer `date`.

    Narrow upsert: ruehrt keine andere Spalte an. Wird ZUERST aufgerufen (vor Hooper,
    vor jeder Score-Anzeige), damit das Bauchgefuehl nicht ankern kann."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        _ensure_table(conn)
        conn.execute(
            """
            INSERT INTO daily_validation (date, perceived_readiness, readiness_ts)
            VALUES (?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                perceived_readiness = excluded.perceived_readiness,
                readiness_ts        = excluded.readiness_ts
            """,
            (date, perceived_readiness, readiness_ts),
        )
        conn.commit()


def upsert_hooper(
    date: str,
    hooper_sleep: int,
    hooper_fatigue: int,
    hooper_soreness: int,
    hooper_stress: int,
    hooper_mood: int,
    hooper_total: int,
    wellness_score: int,
    db_path: Path,
) -> None:
    """Schreibt NUR die fuenf Hooper-Items + total + wellness_score fuer `date`.

    Narrow upsert: ruehrt perceived_readiness/raw_recovery/adjusted_readiness nicht an.
    wellness_score ist der dem Spieler angezeigte 'echte' Score -- reines Log/Display,
    fliesst nie in calculate()/compute() ein."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        _ensure_table(conn)
        conn.execute(
            """
            INSERT INTO daily_validation (
                date, hooper_sleep, hooper_fatigue, hooper_soreness,
                hooper_stress, hooper_mood, hooper_total, wellness_score
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                hooper_sleep    = excluded.hooper_sleep,
                hooper_fatigue  = excluded.hooper_fatigue,
                hooper_soreness = excluded.hooper_soreness,
                hooper_stress   = excluded.hooper_stress,
                hooper_mood     = excluded.hooper_mood,
                hooper_total    = excluded.hooper_total,
                wellness_score  = excluded.wellness_score
            """,
            (
                date,
                hooper_sleep,
                hooper_fatigue,
                hooper_soreness,
                hooper_stress,
                hooper_mood,
                hooper_total,
                wellness_score,
            ),
        )
        conn.commit()


def upsert_scores(
    date: str,
    raw_recovery: float | None,
    adjusted_readiness: int,
    db_path: Path,
) -> None:
    """Schreibt NUR den rohen Recovery-Wert + den Adjusted Score fuer `date`.

    Narrow upsert: ruehrt perceived/hooper nicht an. Wird am ENDE des Laufs aufgerufen,
    nachdem Layer 1 (calculate) gelaufen ist -- Spiegelung der Engine-Ausgabe, kein
    Rueckfluss in die Engine."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        _ensure_table(conn)
        conn.execute(
            """
            INSERT INTO daily_validation (date, raw_recovery, adjusted_readiness)
            VALUES (?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                raw_recovery       = excluded.raw_recovery,
                adjusted_readiness = excluded.adjusted_readiness
            """,
            (date, raw_recovery, adjusted_readiness),
        )
        conn.commit()
