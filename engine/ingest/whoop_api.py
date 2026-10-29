"""Whoop API -> SQLite ingest (Alternative zum CSV-Export).

Holt die Tageszyklen direkt von der (inoffiziellen) Web-App-API
`api.prod.whoop.com` und schreibt sie ueber `engine.ingest.whoop.upsert()` in
dieselbe Tabelle `whoop_daily` wie der CSV-Import. Kein manueller ZIP-Export
mehr noetig.

Die Endpoints sind nicht Teil der offiziellen Developer-API und koennen sich
ohne Vorwarnung aendern. Referenz: WHOOP_API_GUIDE.md (Network-Analyse der
Web-App). Nur stdlib-HTTP (urllib), keine neue Abhaengigkeit.

Authentifizierung (in `.env`, gitignored):
    WHOOP_REFRESH_TOKEN=...   aus app.whoop.com -> DevTools -> Local Storage
                              -> `security.refreshToken` (bevorzugt)
    oder
    WHOOP_EMAIL=... / WHOOP_PASSWORD=...   Login per Passwort-Grant
    WHOOP_USER_ID=...         optional, falls die Token-Antwort keine ID enthaelt

Nach dem ersten erfolgreichen Login liegen Access-/Refresh-Token in der
Token-Datei (Default `data/raw/.whoop_api_token.json`, gitignored) und werden
bei jedem Lauf erneuert -- die .env-Werte braucht es danach nur noch, wenn der
Refresh-Token ungueltig wird.

Mapping API -> DB-Spalte (identisch zur CSV-Semantik):
    Datum                         -> lokales Datum des Zyklus-Endes
                                     (offener Zyklus: lokales Datum des Aufwachens)
    recovery.recovery_score       -> recovery_score
    recovery.hrv_rmssd (s)        -> hrv               (x 1000 -> ms)
    recovery.resting_heart_rate   -> rhr
    Hauptschlaf quality_duration  -> sleep_hours       (ms -> h)
    Hauptschlaf in_sleep_efficiency -> sleep_efficiency (x 100 -> %)
    Hauptschlaf respiratory_rate  -> respiratory_rate
    recovery.skin_temp_celsius    -> skin_temp
    cycle.scaled_strain           -> strain
    cycle.day_kilojoules          -> calories_burned   (kJ / 4.184 -> kcal)

Aufruf:
    python -m engine.ingest.whoop_api               # letzte lookback_days Tage
    python -m engine.ingest.whoop_api --days 180    # Backfill
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from engine.ingest import whoop

PROJECT_ROOT = Path(__file__).resolve().parents[2]

BASE_URL = "https://api.prod.whoop.com"
TOKEN_PATH = "/api-server/oauth/token"
CYCLES_PATH = "/core-details-bff/v0/cycles/details"
API_VERSION = "7"
KJ_PER_KCAL = 4.184

LOG = "[whoop-api]"

DB_COLUMNS = [
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


class WhoopAuthError(RuntimeError):
    """Kein gueltiger Token und keine Zugangsdaten zum Neu-Login."""


def _log(msg: str) -> None:
    print(f"{LOG} {msg}", flush=True)


def _load_dotenv() -> None:
    """`.env` aus dem Projekt-Root laden (python-dotenv optional, wie api/server.py)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=False)


# ── Parsing (pure, ohne Netzwerk) ─────────────────────────────

_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|[+-]\d{2}:?\d{2})?")


def parse_range(range_str: str | None) -> tuple[datetime | None, datetime | None]:
    """PostgreSQL-Range `['start','end')` -> (start, end) als aware UTC-datetimes.

    Offene Ranges (laufender Zyklus, `['start',)`) liefern end=None.
    """
    if not range_str:
        return None, None
    inner = range_str.strip()[1:-1]
    parts = [p.strip().strip("'\"") for p in inner.split(",", 1)]
    out: list[datetime | None] = []
    for p in parts + [""] * (2 - len(parts)):
        m = _TS_RE.search(p)
        out.append(_parse_ts(m.group(0)) if m else None)
    return out[0], out[1]


