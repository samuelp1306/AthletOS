"""Whoop CSV -> SQLite ingest.

Liest data/raw/physiologische_zyklen.csv (deutscher Whoop-Export) und
schreibt die Kernwerte in die Tabelle `whoop_daily` der SQLite-DB.

Mapping deutsche CSV-Spalte -> DB-Spalte (laut Schema in CLAUDE.md):
    Endzeit des Zyklus               -> date            (nur Datumsteil)
    Erholungswert %                  -> recovery_score
    Herzfrequenzvariabilitaet (ms)   -> hrv
    Ruheherzfrequenz (Schlaege ...)  -> rhr
    Schlafdauer (Min.)               -> sleep_hours     (Min. / 60)
    Schlafeffizienz %                -> sleep_efficiency
    Atemfrequenz (Atemzuege/Min.)    -> respiratory_rate
    Hauttemperatur (Celsius)         -> skin_temp
    Tagesbelastung                   -> strain
    Verbrannte Energie (cal)         -> calories_burned
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"

COLUMN_MAP: dict[str, str] = {
    "Erholungswert %": "recovery_score",
    "Herzfrequenzvariabilität (ms)": "hrv",
    "Ruheherzfrequenz (Schläge pro Minute)": "rhr",
    "Schlafeffizienz %": "sleep_efficiency",
    "Atemfrequenz (Atemzüge/Min.)": "respiratory_rate",
    "Hauttemperatur (Celsius)": "skin_temp",
    "Tagesbelastung": "strain",
    "Verbrannte Energie (cal)": "calories_burned",
}

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS whoop_daily (
    date TEXT PRIMARY KEY,
    recovery_score REAL,
    hrv REAL,
    rhr REAL,
    sleep_hours REAL,
    sleep_efficiency REAL,
    respiratory_rate REAL,
    skin_temp REAL,
    strain REAL,
    calories_burned REAL
)
"""


def load_config(path: Path = CONFIG_PATH) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def transform(
    csv_path: Path, min_sleep_minutes: float = 180.0
) -> tuple[pd.DataFrame, list[str]]:
    """CSV laden und auf das DB-Schema mappen.

    Zyklen mit `Schlafdauer (Min.)` unter `min_sleep_minutes` werden komplett
    verworfen: das sind Nap-Only-Eintraege (z. B. Strap-Ladegap), in denen
    der Nachtschlaf nicht erfasst wurde -- auch Recovery/HRV sind dort unbrauchbar.

    Returns:
        (kept_df, dropped_dates) -- dropped_dates enthaelt Datums-Strings, die
        aus der DB entfernt werden sollen, falls sie dort aus frueheren Imports
        noch existieren.
    """
    df = pd.read_csv(csv_path)

    # Unvollstaendige Zyklen (kein Ende) raus - gehoeren keinem abgeschlossenen Tag.
    df = df[df["Endzeit des Zyklus"].notna()].copy()
    df["date"] = pd.to_datetime(df["Endzeit des Zyklus"]).dt.strftime("%Y-%m-%d")

    schlafdauer_min = pd.to_numeric(df["Schlafdauer (Min.)"], errors="coerce")
    keep_mask = schlafdauer_min >= min_sleep_minutes

    kept = df[keep_mask].copy()
    # Datumswerte, die durch den Nap-Filter komplett wegfallen (keine andere
    # Zeile fuer denselben Tag haelt).
    dropped_dates = sorted(set(df.loc[~keep_mask, "date"]) - set(kept["date"]))

    kept["sleep_hours"] = pd.to_numeric(kept["Schlafdauer (Min.)"], errors="coerce") / 60.0

    out = pd.DataFrame({"date": kept["date"].values, "sleep_hours": kept["sleep_hours"].values})
    for src, dst in COLUMN_MAP.items():
        out[dst] = pd.to_numeric(kept[src], errors="coerce").values

    # Bei mehreren Zyklen pro Tag den letzten gewinnen lassen.
    out = out.drop_duplicates(subset=["date"], keep="last")

    out = out[
        [
            "date",
            "recovery_score",
            "hrv",
            "rhr",
            "sleep_hours",
            "sleep_efficiency",
            "respiratory_rate",
            "skin_temp",
            "strain",
            "calories_burned",
        ]
    ]
    return out, dropped_dates


def upsert(
    df: pd.DataFrame, db_path: Path, dropped_dates: list[str] | None = None
) -> tuple[int, int]:
    """Idempotenter Upsert + Loeschen ungueltig gewordener Zeilen.

    `dropped_dates` enthaelt Datumswerte, die der Filter komplett verworfen hat;
    falls sie aus frueheren Importen noch in der DB liegen, werden sie entfernt.

    Returns:
        (n_upserted, n_deleted)
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [tuple(None if pd.isna(v) else v for v in row) for row in df.itertuples(index=False)]

    with sqlite3.connect(db_path) as conn:
        conn.execute(CREATE_TABLE_SQL)
        n_deleted = 0
        if dropped_dates:
            placeholders = ",".join("?" * len(dropped_dates))
            cur = conn.execute(
                f"DELETE FROM whoop_daily WHERE date IN ({placeholders})",
                dropped_dates,
            )
            n_deleted = cur.rowcount
        conn.executemany(
            """
            INSERT INTO whoop_daily (
                date, recovery_score, hrv, rhr, sleep_hours,
                sleep_efficiency, respiratory_rate, skin_temp, strain, calories_burned
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                recovery_score   = excluded.recovery_score,
                hrv              = excluded.hrv,
                rhr              = excluded.rhr,
                sleep_hours      = excluded.sleep_hours,
                sleep_efficiency = excluded.sleep_efficiency,
                respiratory_rate = excluded.respiratory_rate,
                skin_temp        = excluded.skin_temp,
                strain           = excluded.strain,
                calories_burned  = excluded.calories_burned
            """,
            rows,
        )
        conn.commit()
    return len(rows), n_deleted


def ingest(config: dict | None = None) -> tuple[int, int]:
    """Liest die Whoop-CSV und schreibt sie in whoop_daily.

    Returns:
        (n_upserted, n_deleted)
    """
    cfg = config or load_config()
    csv_path = PROJECT_ROOT / cfg["paths"]["raw_data"] / "physiologische_zyklen.csv"
    db_path = PROJECT_ROOT / cfg["paths"]["database"]
    min_sleep = float(cfg.get("ingest", {}).get("whoop", {}).get("min_sleep_minutes", 180))

    df, dropped_dates = transform(csv_path, min_sleep_minutes=min_sleep)
    return upsert(df, db_path, dropped_dates=dropped_dates)


if __name__ == "__main__":
    cfg = load_config()
    db_path = PROJECT_ROOT / cfg["paths"]["database"]

    n_up, n_del = ingest(cfg)
    print(
        f"Eingespielt: {n_up} Zeilen aus physiologische_zyklen.csv -> {db_path}"
        + (f" (Nap-Only entfernt: {n_del})" if n_del else "")
    )

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM whoop_daily ORDER BY date DESC LIMIT 3")
        rows = cur.fetchall()

    print("\nLetzte 3 Zeilen aus whoop_daily:")
    for r in rows:
        print(dict(r))
