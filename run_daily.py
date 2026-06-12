"""Daily 30-second interface for Performance OS.

Usage: python run_daily.py

Flow:
    1. Read today's date; fall back to last Whoop day if today has no data
    2. Ask: "How do you feel?" (1=good / 2=okay / 3=bad)
    3. If 2 or 3, ask reason (soreness/fatigue/mental/deficit/sleep)
    4. Save check-in to daily_checkin for the analysis date
    5. Run Layer 1: calculate()
    6. Run protocol: generate_protocol() for training recommendation
    7. Run Layer 2: generate_daily_report() — skipped if ANTHROPIC_API_KEY missing
    8. Print formatted report (fits one screen)
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date as date_cls, timedelta
from pathlib import Path

import pandas as pd

from engine.calculate import calculate, load_config
from engine.ingest.checkin import upsert as save_checkin
from engine.models.protocol import DailyData, ProtocolOutput, generate_protocol
from engine.models.readiness import compute_baseline

PROJECT_ROOT = Path(__file__).resolve().parent

CHECKIN_NUMERIC: dict[str, int] = {"yes": 90, "limited": 60, "no": 30}
FEEL_MAP: dict[str, str] = {"1": "yes", "2": "limited", "3": "no"}
REASONS: list[str] = ["soreness", "fatigue", "mental", "deficit", "sleep"]
W = 58  # output column width


# ── DB helpers ────────────────────────────────────────────────

def _db_path(cfg: dict) -> Path:
    return PROJECT_ROOT / cfg["paths"]["database"]


def _fetch_whoop(cfg: dict, target: str) -> tuple[dict, str]:
    """Return (whoop_row, date). Falls back to last available row."""
    db = _db_path(cfg)
    try:
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT * FROM whoop_daily WHERE date = ?", (target,)
            )
            row = cur.fetchone()
            if row:
                return dict(row), target
            cur = conn.execute(
                "SELECT * FROM whoop_daily ORDER BY date DESC LIMIT 1"
            )
            row = cur.fetchone()
            if row:
                d = dict(row)
                return d, d["date"]
    except sqlite3.OperationalError:
        pass
    raise RuntimeError(
        "No Whoop data in DB. Run: python -m engine.ingest.whoop"
    )


def _fetch_yazio(cfg: dict, date: str) -> dict | None:
    db = _db_path(cfg)
    try:
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT * FROM yazio_daily WHERE date = ?", (date,)
            )
            row = cur.fetchone()
            return dict(row) if row else None
    except sqlite3.OperationalError:
        return None


def _fetch_rpe_yesterday(cfg: dict, date: str) -> float | None:
    yday = (date_cls.fromisoformat(date) - timedelta(days=1)).isoformat()
    db = _db_path(cfg)
    try:
        with sqlite3.connect(db) as conn:
            cur = conn.execute(
                "SELECT MAX(rpe) FROM training_log WHERE date = ?", (yday,)
            )
            v = cur.fetchone()[0]
            return float(v) if v is not None else None
    except Exception:
        return None


def _compute_baselines(cfg: dict, date: str) -> tuple[float | None, float | None]:
    """28-day medians for HRV and RHR (Buchheit 2014)."""
    db = _db_path(cfg)
    try:
        with sqlite3.connect(db) as conn:
            df = pd.read_sql_query(
                "SELECT hrv, rhr FROM whoop_daily "
                "WHERE date <= ? ORDER BY date DESC LIMIT 28",
                conn,
                params=(date,),
            )
        return compute_baseline(df["hrv"]), compute_baseline(df["rhr"])
    except Exception:
        return None, None


# ── Interactive check-in ──────────────────────────────────────

def _ask_checkin() -> tuple[str, str]:
    """Two questions max. Returns (readiness, reason)."""
    print()
    while True:
        ans = input("  How do you feel? (1=good  2=okay  3=bad): ").strip()
        if ans in FEEL_MAP:
            readiness = FEEL_MAP[ans]
            break
        print("  Please enter 1, 2, or 3.")

    if readiness == "yes":
        return "yes", "none"

    opts = " / ".join(REASONS)
    while True:
        ans = input(f"  Reason? ({opts}): ").strip().lower()
        if ans in REASONS:
            return readiness, ans
        print(f"  Options: {opts}")


# ── Protocol construction ─────────────────────────────────────

def _build_daily_data(
    layer1: dict,
    whoop: dict,
    yazio: dict | None,
    readiness: str,
    reason: str,
    cfg: dict,
    date: str,
) -> DailyData:
    hrv_baseline, rhr_baseline = _compute_baselines(cfg, date)

    hrv_raw = whoop.get("hrv")
    rhr_raw = whoop.get("rhr")
    # Use sentinel 1.0 when missing to avoid div/0 in generate_flags()
    hrv_val = float(hrv_raw) if hrv_raw else 1.0
    rhr_val = float(rhr_raw) if rhr_raw else 60.0

    # If no baseline yet, treat current as baseline → delta = 0, no HRV flags
    hrv_base = float(hrv_baseline) if hrv_baseline and hrv_baseline > 0 else hrv_val
    rhr_base = float(rhr_baseline) if rhr_baseline and rhr_baseline > 0 else rhr_val
    if hrv_base <= 0:
        hrv_base = 1.0

    whoop_recovery = float(whoop.get("recovery_score") or 0)
    weight_kg = float(cfg["athlete"]["weight_kg"])

    def _nut(field: str) -> float | None:
        return (
            float(yazio[field])
            if yazio and yazio.get(field) is not None
            else None
        )

    return DailyData(
        adjusted_readiness=int(layer1["adjusted_readiness"]),
        whoop_recovery=int(whoop_recovery),
        discrepancy=int(whoop_recovery) - CHECKIN_NUMERIC.get(readiness, 60),
        acwr=float(layer1.get("acwr") or 1.0),
        acwr_zone=str(layer1.get("acwr_zone") or "optimal"),
        checkin=readiness,
        checkin_reason=reason,
        rpe_yesterday=_fetch_rpe_yesterday(cfg, date),
        hrv=hrv_val,
        hrv_baseline=hrv_base,
        rhr=rhr_val,
        rhr_baseline=rhr_base,
        sleep_hours=float(whoop.get("sleep_hours") or 0),
        sleep_efficiency=float(whoop.get("sleep_efficiency") or 0),
        calories=_nut("calories"),
        tdee=float(cfg["nutrition"]["tdee"]),
        protein_g=_nut("protein"),
        protein_target_g=float(cfg["nutrition"]["protein_target_per_kg"]) * weight_kg,
        carbs_g=_nut("carbs"),
        deficit_detected=bool(layer1.get("deficit_detected", False)),
        position="FB",           # LB maps to fullback profile
        returning_from_injury=True,  # active ATFL rehab per CLAUDE.md
    )


# ── Output formatting ─────────────────────────────────────────

_REC_LABELS: dict[str, str] = {
    "full_intensity": "FULL INTENSITY",
    "reduced": "REDUCED INTENSITY",
    "active_recovery": "ACTIVE RECOVERY",
    "rest": "REST",
}


def _clip(text: str, width: int = W - 4) -> str:
    return text if len(text) <= width else text[: width - 1] + "..."


def _print_report(
    today: str,
    whoop_date: str,
    whoop: dict,
    layer1: dict,
    proto: ProtocolOutput,
    ai_report: str | None,
) -> None:
    bar = "=" * W
    thin = "-" * W

    adj = layer1["adjusted_readiness"]
    raw = float(layer1.get("whoop_recovery") or 0)
    arrow = "v" if adj < raw else ("^" if adj > raw else "=")
    corr = "  ".join(layer1.get("corrections_applied") or []) or "none"

    acwr_val = layer1.get("acwr")
    acwr_str = f"{acwr_val:.2f}" if acwr_val is not None else "--"
    acwr_zone = layer1.get("acwr_zone") or "--"

    sleep_h = whoop.get("sleep_hours")
    sleep_eff = whoop.get("sleep_efficiency")
    sleep_str = (
        f"{sleep_h:.1f}h / {sleep_eff:.0f}%" if sleep_h and sleep_eff else "--"
    )

    ci_val = layer1.get("checkin") or "--"
    ci_reason = layer1.get("checkin_reason") or ""
    ci_str = ci_val + (
        f" ({ci_reason})" if ci_reason and ci_reason != "none" else ""
    )

    rec = _REC_LABELS.get(proto.training_recommendation, proto.training_recommendation.upper())
    conf = proto.confidence

    print()
    print(bar)
    header = f"  AthletOS  {today}"
    if whoop_date != today:
        header += f"  (Whoop: {whoop_date})"
    print(header)
    print(bar)

    print(f"  Readiness  {raw:.0f} -> {adj} {arrow}   [{corr}]")
    print(f"  ACWR       {acwr_str} / {acwr_zone}   Sleep: {sleep_str}")
    print(f"  Check-in   {ci_str}")
    print()

    print(f"  >> {rec}  [{conf}]")
    for reason in proto.recommendation_reasons[:2]:
        print(f"     {_clip(reason)}")

    all_flags = (proto.flags + proto.nutrition_flags)[:3]
    if all_flags:
        print()
        for flag in all_flags:
            print(f"  {_clip(flag)}")

    if ai_report:
        print()
        print(thin)
        print("  DAILY REPORT")
        print(thin)
        print(ai_report)

    print()
    print(bar)
    print()


# ── Main ──────────────────────────────────────────────────────

def main() -> int:
    today = date_cls.today().isoformat()

    try:
        cfg = load_config()
    except Exception as e:
        print(f"Config error: {e}")
        return 3

    try:
        whoop, whoop_date = _fetch_whoop(cfg, today)
    except RuntimeError as e:
        print(str(e))
        return 1

    if whoop_date != today:
        print(f"  Note: No Whoop data for {today}. Using {whoop_date}.")

    try:
        readiness, reason = _ask_checkin()
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.")
        return 0

    # Save check-in for analysis date so calculate() picks it up correctly
    save_checkin([(whoop_date, readiness, reason)], _db_path(cfg))

    # Layer 1
    try:
        layer1 = calculate(whoop_date, cfg)
    except Exception as e:
        print(f"Layer 1 error: {type(e).__name__}: {e}")
        return 1

    # Ensure display matches what user just entered (upsert above guarantees this
    # for calculate, but make explicit in case of timing edge case)
    layer1["checkin"] = readiness
    layer1["checkin_reason"] = reason

    yazio = _fetch_yazio(cfg, whoop_date)

    # Protocol (deterministic, Layer 1)
    try:
        daily_data = _build_daily_data(
            layer1, whoop, yazio, readiness, reason, cfg, whoop_date
        )
        proto = generate_protocol(daily_data)
    except Exception as e:
        proto = ProtocolOutput(
            training_recommendation="reduced",
            recommendation_reasons=[f"Protocol unavailable ({type(e).__name__}: {e})"],
            confidence="low",
        )

    # Enrich layer1 for Layer 2 — Claude sees training context too
    layer1["training_recommendation"] = proto.training_recommendation
    layer1["recommendation_reasons"] = proto.recommendation_reasons[:4]
    layer1["protocol_flags"] = proto.flags[:4]

    # Layer 2 (optional)
    ai_report: str | None = None
    if os.environ.get("ANTHROPIC_API_KEY"):
        print("  Calling AI coach...", end="", flush=True)
        try:
            from coach.interpret import generate_daily_report
            ai_report = generate_daily_report(layer1, cfg)
            print(" done.")
        except Exception as e:
            print(f" failed: {type(e).__name__}: {e}")
    else:
        print("  (ANTHROPIC_API_KEY not set -- AI report skipped)")

    _print_report(today, whoop_date, whoop, layer1, proto, ai_report)
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main())