def _parse_ts(ts: str) -> datetime:
    ts = ts.replace("Z", "+00:00")
    # "+0000" -> "+00:00" (fromisoformat < 3.11 kennt die Kurzform nicht)
    ts = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", ts)
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_offset(offset: str | None) -> timezone:
    """Whoop-Offset ("-0800", "+02:00") -> timezone. Fehlend -> UTC."""
    if not offset:
        return timezone.utc
    m = re.fullmatch(r"([+-])(\d{2}):?(\d{2})", offset.strip())
    if not m:
        return timezone.utc
    sign = -1 if m.group(1) == "-" else 1
    return timezone(sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3))))


def _main_sleep(sleeps: list[dict]) -> dict | None:
    """Laengster Nicht-Nap-Schlaf; nur Naps vorhanden -> laengster Nap.

    So landet bei Nap-Only-Zyklen die kurze Nap-Dauer in sleep_hours und der
    min_sleep_minutes-Filter verwirft den Tag -- exakt wie beim CSV-Import.
    """
    if not sleeps:
        return None
    pool = [s for s in sleeps if not s.get("is_nap")] or sleeps
    return max(pool, key=lambda s: s.get("quality_duration") or 0)


def _cycle_date(record: dict) -> str | None:
    """Lokales Datum, unter dem ein Zyklus in whoop_daily landet.

    Abgeschlossener Zyklus: Datum des Zyklus-Endes in Zyklus-Zeitzone (wie
    `Endzeit des Zyklus` im CSV). Laufender Zyklus (heute): Datum des
    Aufwachens aus dem Hauptschlaf -- der CSV-Export verwirft diesen Zyklus,
    die API liefert die heutige Recovery aber schon morgens.
    """
    cycle = record.get("cycle") or {}
    tz = parse_offset(cycle.get("timezone_offset"))
    _, end = parse_range(cycle.get("during"))
    if end is not None:
        return end.astimezone(tz).date().isoformat()
    sleep = _main_sleep(record.get("sleeps") or [])
    if sleep is None:
        return None
    _, wake = parse_range(sleep.get("during"))
    if wake is None:
        return None
    return wake.astimezone(tz).date().isoformat()


def _scale(value: float | None, factor: float) -> float | None:
    return None if value is None else value * factor


def record_to_row(record: dict) -> dict | None:
    """Ein `cycles/details`-Record -> dict mit DB-Spalten (+ `_start`, `_sleep_min`).

    None, wenn sich kein Datum bestimmen laesst.
    """
    day = _cycle_date(record)
    if day is None:
        return None
    cycle = record.get("cycle") or {}
    recovery = record.get("recovery") or {}
    sleep = _main_sleep(record.get("sleeps") or []) or {}
    start, _ = parse_range(cycle.get("during"))

    sleep_ms = sleep.get("quality_duration")
    kj = cycle.get("day_kilojoules")
    return {
        "date": day,
        "recovery_score": recovery.get("recovery_score"),
        "hrv": _scale(recovery.get("hrv_rmssd"), 1000.0),
        "rhr": recovery.get("resting_heart_rate"),
        "sleep_hours": _scale(sleep_ms, 1 / 3_600_000),
        "sleep_efficiency": _scale(sleep.get("in_sleep_efficiency"), 100.0),
        "respiratory_rate": sleep.get("respiratory_rate"),
        "skin_temp": recovery.get("skin_temp_celsius"),
        "strain": cycle.get("scaled_strain"),
        "calories_burned": None if kj is None else kj / KJ_PER_KCAL,
        "_start": start,
        "_sleep_min": None if sleep_ms is None else sleep_ms / 60_000,
    }


