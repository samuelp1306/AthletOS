"""Tests fuer engine/ingest/whoop_api.py -- nur Parsing, kein Netzwerk.

Aufruf: python -m unittest tests.test_whoop_api
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from engine.ingest import whoop, whoop_api


def _record(during: str, sleep_during: str, sleep_ms: int, *, tz: str = "+0200",
            is_nap: bool = False) -> dict:
    """Minimaler cycles/details-Record nach dem Schema aus WHOOP_API_GUIDE.md."""
    return {
        "cycle": {
            "during": during,
            "timezone_offset": tz,
            "scaled_strain": 13.4,
            "day_kilojoules": 10370.79,
        },
        "sleeps": [{
            "during": sleep_during,
            "is_nap": is_nap,
            "quality_duration": sleep_ms,
            "in_sleep_efficiency": 0.95037776,
            "respiratory_rate": 13.828125,
        }],
        "recovery": {
            "recovery_score": 95,
            "resting_heart_rate": 46,
            "hrv_rmssd": 0.099190265,
            "skin_temp_celsius": 33.199333,
        },
    }


CLOSED = _record(
    "['2026-06-20T20:30:00.000Z','2026-06-21T21:00:00.000Z')",
    "['2026-06-20T20:30:00.000Z','2026-06-21T05:00:00.000Z')",
    27_928_890,
)
# Laufender Zyklus: offene Range, Aufwachen am 22.06. lokal.
OPEN = _record(
    "['2026-06-21T21:00:00.000Z',)",
    "['2026-06-21T21:00:00.000Z','2026-06-22T05:30:00.000Z')",
    28_800_000,
)
# Nap-Only-Zyklus (Strap-Ladegap) -> muss verworfen werden.
NAP_ONLY = _record(
    "['2026-06-18T22:00:00.000Z','2026-06-19T22:00:00.000Z')",
    "['2026-06-19T12:00:00.000Z','2026-06-19T12:30:00.000Z')",
    30 * 60_000,
    is_nap=True,
)


class ParseTests(unittest.TestCase):
    def test_parse_range_closed_and_open(self) -> None:
        start, end = whoop_api.parse_range(CLOSED["cycle"]["during"])
        self.assertEqual(start.isoformat(), "2026-06-20T20:30:00+00:00")
        self.assertEqual(end.isoformat(), "2026-06-21T21:00:00+00:00")
        start, end = whoop_api.parse_range(OPEN["cycle"]["during"])
        self.assertIsNotNone(start)
        self.assertIsNone(end)

    def test_parse_offset(self) -> None:
        self.assertEqual(whoop_api.parse_offset("-0800").utcoffset(None).total_seconds(), -8 * 3600)
        self.assertEqual(whoop_api.parse_offset("+02:00").utcoffset(None).total_seconds(), 2 * 3600)
        self.assertEqual(whoop_api.parse_offset(None).utcoffset(None).total_seconds(), 0)


class TransformTests(unittest.TestCase):
    def test_unit_conversion_and_local_date(self) -> None:
        row = whoop_api.record_to_row(CLOSED)
        # Ende 21:00Z = 23:00 lokal (+02:00) -> 21.06.
        self.assertEqual(row["date"], "2026-06-21")
        self.assertAlmostEqual(row["hrv"], 99.190265, places=4)
        self.assertAlmostEqual(row["sleep_hours"], 7.758025, places=4)
        self.assertAlmostEqual(row["sleep_efficiency"], 95.037776, places=4)
        self.assertAlmostEqual(row["calories_burned"], 2478.68, places=1)
        self.assertEqual(row["recovery_score"], 95)
        self.assertEqual(row["rhr"], 46)
        self.assertEqual(row["strain"], 13.4)

    def test_cycle_end_after_local_midnight(self) -> None:
        # Ende 22:30Z = 00:30 lokal am Folgetag -> Datum springt wie im CSV.
        rec = _record(
            "['2026-06-20T20:30:00.000Z','2026-06-21T22:30:00.000Z')",
            "['2026-06-20T20:30:00.000Z','2026-06-21T05:00:00.000Z')",
            27_000_000,
        )
        self.assertEqual(whoop_api.record_to_row(rec)["date"], "2026-06-22")

    def test_open_cycle_dated_by_wake(self) -> None:
        self.assertEqual(whoop_api.record_to_row(OPEN)["date"], "2026-06-22")

    def test_nap_only_dropped(self) -> None:
        df, dropped = whoop_api.transform([NAP_ONLY, CLOSED, OPEN], min_sleep_minutes=180)
        self.assertEqual(list(df["date"]), ["2026-06-21", "2026-06-22"])
        self.assertEqual(dropped, ["2026-06-20"])
        self.assertEqual(list(df.columns), whoop_api.DB_COLUMNS)

    def test_later_cycle_wins_on_same_date(self) -> None:
        early = _record(
            "['2026-06-20T20:30:00.000Z','2026-06-21T22:30:00.000Z')",
            "['2026-06-20T20:30:00.000Z','2026-06-21T05:00:00.000Z')",
            27_000_000,
        )
        later = _record(
            "['2026-06-21T22:30:00.000Z',)",
            "['2026-06-21T22:30:00.000Z','2026-06-22T06:00:00.000Z')",
            25_000_000,
        )
        later["recovery"]["recovery_score"] = 42
        df, _ = whoop_api.transform([later, early])
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["recovery_score"], 42)

    def test_upsert_into_whoop_daily(self) -> None:
        df, dropped = whoop_api.transform([CLOSED, OPEN])
        # ignore_cleanup_errors: Windows haelt die SQLite-Datei evtl. noch kurz gesperrt.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db = Path(tmp) / "t.db"
            n_up, n_del = whoop.upsert(df, db, dropped_dates=dropped)
            self.assertEqual((n_up, n_del), (2, 0))
            with sqlite3.connect(db) as conn:
                rows = conn.execute("SELECT date, recovery_score FROM whoop_daily ORDER BY date").fetchall()
        self.assertEqual(rows, [("2026-06-21", 95.0), ("2026-06-22", 95.0)])


class ChunkTests(unittest.TestCase):
    def test_chunks_cover_range_without_gaps(self) -> None:
        ranges = whoop_api.chunk_ranges(90, 30, date(2026, 10, 29))
        self.assertEqual(ranges[0][0], "2026-07-31T00:00:00.000Z")
        self.assertEqual(ranges[-1][1], "2026-10-30T23:59:59.999Z")
        self.assertEqual(len(ranges), 4)  # 92 Tage -> 30+30+30+2
        self.assertEqual(ranges[0][1], "2026-08-29T23:59:59.999Z")
        self.assertEqual(ranges[1][0], "2026-08-30T00:00:00.000Z")


if __name__ == "__main__":
    unittest.main()
