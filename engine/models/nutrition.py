"""Nutrition checks fuer einen Tag.

Pure function: kein DB-Read, kein I/O. Eingabe = Tageswerte, Ausgabe = Flags.

Input (`day` dict):
    calories:           float | None    kcal des Tages (aus yazio_daily)
    protein:            float | None    g Protein des Tages
    carbs:              float | None    g Carbs des Tages (akzeptiert, derzeit ungenutzt)
    tdee:               float           kcal Total Daily Energy Expenditure (aus config)
    protein_target_g:   float           g Protein-Ziel fuer den Tag (aus config)

Output:
    deficit_detected:   bool            calories < tdee - deficit_threshold
    protein_ok:         bool            protein >= protein_target_g
    deficit_kcal:       float | None    tdee - calories (positiv = Defizit, None bei fehlenden Daten)

Fehlende Werte werden geraeuschlos behandelt: kein Crash, sondern False / None.
Das matched die CLAUDE.md-Regel 'continue with available data and log what's missing'.
Die Carb-Pre-Training-Pruefung steht in CLAUDE.md, braucht aber Info ueber
das Training von MORGEN -- gehoert deshalb in calculate.py, nicht hierher.
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


def _to_float(x: Any) -> float | None:
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def compute(day: dict, config: dict) -> dict[str, Any]:
    """Berechnet Defizit + Protein-OK fuer einen Tag."""
    threshold = float(config["nutrition"]["deficit_threshold"])

    calories = _to_float(day.get("calories"))
    protein = _to_float(day.get("protein"))
    tdee = _to_float(day.get("tdee"))
    target = _to_float(day.get("protein_target_g"))

    if calories is None or tdee is None:
        deficit_kcal: float | None = None
        deficit_detected = False
    else:
        deficit_kcal = tdee - calories
        deficit_detected = deficit_kcal > threshold

    protein_ok = protein is not None and target is not None and protein >= target

    return {
        "deficit_detected": deficit_detected,
        "protein_ok": protein_ok,
        "deficit_kcal": deficit_kcal,
    }


if __name__ == "__main__":
    cfg = load_config()
    target_g = cfg["nutrition"]["protein_target_per_kg"] * cfg["athlete"]["weight_kg"]

    # Sample: leichtes Defizit, Protein unter Ziel.
    sample = {
        "calories": 2100,
        "protein": 95,
        "carbs": 220,
        "tdee": cfg["nutrition"]["tdee"],   # 2500
        "protein_target_g": target_g,        # 1.6 * 66 = 105.6
    }
    result = compute(sample, cfg)
    print("Input:", sample)
    print("Output:", result)

    # 2500 - 2100 = 400 > 300 -> deficit_detected True
    # 95 < 105.6 -> protein_ok False
    assert result["deficit_detected"] is True
    assert result["protein_ok"] is False
    assert result["deficit_kcal"] == 400.0
    print("OK")
