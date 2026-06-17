"""Adjusted Readiness Score.

Korrigiert den Whoop Recovery Score um Signale, die Whoop nicht kennt:
subjektives Check-in, Schlafqualitaet, sowie eine
kombinierte HRV/RHR-Signalanalyse nach Buchheit (2014).

Sources:
- Buchheit M (2014). Monitoring training status with HR measures:
  do all roads lead to Rome? Frontiers in Physiology, 5:73.
  Kernaussagen, die hier umgesetzt sind:
    * Baseline = Median (nicht Mean) ueber 28 Tage. Robust gegen einzelne
      Ausreisser-Tage (Alkohol, krank, Reise) und reflektiert die typische
      individuelle Baseline besser als der arithmetische Mittelwert.
    * Tageswerte vorher mit 3-Tage Rolling Average glaetten. Einzelne
      HRV-Tageswerte sind zu rauschig, um interpretierbar zu sein.
    * HRV allein ist mehrdeutig -- nur die Kombination HRV + RHR macht die
      autonome Lage interpretierbar:
        - HRV hoch + RHR niedrig  -> parasympathisch dominant   (echt erholt)
        - HRV hoch + RHR hoch     -> "parasympathic saturation" (versteckter Stress)
        - HRV niedrig + RHR hoch  -> sympathisch dominant       (Uebertraining/Infekt)

Alle weiteren Korrekturen sind additiv und kommen aus `config.yaml -> readiness`.
Recovery-Gates verhindern Doppelbestrafung bei schon niedrigem Whoop-Score
(z. B. ein 'no'-Checkin bei Recovery=30 zieht nicht nochmal 20 Punkte ab).

Input (`day` dict):
    recovery_score:    float 0-100   (whoop_daily.recovery_score)            -- Pflicht
    checkin:           str | None    ("yes" | "limited" | "no")               -- optional
    sleep_efficiency:  float 0-100   (whoop_daily.sleep_efficiency)           -- optional
    sleep_hours:       float         (whoop_daily.sleep_hours)                -- optional
    hrv:               float         (whoop_daily.hrv, ms)                    -- optional
    rhr:               float         (whoop_daily.rhr, bpm)                   -- optional
    db_path:           str | Path    Pfad zur SQLite-DB fuer Baseline-Fetch   -- optional
    date:              str           YYYY-MM-DD, Stichtag fuer Baseline       -- optional

Die HRV/RHR-Korrektur greift nur, wenn hrv, rhr, db_path UND date vorhanden sind
und die History genug Datenpunkte hergibt. Sonst wird sie still uebersprungen.

Output:
    {
        "adjusted_readiness": int 0-100,
        "corrections_applied": list[str],
        "hrv_rhr_signal": dict | absent   # nur wenn Signal berechnet wurde
    }
"""

from __future__ import annotations

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


def _is_num(x: Any) -> bool:
    """True wenn x eine endliche Zahl ist (kein None, kein NaN)."""
    if x is None:
        return False
    try:
        f = float(x)
    except (TypeError, ValueError):
        return False
    return f == f  # NaN check ohne math import


# ============================================================
# HRV / RHR Baseline + Smoothing (Buchheit 2014)
# ============================================================

def _load_hrv_rhr_history(
    db_path: Path, target_date: str, window_days: int
) -> pd.DataFrame:
    """Letzte `window_days` Tage (HRV, RHR) bis einschl. target_date, aufsteigend sortiert."""
    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(
            """
            SELECT date, hrv, rhr
            FROM whoop_daily
            WHERE date <= ?
            ORDER BY date DESC
            LIMIT ?
            """,
            conn,
            params=(target_date, window_days),
        )
    return df.sort_values("date").reset_index(drop=True)


def compute_baseline(series: pd.Series, min_points: int = 7) -> Optional[float]:
    """Median der Serie (Buchheit 2014).

    Returns None, wenn weniger als `min_points` valide Werte vorhanden sind --
    eine Baseline aus z. B. nur 3 Tagen waere irrefuehrend stabil.
    """
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if len(clean) < min_points:
        return None
    return float(clean.median())


def compute_smoothed(series: pd.Series, window: int = 3) -> Optional[float]:
    """Rolling-Mean der letzten `window` Werte. None wenn zu wenig Daten.

    Glaettet Tag-zu-Tag-Rauschen, sodass ein einzelner schlechter HRV-Tag
    nicht direkt einen Stress-Alarm ausloest.
    """
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if len(clean) < window:
        return None
    return float(clean.tail(window).mean())