def transform(
    records: list[dict], min_sleep_minutes: float = 180.0
) -> tuple[pd.DataFrame, list[str]]:
    """API-Records -> (kept_df, dropped_dates), gleiche Semantik wie whoop.transform().

    - Zyklen mit Hauptschlaf < min_sleep_minutes (oder ohne Schlaf) werden verworfen.
    - Mehrere Zyklen pro Datum: der spaeter beginnende gewinnt.
    """
    rows = [r for r in (record_to_row(rec) for rec in records) if r is not None]
    if not rows:
        return pd.DataFrame(columns=DB_COLUMNS), []

    df = pd.DataFrame(rows)
    df = df.sort_values("_start", na_position="first", kind="stable")
    keep_mask = pd.to_numeric(df["_sleep_min"], errors="coerce") >= min_sleep_minutes
    kept = df[keep_mask]
    dropped_dates = sorted(set(df.loc[~keep_mask, "date"]) - set(kept["date"]))

    out = kept.drop_duplicates(subset=["date"], keep="last")[DB_COLUMNS]
    out = out.sort_values("date").reset_index(drop=True)
    return out, dropped_dates


def chunk_ranges(
    days: int, chunk_days: int, today: date
) -> list[tuple[str, str]]:
    """Zeitraum der letzten `days` Tage -> Liste von (startTime, endTime) in UTC.

    Die API schneidet Tagesgrenzen in Nutzer-Lokalzeit; wir polstern deshalb
    den Gesamtzeitraum um je einen Tag und bestimmen das Datum selbst aus den
    Records (`_cycle_date`). Ueberlappungen an Chunkgrenzen sind harmlos --
    der Upsert ist idempotent und transform() dedupliziert.
    """
    start = datetime.combine(today - timedelta(days=days), datetime.min.time(), timezone.utc)
    end = datetime.combine(today + timedelta(days=2), datetime.min.time(), timezone.utc)
    ranges = []
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=chunk_days), end)
        last = nxt - timedelta(seconds=1)
        ranges.append((
            cur.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            last.strftime("%Y-%m-%dT%H:%M:%S.999Z"),
        ))
        cur = nxt
    return ranges


# ── HTTP / Auth ───────────────────────────────────────────────

def _request(method: str, path: str, *, params: dict | None = None,
             body: dict | None = None, token: str | None = None,
             timeout: float = 30.0) -> dict:
    url = BASE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        # Die Web-App sendet "bearer" klein -- so beibehalten.
        headers["Authorization"] = f"bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _read_tokens(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_tokens(path: Path, tokens: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tokens, indent=2), encoding="utf-8")


def _store_token_response(resp: dict, prev: dict, path: Path) -> dict:
    user = resp.get("user") or {}
    tokens = {
        "access_token": resp["access_token"],
        # Ohne neuen Refresh-Token in der Antwort den alten behalten.
        "refresh_token": resp.get("refresh_token") or prev.get("refresh_token"),
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(seconds=int(resp.get("expires_in", 3600)))
        ).isoformat(),
        "user_id": user.get("id") or prev.get("user_id"),
    }
    _write_tokens(path, tokens)
    return tokens


