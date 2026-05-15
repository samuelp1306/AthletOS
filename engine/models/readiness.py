"""Adjusted Readiness Score.

Korrigiert den Whoop Recovery Score um Signale, die Whoop nicht kennt:
Kalorien-Defizit, subjektives Check-in, Schlafqualitaet.

Alle Korrekturen sind additiv und kommen aus `config.yaml -> readiness`.
Recovery-Gates verhindern Doppelbestrafung bei schon niedrigem Whoop-Score
(z. B. ein 'no'-Checkin bei Recovery=30 zieht nicht nochmal 20 Punkte ab).

Input (`day` dict):
    recovery_score:    float 0-100   (whoop_daily.recovery_score)            -- Pflicht
    deficit_detected:  bool          (aus nutrition.py)                       -- optional
    checkin:           str | None    ("yes" | "limited" | "no")               -- optional
    sleep_efficiency:  float 0-100   (whoop_daily.sleep_efficiency)           -- optional
    sleep_hours:       float         (whoop_daily.sleep_hours)                -- optional

Output:
    {
        "adjusted_readiness": int 0-100,
        "corrections_applied": list[str]    # z.B. ["deficit:-15", "checkin_limited:-10"]
    }
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

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


def compute(day: dict, config: dict) -> dict[str, Any]:
    """Berechnet den Adjusted Readiness Score fuer einen Tag.

    Logik (additiv, dann auf 0-100 geklemmt):
        - deficit_detected AND recovery > gate_deficit         -> +correction_deficit
        - checkin == "no" AND recovery > gate_checkin_no       -> +correction_checkin_no
        - checkin == "limited" AND recovery > gate_limited     -> +correction_checkin_limited
        - eff > eff_good AND hours > hours_good                -> +correction_sleep_bonus
        - eff < eff_bad OR hours < hours_bad                   -> +correction_sleep_malus
    """
    r = config["readiness"]
    recovery = day.get("recovery_score")
    if not _is_num(recovery):
        raise ValueError("day['recovery_score'] muss eine Zahl sein")
    recovery = float(recovery)

    score = recovery
    corrections: list[str] = []

    # --- Defizit ---
    if day.get("deficit_detected") and recovery > r["gate_recovery_deficit"]:
        delta = r["correction_deficit"]
        score += delta
        corrections.append(f"deficit:{delta:+d}")

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

    adjusted = max(0, min(100, int(round(score))))
    return {"adjusted_readiness": adjusted, "corrections_applied": corrections}


if __name__ == "__main__":
    cfg = load_config()

    # Sample aus dem Dashboard-Screenshot:
    # recovery=88, hrv=102 (nicht relevant fuer readiness), deficit=True, checkin=limited
    # Keine Schlafwerte uebergeben -> Schlafkorrekturen entfallen.
    sample = {
        "recovery_score": 88,
        "deficit_detected": True,
        "checkin": "limited",
    }
    result = compute(sample, cfg)

    print("Input:", sample)
    print("Output:", result)

    # Erwartet: 88 - 15 (deficit) - 10 (checkin_limited) = 63
    expected = 63
    assert result["adjusted_readiness"] == expected, (
        f"adjusted_readiness {result['adjusted_readiness']} != erwartet {expected}"
    )
    assert "deficit:-15" in result["corrections_applied"]
    assert "checkin_limited:-10" in result["corrections_applied"]
    print(f"\nOK: adjusted_readiness = {expected}, corrections = {result['corrections_applied']}")