def hrv_rhr_signal(
    hrv_smoothed: float,
    hrv_baseline: float,
    rhr_smoothed: float,
    rhr_baseline: float,
    config: dict,
) -> dict[str, Any]:
    """Kombiniertes HRV+RHR Signal nach Buchheit 2014.

    Klassifiziert in vier Zustaende anhand der relativen Abweichung von Baseline:

      parasympathetic_dominant: HRV > baseline + hrv_high_pct UND RHR < baseline - rhr_delta_bpm
        -> echt erholt, vagal dominiert  -> +Bonus

      sympathetic_activated:    HRV > baseline + hrv_high_pct UND RHR > baseline + rhr_delta_bpm
        -> "parasympathic saturation" / versteckter Stress.
           HRV sieht gut aus, RHR widerlegt das  -> negative Korrektur.

      sympathetic_dominant:     HRV < baseline - hrv_low_pct  UND RHR > baseline + rhr_delta_bpm
        -> akuter Stress / Uebertraining / Infektion  -> deutliche neg. Korrektur

      mixed:                    alles andere
        -> keine Korrektur (Signal ist nicht eindeutig genug)

    Schwellen + Korrekturen kommen aus config.yaml -> readiness.hrv_rhr.

    Returns:
        {
            "type": <signal>,
            "correction": <int>,
            "hrv_delta_pct": <float, gerundet auf 1 Stelle>,
            "rhr_delta_bpm": <float, gerundet auf 1 Stelle>,
        }
    """
    r = config["readiness"]["hrv_rhr"]
    hrv_high = float(r["hrv_high_pct"]) / 100.0     # 5  -> 0.05
    hrv_low = float(r["hrv_low_pct"]) / 100.0       # 10 -> 0.10
    rhr_delta = float(r["rhr_delta_bpm"])           # 3 bpm

    if hrv_baseline <= 0:
        hrv_delta_pct = 0.0
    else:
        hrv_delta_pct = (hrv_smoothed - hrv_baseline) / hrv_baseline
    rhr_delta_val = rhr_smoothed - rhr_baseline

    hrv_up = hrv_delta_pct > hrv_high
    hrv_down = hrv_delta_pct < -hrv_low
    rhr_up = rhr_delta_val > rhr_delta
    rhr_down = rhr_delta_val < -rhr_delta

    if hrv_up and rhr_down:
        signal = "parasympathetic_dominant"
        correction = int(r["correction_parasympathetic_dominant"])
    elif hrv_up and rhr_up:
        signal = "sympathetic_activated"
        correction = int(r["correction_sympathetic_activated"])
    elif hrv_down and rhr_up:
        signal = "sympathetic_dominant"
        correction = int(r["correction_sympathetic_dominant"])
    else:
        signal = "mixed"
        correction = 0

    return {
        "type": signal,
        "correction": correction,
        "hrv_delta_pct": round(hrv_delta_pct * 100, 1),
        "rhr_delta_bpm": round(rhr_delta_val, 1),
    }


def _apply_hrv_rhr_correction(day: dict, config: dict) -> Optional[dict[str, Any]]:
    """Holt History aus der DB, berechnet Baseline+Smoothed und ruft hrv_rhr_signal().

    Returns None, wenn Voraussetzungen nicht erfuellt sind (fehlende Felder im
    `day` dict, keine hrv_rhr-Konfiguration, oder zu wenig History).
    """
    r = config["readiness"]
    if "hrv_rhr" not in r:
        return None

    if not (_is_num(day.get("hrv")) and _is_num(day.get("rhr"))):
        return None

    db_path = day.get("db_path")
    target_date = day.get("date")
    if db_path is None or target_date is None:
        return None

    cfg = r["hrv_rhr"]
    history = _load_hrv_rhr_history(
        Path(db_path), target_date, int(cfg["baseline_window"])
    )
    if history.empty:
        return None

    hrv_baseline = compute_baseline(history["hrv"])
    rhr_baseline = compute_baseline(history["rhr"])
    hrv_smoothed = compute_smoothed(history["hrv"], int(cfg["smoothing_window"]))
    rhr_smoothed = compute_smoothed(history["rhr"], int(cfg["smoothing_window"]))

    if None in (hrv_baseline, rhr_baseline, hrv_smoothed, rhr_smoothed):
        return None

    return hrv_rhr_signal(
        hrv_smoothed, hrv_baseline, rhr_smoothed, rhr_baseline, config
    )


# ============================================================
# Main compute
# ============================================================