def get_session(token_file: Path) -> tuple[str, int]:
    """Gueltigen Access-Token + User-ID besorgen (Cache -> Refresh -> Login).

    Wirft WhoopAuthError, wenn nichts davon klappt.
    """
    tokens = _read_tokens(token_file)
    env_user = os.environ.get("WHOOP_USER_ID")

    expires_at = tokens.get("expires_at")
    if tokens.get("access_token") and expires_at:
        if datetime.fromisoformat(expires_at) - timedelta(minutes=5) > datetime.now(timezone.utc):
            user_id = tokens.get("user_id") or env_user
            if user_id:
                return tokens["access_token"], int(user_id)

    errors: list[str] = []
    refresh_candidates = [tokens.get("refresh_token"), os.environ.get("WHOOP_REFRESH_TOKEN")]
    for refresh in dict.fromkeys(r for r in refresh_candidates if r):
        try:
            resp = _request("POST", TOKEN_PATH, body={
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                # Neuen Refresh-Token ausstellen lassen, damit die Kette nie abreisst.
                "issueRefresh": True,
            })
            tokens = _store_token_response(resp, {**tokens, "refresh_token": refresh}, token_file)
            break
        except urllib.error.HTTPError as e:
            errors.append(f"Refresh fehlgeschlagen (HTTP {e.code})")
    else:
        email, password = os.environ.get("WHOOP_EMAIL"), os.environ.get("WHOOP_PASSWORD")
        if not (email and password):
            raise WhoopAuthError(
                "; ".join(errors + [
                    "Keine Whoop-Zugangsdaten. WHOOP_REFRESH_TOKEN oder "
                    "WHOOP_EMAIL + WHOOP_PASSWORD in .env setzen."
                ])
            )
        try:
            resp = _request("POST", TOKEN_PATH, body={
                "grant_type": "password",
                "username": email,
                "password": password,
                "issueRefresh": True,
            })
        except urllib.error.HTTPError as e:
            raise WhoopAuthError(f"Login fehlgeschlagen (HTTP {e.code})") from e
        tokens = _store_token_response(resp, tokens, token_file)

    user_id = tokens.get("user_id") or env_user
    if not user_id:
        raise WhoopAuthError("User-ID unbekannt -- WHOOP_USER_ID in .env setzen.")
    return tokens["access_token"], int(user_id)


def fetch_cycles(token: str, user_id: int, days: int, chunk_days: int,
                 today: date | None = None) -> list[dict]:
    """Alle `cycles/details`-Records der letzten `days` Tage (in Chunks)."""
    records: list[dict] = []
    for start, end in chunk_ranges(days, chunk_days, today or date.today()):
        resp = _request("GET", CYCLES_PATH, token=token, params={
            "apiVersion": API_VERSION,
            "id": user_id,
            "startTime": start,
            "endTime": end,
            "limit": chunk_days + 2,
        })
        records.extend(resp.get("records") or [])
    return records


# ── Orchestrierung ────────────────────────────────────────────

def ingest(config: dict | None = None, days: int | None = None) -> tuple[int, int]:
    """Whoop-API -> whoop_daily. Returns (n_upserted, n_deleted)."""
    cfg = config or whoop.load_config()
    api_cfg = cfg.get("ingest", {}).get("whoop_api", {})
    min_sleep = float(cfg.get("ingest", {}).get("whoop", {}).get("min_sleep_minutes", 180))
    db_path = PROJECT_ROOT / cfg["paths"]["database"]
    token_file = PROJECT_ROOT / api_cfg.get("token_file", "data/raw/.whoop_api_token.json")
    days = days or int(api_cfg.get("lookback_days", 30))
    chunk_days = int(api_cfg.get("chunk_days", 30))

    token, user_id = get_session(token_file)
    records = fetch_cycles(token, user_id, days, chunk_days)
    _log(f"{len(records)} Zyklen von der API geladen ({days} Tage).")

    df, dropped_dates = transform(records, min_sleep_minutes=min_sleep)
    if df.empty and not dropped_dates:
        return 0, 0
    return whoop.upsert(df, db_path, dropped_dates=dropped_dates)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Whoop-Daten direkt per API importieren.")
    parser.add_argument("--days", type=int, default=None,
                        help="Lookback in Tagen (Default: config ingest.whoop_api.lookback_days)")
    parser.add_argument("--strict", action="store_true",
                        help="Bei Fehlern Exit 1 statt 0 (Default ist non-blocking fuer start.bat).")
    args = parser.parse_args(argv)

    _load_dotenv()
    try:
        n_up, n_del = ingest(days=args.days)
    except WhoopAuthError as e:
        _log(f"Auth: {e}")
        return 1 if args.strict else 0
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        _log(f"Netzwerk/HTTP-Fehler: {e}")
        return 1 if args.strict else 0
    except Exception as e:  # noqa: BLE001 -- start.bat darf nie blockieren
        _log(f"ERR: {type(e).__name__}: {e}")
        return 1 if args.strict else 0

    extra = f" (Nap-Only entfernt: {n_del})" if n_del else ""
    _log(f"Ingest fertig: {n_up} Tage upserted{extra}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
