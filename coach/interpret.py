"""Layer 2: Claude API Call.

Nimmt das Layer-1-Dict aus engine/calculate.py, schickt es als JSON an Claude
zusammen mit dem System Prompt aus coach/prompts/daily_report.md und gibt
den generierten Daily-Report-Text zurueck.

Regeln aus CLAUDE.md:
- Layer 2 ruft nichts aus Layer 1 auf. Wir nehmen nur das Dict entgegen.
- Layer 2 erfindet keine Zahlen. Das wird im System Prompt erzwungen.

API-Key kommt aus der Umgebungsvariable ANTHROPIC_API_KEY.
Modell und max_tokens kommen aus config.yaml -> coach.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def load_config(path: Path = CONFIG_PATH) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_prompt(rel_path: str) -> str:
    p = PROJECT_ROOT / rel_path
    if not p.exists():
        raise FileNotFoundError(f"System Prompt nicht gefunden: {p}")
    return p.read_text(encoding="utf-8").strip()


def generate_daily_report(layer1: dict, config: dict | None = None) -> str:
    """Generiert den Tagesreport aus dem Layer-1-Dict.

    Returns:
        Den vom Modell generierten Report-Text (deutscher Fliesstext, 4 Absaetze).
    """
    cfg = config or load_config()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY ist nicht gesetzt. Setze die Umgebungsvariable, "
            "bevor du Layer 2 ausfuehrst."
        )

    try:
        from anthropic import Anthropic
    except ImportError as e:
        raise RuntimeError(
            "anthropic SDK nicht installiert. Installiere mit: pip install anthropic"
        ) from e

    coach_cfg = cfg["coach"]
    system_prompt = _load_prompt(coach_cfg["daily_prompt"])

    user_message = (
        "Hier sind die Tageswerte aus dem deterministischen Layer 1. "
        "Erzeuge daraus den Daily Report nach den Regeln des System Prompts.\n\n"
        + json.dumps(layer1, indent=2, ensure_ascii=False, default=str)
    )

    client = Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=coach_cfg["model"],
        max_tokens=int(coach_cfg["max_tokens"]),
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    # Sonnet gibt einen Block aus content zurueck. Wir nehmen den Text-Anteil.
    parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
    return "\n".join(parts).strip()


if __name__ == "__main__":
    # Smoke-Test ohne DB: nimm ein Beispiel-Dict und ruf die API.
    sample = {
        "date": "2026-05-04",
        "whoop_recovery": 88,
        "adjusted_readiness": 63,
        "corrections_applied": ["deficit:-15", "checkin_limited:-10"],
        "acwr": 1.05,
        "acwr_zone": "optimal",
        "deficit_detected": True,
        "protein_ok": False,
        "checkin": "limited",
        "checkin_reason": "fatigue",
    }
    print(generate_daily_report(sample))