def compute(day: dict, config: dict) -> dict[str, Any]:
    """Berechnet den Adjusted Readiness Score fuer einen Tag.

    Logik (additiv, dann auf 0-100 geklemmt):
        - checkin == "no" AND recovery > gate_checkin_no       -> +correction_checkin_no
        - checkin == "limited" AND recovery > gate_limited     -> +correction_checkin_limited
        - eff > eff_good AND hours > hours_good                -> +correction_sleep_bonus
        - eff < eff_bad OR hours < hours_bad                   -> +correction_sleep_malus
        - hrv_rhr_signal(...) -> +correction (Buchheit 2014, siehe hrv_rhr_signal)
    """
    r = config["readiness"]
    recovery = day.get("recovery_score")
    if not _is_num(recovery):
        raise ValueError("day['recovery_score'] muss eine Zahl sein")
    recovery = float(recovery)

    score = recovery
    corrections: list[str] = []

    # --- Subjektives Check-in ---
    checkin = day.get("checkin")
    if checkin == "no" and recovery > r["gate_recovery_checkin_no"]:
        delta = r["correction_checkin_no"]
        score += delta
        corrections.append(f"checkin_no:{delta:+d}")
    elif checkin == "limited" and recovery > r["gate_recovery_checkin_limited"]:
        delta = r["correction_checkin_limited"]
        score += delta
        corrections.append(f"checkin_limited:{delta:+d}")

    # --- Schlaf ---
    eff = day.get("sleep_efficiency")
    hours = day.get("sleep_hours")
    if _is_num(eff) and _is_num(hours):
        eff_f, hours_f = float(eff), float(hours)
        if eff_f > r["sleep_efficiency_good"] and hours_f > r["sleep_hours_good"]:
            delta = r["correction_sleep_bonus"]
            score += delta
            corrections.append(f"sleep_bonus:{delta:+d}")
        elif eff_f < r["sleep_efficiency_bad"] or hours_f < r["sleep_hours_bad"]:
            delta = r["correction_sleep_malus"]
            score += delta
            corrections.append(f"sleep_malus:{delta:+d}")

    # --- HRV/RHR Combined Signal (Buchheit 2014) ---
    signal_info = _apply_hrv_rhr_correction(day, config)
    if signal_info is not None and signal_info["correction"] != 0:
        delta = signal_info["correction"]
        score += delta
        corrections.append(f"{signal_info['type']}:{delta:+d}")

    adjusted = max(0, min(100, int(round(score))))
    out: dict[str, Any] = {
        "adjusted_readiness": adjusted,
        "corrections_applied": corrections,
    }
    if signal_info is not None:
        out["hrv_rhr_signal"] = signal_info
    return out


if __name__ == "__main__":
    cfg = load_config()

    # Basis-Sample (ohne HRV/RHR-Signal, weil db_path+date fehlen):
    sample = {
        "recovery_score": 88,
        "checkin": "limited",
    }
    result = compute(sample, cfg)

    print("Input:", sample)
    print("Output:", result)

    expected = 78  # 88 - 10 (checkin_limited)
    assert result["adjusted_readiness"] == expected, (
        f"adjusted_readiness {result['adjusted_readiness']} != erwartet {expected}"
    )
    assert "checkin_limited:-10" in result["corrections_applied"]
    assert "hrv_rhr_signal" not in result, "Ohne db_path+date kein Signal erwartet"
    print(f"\nOK (Basis): adjusted_readiness = {expected}")

    # Smoke-Test fuer hrv_rhr_signal() mit konstruierten Werten:
    test_cases = [
        # (hrv_s, hrv_b, rhr_s, rhr_b, erwarteter Typ)
        (60.0, 50.0, 45.0, 50.0, "parasympathetic_dominant"),  # +20%, -5bpm
        (60.0, 50.0, 55.0, 50.0, "sympathetic_activated"),     # +20%, +5bpm
        (40.0, 50.0, 55.0, 50.0, "sympathetic_dominant"),      # -20%, +5bpm
        (50.0, 50.0, 50.0, 50.0, "mixed"),                     #   0%,  0bpm
        (55.0, 50.0, 51.0, 50.0, "mixed"),                     # +10%, +1bpm
    ]
    for hrv_s, hrv_b, rhr_s, rhr_b, want in test_cases:
        sig = hrv_rhr_signal(hrv_s, hrv_b, rhr_s, rhr_b, cfg)
        assert sig["type"] == want, f"{(hrv_s, hrv_b, rhr_s, rhr_b)} -> {sig['type']}, erwartet {want}"
    print("OK (hrv_rhr_signal): 5 Faelle stimmen.")
