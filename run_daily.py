"""Daily Run -- ein Kommando, ein Tag.

Pipeline:
    1. engine.calculate.calculate(date)   -> Layer-1-Dict aus DB
    2. coach.interpret.generate_daily_report(dict) -> Report-Text via Claude

Usage:
    python run_daily.py                     # heutiges Datum
    python run_daily.py --date 2026-05-04   # expliziter Tag
    python run_daily.py --json              # Layer-1-Dict zusaetzlich ausgeben
    python run_daily.py --dry-run           # nur Layer 1, kein API-Call

ANTHROPIC_API_KEY muss als Umgebungsvariable gesetzt sein (ausser --dry-run).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date as date_cls

from coach.interpret import generate_daily_report, load_config
from engine.calculate import calculate


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Performance OS Daily Report")
    p.add_argument(
        "--date",
        default=date_cls.today().isoformat(),
        help="Datum YYYY-MM-DD (default: heute)",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Layer-1-Dict zusaetzlich als JSON drucken",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Nur Layer 1, kein API-Call",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    cfg = load_config()

    # --- Layer 1 ---
    try:
        layer1 = calculate(args.date, cfg)
    except ValueError as e:
        print(f"Layer 1 abgebrochen: {e}", file=sys.stderr)
        print(
            "  -> Vermutlich fehlt der Whoop-Eintrag fuer den Tag. "
            "Erst 'python -m engine.ingest.whoop' laufen lassen.",
            file=sys.stderr,
        )
        return 1

    if args.json:
        print("=== Layer 1 (engine/calculate.py) ===")
        print(json.dumps(layer1, indent=2, ensure_ascii=False, default=str))
        print()

    if args.dry_run:
        if not args.json:
            print(json.dumps(layer1, indent=2, ensure_ascii=False, default=str))
        return 0

    # --- Layer 2 ---
    try:
        report = generate_daily_report(layer1, cfg)
    except RuntimeError as e:
        print(f"Layer 2 abgebrochen: {e}", file=sys.stderr)
        return 2

    print(f"=== Daily Report {args.date} ===")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
