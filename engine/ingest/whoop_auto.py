"""Auto-ingest the latest Whoop export from the Downloads folder.

Sucht im Downloads-Ordner nach Dateien `my_whoop_data_*.zip`, nimmt die
juengste (nach mtime), entpackt `physiologische_zyklen.csv` nach
`data/raw/` und ruft `engine.ingest.whoop.ingest()` auf.

Idempotent: ein Marker `data/raw/.whoop_auto_state.json` haelt fest, welche
ZIP zuletzt verarbeitet wurde (Name, mtime, Groesse). Bei unveraenderter
neuester ZIP wird nichts getan.

Fail-safe: jeder Fehler wird gemeldet, aber das Script terminiert mit Exit 0,
damit ein Aufruf aus `start.bat` den App-Start niemals blockiert.

Aufruf:
    python -m engine.ingest.whoop_auto
    python -m engine.ingest.whoop_auto --downloads "D:/Andere/Downloads"
    python -m engine.ingest.whoop_auto --force

Env override:
    WHOOP_DOWNLOADS_DIR=...   ueberschreibt den Default
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DOWNLOADS = Path(r"C:\Users\samue\Downloads")
ZIP_PATTERN = "my_whoop_data_*.zip"
CSV_INSIDE_ZIP = "physiologische_zyklen.csv"
STATE_FILENAME = ".whoop_auto_state.json"

# Prefix fuer alle Logzeilen -- macht den Aufruf aus start.bat leicht erkennbar.
LOG = "[whoop-auto]"


def _log(msg: str) -> None:
    print(f"{LOG} {msg}", flush=True)


def find_latest_zip(downloads_dir: Path) -> Path | None:
    """Juengste passende ZIP nach mtime; None wenn keine vorhanden."""
    if not downloads_dir.is_dir():
        _log(f"Downloads-Ordner nicht gefunden: {downloads_dir}")
        return None
    candidates = list(downloads_dir.glob(ZIP_PATTERN))
    if not candidates:
        return None
    # mtime statt Dateiname -- Browser-Suffix " (1).zip" macht Namens-Sort unzuverlaessig.
    return max(candidates, key=lambda p: p.stat().st_mtime)


def fingerprint(path: Path) -> dict:
    """Stabile Identitaet einer Datei: Name + mtime + Groesse."""
    st = path.stat()
    return {"name": path.name, "mtime": st.st_mtime, "size": st.st_size}


def read_state(state_path: Path) -> dict | None:
    if not state_path.exists():
        return None
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_state(state_path: Path, fp: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(fp, indent=2), encoding="utf-8")


def extract_csv(zip_path: Path, raw_dir: Path) -> Path:
    """Extrahiert physiologische_zyklen.csv aus der ZIP nach raw_dir.

    Sucht die CSV case-insensitiv und unabhaengig von einem evtl. Unterordner
    in der ZIP. Wirft FileNotFoundError, wenn die CSV nicht enthalten ist.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    target = raw_dir / CSV_INSIDE_ZIP

    with zipfile.ZipFile(zip_path) as zf:
        match = None
        for name in zf.namelist():
            # name kann "subdir/physiologische_zyklen.csv" sein
            if Path(name).name.lower() == CSV_INSIDE_ZIP.lower():
                match = name
                break
        if match is None:
            raise FileNotFoundError(
                f"{CSV_INSIDE_ZIP} nicht in {zip_path.name} gefunden. "
                f"Enthalten: {zf.namelist()[:5]}..."
            )
        with zf.open(match) as src, target.open("wb") as dst:
            shutil.copyfileobj(src, dst)
    return target


def archive_zip(zip_path: Path, raw_dir: Path) -> Path:
    """Kopiert die ZIP nach data/raw/ (fuer Nachvollziehbarkeit)."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    archived = raw_dir / zip_path.name
    if not archived.exists() or archived.stat().st_mtime < zip_path.stat().st_mtime:
        shutil.copy2(zip_path, archived)
    return archived


def run(downloads_dir: Path, force: bool = False) -> int:
    """Hauptablauf. Returncode wie ueblich (0 = ok), wird vom main() geschluckt."""
    # whoop.ingest erst hier importieren -- so faellt ein Import-Fehler nur dann auf,
    # wenn wir ihn wirklich brauchen, und das Script kann sich vorher sauber beenden.
    try:
        from engine.ingest import whoop  # noqa: WPS433 (late import is intentional)
    except ImportError as e:
        _log(f"Konnte engine.ingest.whoop nicht importieren: {e}")
        return 1

    latest = find_latest_zip(downloads_dir)
    if latest is None:
        _log(f"Keine {ZIP_PATTERN} in {downloads_dir} gefunden -- skip.")
        return 0

    fp = fingerprint(latest)
    raw_dir = PROJECT_ROOT / "data" / "raw"
    state_path = raw_dir / STATE_FILENAME
    prev = read_state(state_path)

    if not force and prev == fp:
        _log(f"{latest.name} bereits importiert -- skip.")
        return 0

    size_mb = fp["size"] / (1024 * 1024)
    _log(f"Neue Whoop-Export erkannt: {latest.name} ({size_mb:.2f} MB)")

    try:
        archived = archive_zip(latest, raw_dir)
        _log(f"ZIP archiviert: {archived.relative_to(PROJECT_ROOT)}")
    except OSError as e:
        _log(f"WARN: ZIP-Archivierung fehlgeschlagen ({e}) -- ingest laeuft trotzdem weiter.")

    try:
        csv_target = extract_csv(latest, raw_dir)
        _log(f"CSV extrahiert: {csv_target.relative_to(PROJECT_ROOT)}")
    except (FileNotFoundError, zipfile.BadZipFile, OSError) as e:
        _log(f"ERR: Extraktion fehlgeschlagen: {e}")
        return 1

    try:
        cfg = whoop.load_config()
        n_up, n_del = whoop.ingest(cfg)
    except Exception as e:  # noqa: BLE001 -- wir wollen wirklich keinen Crash hochbubblen
        _log(f"ERR: Ingest fehlgeschlagen: {e}")
        return 1

    extra = f" (Nap-Only entfernt: {n_del})" if n_del else ""
    _log(f"Ingest fertig: {n_up} Zeilen upserted{extra}.")

    write_state(state_path, fp)
    _log("State-Marker aktualisiert.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Auto-ingest latest Whoop export from Downloads.")
    parser.add_argument(
        "--downloads",
        default=os.environ.get("WHOOP_DOWNLOADS_DIR", str(DEFAULT_DOWNLOADS)),
        help="Pfad zum Downloads-Ordner (Default: %(default)s)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Auch reimportieren, wenn die ZIP unveraendert ist.",
    )
    args = parser.parse_args(argv)

    downloads_dir = Path(args.downloads)
    try:
        rc = run(downloads_dir, force=args.force)
    except Exception as e:  # noqa: BLE001 -- letzte Verteidigungslinie fuer start.bat
        _log(f"ERR (uncaught): {type(e).__name__}: {e}")
        rc = 1

    # start.bat soll NIE wegen Whoop-Auto-Ingest fehlschlagen.
    # Wir loggen den internen Returncode, geben aber 0 nach aussen zurueck.
    if rc != 0:
        _log(f"Beendet mit internem rc={rc}, gebe trotzdem 0 zurueck (non-blocking).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
