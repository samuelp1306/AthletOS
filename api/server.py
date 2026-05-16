"""Performance OS REST API (FastAPI).

Endpoints:
    GET  /api/daily?date=YYYY-MM-DD       Layer-1 + protocol-output fuer einen Tag
    GET  /api/trends?days=30&end_date=... Arrays fuer Charts
    POST /api/checkin                     Speichert daily_checkin
    GET  /api/report?date=YYYY-MM-DD      Claude-Report (synchron)
    GET  /api/nutrition?date=YYYY-MM-DD   yazio_daily-Werte + Targets

Start:
    cd <project_root>
    python -m uvicorn api.server:app --reload --port 8000

CORS ist auf http://localhost:5173 freigegeben (Vite dev server).
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.calculate import calculate  # noqa: E402
from engine.models import acwr  # noqa: E402
from engine.models.protocol import DailyData, generate_protocol  # noqa: E402

CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_db_path() -> Path:
    return PROJECT_ROOT / load_config()["paths"]["database"]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _fetch_one(conn: sqlite3.Connection, table: str, date_str: str) -> dict | None:
    if not _table_exists(conn, table):
        return None
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        f"SELECT * FROM {table} WHERE date = ?", (date_str,)
    ).fetchone()
    return dict(row) if row else None


def _fetch_rpe_yesterday(conn: sqlite3.Connection, date: str) -> float | None:
    if not _table_exists(conn, "training_log"):
        return None
    cur = conn.execute(
        "SELECT MAX(rpe) FROM training_log WHERE date = date(?, '-1 day')",
        (date,),
    )
    row = cur.fetchone()
    return float(row[0]) if row and row[0] is not None else None


# Position-Mapping aus config -> Modell-Kuerzel (siehe viz/dashboard.py)
_POSITION_MAP = {
    "GK": "GK", "TW": "GK",
    "CB": "CB", "IV": "CB",
    "FB": "FB", "LB": "FB", "RB": "FB",
    "CM": "CM", "ZM": "CM", "DM": "CM",
    "AM": "AM", "OM": "AM", "ZOM": "AM",
    "W": "W", "LW": "W", "RW": "W", "LM": "W", "RM": "W",
    "ST": "ST", "CF": "ST",
}


def _normalize_position(cfg: dict) -> str:
    raw = (cfg.get("athlete", {}).get("position") or "FB").upper()
    token = raw.replace(",", " ").replace("/", " ").split()
    return _POSITION_MAP.get(token[0] if token else "FB", "FB")


def _build_daily_data(date: str, layer1: dict, cfg: dict) -> DailyData:
    """Konstruiert DailyData fuer protocol.generate_protocol()."""
    db_path = get_db_path()
    weight_kg = float(cfg["athlete"]["weight_kg"])
    protein_target_g = float(cfg["nutrition"]["protein_target_per_kg"]) * weight_kg

    with sqlite3.connect(db_path) as conn:
        whoop = _fetch_one(conn, "whoop_daily", date) or {}
        yazio = _fetch_one(conn, "yazio_daily", date) or {}
        rpe_yesterday = _fetch_rpe_yesterday(conn, date)

        # 28-Tage Baselines aus whoop_daily bis date
        bdf = pd.read_sql_query(
            "SELECT hrv, rhr FROM whoop_daily WHERE date <= ? "
            "ORDER BY date DESC LIMIT 28",
            conn,
            params=(date,),
        )
    hrv_baseline = float(bdf["hrv"].mean(skipna=True)) if not bdf.empty else float(whoop.get("hrv") or 1)
    rhr_baseline = float(bdf["rhr"].mean(skipna=True)) if not bdf.empty else float(whoop.get("rhr") or 1)
    if not hrv_baseline:
        hrv_baseline = 1.0
    if not rhr_baseline:
        rhr_baseline = 1.0

    whoop_recovery = int(layer1["whoop_recovery"]) if layer1.get("whoop_recovery") is not None else 0
    adjusted = int(layer1["adjusted_readiness"])

    return DailyData(
        adjusted_readiness=adjusted,
        whoop_recovery=whoop_recovery,
        discrepancy=whoop_recovery - adjusted,
        acwr=float(layer1["acwr"]) if layer1.get("acwr") is not None else 1.0,
        acwr_zone=layer1.get("acwr_zone") or "optimal",
        checkin=layer1.get("checkin") or "yes",
        checkin_reason=layer1.get("checkin_reason") or "none",
        rpe_yesterday=rpe_yesterday,
        hrv=float(whoop.get("hrv") or 0),
        hrv_baseline=hrv_baseline,
        rhr=float(whoop.get("rhr") or 0),
        rhr_baseline=rhr_baseline,
        sleep_hours=float(whoop.get("sleep_hours") or 0),
        sleep_efficiency=float(whoop.get("sleep_efficiency") or 0),
        calories=float(yazio["calories"]) if yazio.get("calories") is not None else None,
        tdee=float(cfg["nutrition"]["tdee"]),
        protein_g=float(yazio["protein"]) if yazio.get("protein") is not None else None,
        protein_target_g=protein_target_g,
        carbs_g=float(yazio["carbs"]) if yazio.get("carbs") is not None else None,
        deficit_detected=bool(layer1.get("deficit_detected", False)),
        position=_normalize_position(cfg),
    )


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CheckinBody(BaseModel):
    date: str = Field(..., description="YYYY-MM-DD")
    rpe: float | None = Field(None, ge=1, le=10)
    readiness: str = Field(..., pattern="^(yes|limited|no)$")
    reason: str | None = None


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Performance OS API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        # Falls die PWA via 8000-Port served wird (gleicher Origin), nicht noetig
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


# --- /api/daily ----------------------------------------------------------

@app.get("/api/daily")
def daily(date: str) -> dict[str, Any]:
    cfg = load_config()
    try:
        layer1 = calculate(date, cfg)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Whoop-Vitals fuer das Frontend (HRV/RHR/Sleep)
    db_path = get_db_path()
    with sqlite3.connect(db_path) as conn:
        whoop = _fetch_one(conn, "whoop_daily", date) or {}
        bdf = pd.read_sql_query(
            "SELECT hrv, rhr FROM whoop_daily WHERE date <= ? "
            "ORDER BY date DESC LIMIT 28",
            conn,
            params=(date,),
        )
        checkin_row = _fetch_one(conn, "daily_checkin", date) or {}

    hrv_baseline = float(bdf["hrv"].mean(skipna=True)) if not bdf.empty else None
    rhr_baseline = float(bdf["rhr"].mean(skipna=True)) if not bdf.empty else None

    # Protocol-Output (best-effort; bei DailyData-Fehler weiter ohne)
    protocol_payload = None
    try:
        daily_data = _build_daily_data(date, layer1, cfg)
        proto = generate_protocol(daily_data)
        protocol_payload = {
            "training_recommendation": proto.training_recommendation,
            "confidence": proto.confidence,
            "recommendation_reasons": list(proto.recommendation_reasons or []),
            "flags": list(proto.flags or []),
            "nutrition_flags": list(proto.nutrition_flags or []),
            "bloodwork_flags": list(proto.bloodwork_flags or []),
        }
    except Exception as e:  # nicht den ganzen Daily-Call killen
        protocol_payload = {"error": f"{type(e).__name__}: {e}"}

    whoop_recovery = layer1.get("whoop_recovery")
    adjusted = layer1["adjusted_readiness"]
    discrepancy = (
        int(whoop_recovery) - int(adjusted)
        if whoop_recovery is not None else 0
    )

    return {
        "date": date,
        "whoop_recovery": whoop_recovery,
        "adjusted_readiness": adjusted,
        "corrections_applied": layer1.get("corrections_applied") or [],
        "acwr": layer1.get("acwr"),
        "acwr_zone": layer1.get("acwr_zone"),
        "deficit_detected": bool(layer1.get("deficit_detected", False)),
        "protein_ok": bool(layer1.get("protein_ok", False)),
        "checkin": checkin_row.get("readiness") or layer1.get("checkin"),
        "checkin_reason": checkin_row.get("reason") or layer1.get("checkin_reason"),
        "rpe": checkin_row.get("rpe"),
        "hrv": whoop.get("hrv"),
        "rhr": whoop.get("rhr"),
        "sleep_hours": whoop.get("sleep_hours"),
        "sleep_efficiency": whoop.get("sleep_efficiency"),
        "hrv_baseline": hrv_baseline,
        "rhr_baseline": rhr_baseline,
        "discrepancy": discrepancy,
        "protocol": protocol_payload,
    }


# --- /api/trends --------------------------------------------------------

@app.get("/api/trends")
def trends(days: int = 30, end_date: str | None = None) -> dict[str, list]:
    cfg = load_config()
    db_path = get_db_path()

    # Datumsfenster aufbauen
    with sqlite3.connect(db_path) as conn:
        if end_date is None:
            row = conn.execute(
                "SELECT MAX(date) FROM whoop_daily"
            ).fetchone()
            end_date = row[0] if row and row[0] else None
        if not end_date:
            return {k: [] for k in ["dates", "hrv", "recovery",
                                    "adjusted_readiness", "acwr",
                                    "sleep_hours", "discrepancy"]}

        whoop_df = pd.read_sql_query(
            "SELECT date, recovery_score, hrv, sleep_hours "
            "FROM whoop_daily WHERE date <= ? ORDER BY date",
            conn,
            params=(end_date,),
        ).tail(days).reset_index(drop=True)

    # ACWR fuer denselben Zeitraum
    acwr_df = acwr.compute(db_path, cfg)
    acwr_df["date_str"] = pd.to_datetime(acwr_df["date"]).dt.strftime("%Y-%m-%d")
    acwr_lookup = dict(zip(acwr_df["date_str"], acwr_df["acwr"]))

    # Adjusted Readiness pro Tag via calculate() (akzeptable Kosten fuer 30 Tage)
    adj: list[int | None] = []
    disc: list[int | None] = []
    for _, row in whoop_df.iterrows():
        d = row["date"].strftime("%Y-%m-%d") if hasattr(row["date"], "strftime") else str(row["date"])[:10]
        try:
            l1 = calculate(d, cfg)
            adj.append(int(l1["adjusted_readiness"]))
            wr = l1.get("whoop_recovery")
            disc.append(int(wr) - int(l1["adjusted_readiness"]) if wr is not None else None)
        except Exception:
            adj.append(None)
            disc.append(None)

    def _series(col):
        return [None if pd.isna(v) else float(v) for v in whoop_df[col]]

    date_strs = [
        d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]
        for d in whoop_df["date"]
    ]
    acwr_series = [
        (float(acwr_lookup[d]) if d in acwr_lookup and pd.notna(acwr_lookup[d]) else None)
        for d in date_strs
    ]

    return {
        "dates": date_strs,
        "hrv": _series("hrv"),
        "recovery": _series("recovery_score"),
        "adjusted_readiness": adj,
        "acwr": acwr_series,
        "sleep_hours": _series("sleep_hours"),
        "discrepancy": disc,
    }


# --- POST /api/checkin --------------------------------------------------

@app.post("/api/checkin")
def post_checkin(body: CheckinBody) -> dict:
    if body.readiness not in {"yes", "limited", "no"}:
        raise HTTPException(400, "readiness must be yes|limited|no")

    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        # idempotente Schema-Pflege (rpe-Spalte hinzufuegen, falls aelter)
        try:
            from engine.ingest import checkin as checkin_ingest
            checkin_ingest.migrate_add_rpe_column(conn)
        except Exception:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS daily_checkin ("
                "date TEXT PRIMARY KEY, readiness TEXT NOT NULL, "
                "reason TEXT, rpe REAL)"
            )
        conn.execute(
            "INSERT OR REPLACE INTO daily_checkin (date, readiness, reason, rpe) "
            "VALUES (?, ?, ?, ?)",
            (body.date, body.readiness, body.reason, body.rpe),
        )
        conn.commit()
    return {"success": True}


# --- /api/nutrition -----------------------------------------------------

@app.get("/api/nutrition")
def nutrition(date: str) -> dict:
    cfg = load_config()
    db_path = get_db_path()
    weight_kg = float(cfg["athlete"]["weight_kg"])
    tdee = float(cfg["nutrition"]["tdee"])
    protein_target = float(cfg["nutrition"]["protein_target_per_kg"]) * weight_kg

    with sqlite3.connect(db_path) as conn:
        row = _fetch_one(conn, "yazio_daily", date)

    if not row:
        return {
            "date": date,
            "available": False,
            "calories": None, "protein": None, "carbs": None, "fat": None,
            "tdee": tdee, "protein_target": protein_target,
            "weight_kg": weight_kg,
            "deficit": None,
        }

    cals = float(row["calories"]) if row.get("calories") is not None else None
    deficit = (tdee - cals) if cals is not None else None

    return {
        "date": date,
        "available": True,
        "calories": cals,
        "protein": float(row["protein"]) if row.get("protein") is not None else None,
        "carbs": float(row["carbs"]) if row.get("carbs") is not None else None,
        "fat": float(row["fat"]) if row.get("fat") is not None else None,
        "tdee": tdee,
        "protein_target": protein_target,
        "weight_kg": weight_kg,
        "deficit": deficit,
    }


# --- /api/report --------------------------------------------------------

@app.get("/api/report")
def report(date: str) -> dict:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(503, "ANTHROPIC_API_KEY nicht gesetzt")

    cfg = load_config()
    try:
        layer1 = calculate(date, cfg)
    except ValueError as e:
        raise HTTPException(404, str(e))

    try:
        from coach.interpret import generate_daily_report
        text = generate_daily_report(layer1, cfg)
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")

    return {"date": date, "report": text}
