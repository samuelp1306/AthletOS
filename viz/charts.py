"""Charts aus whoop_daily fuer die letzten 30 Tage.

Drei PNGs werden nach `outputs/` geschrieben:

    hrv_trend.png              HRV-Verlauf mit 28-Tage-Baseline als horizontale Linie
    acwr.png                   ACWR-Verlauf mit farbigen Zonen (gruen/gelb/rot)
    recovery_vs_readiness.png  Whoop Recovery vs Adjusted Readiness im Vergleich

Alle Werte kommen aus dem Engine-Layer (whoop_daily + readiness.compute pro Tag +
acwr.compute fuer den Verlauf). Kein erfinden, keine Glaettung -- was die DB hat,
landet im Chart.
"""

from __future__ import annotations

import sqlite3
from datetime import date as date_cls
from datetime import timedelta
from pathlib import Path

import pandas as pd
import yaml

from engine.models import acwr, nutrition, readiness

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"

WINDOW_DAYS = 30
HRV_BASELINE_DAYS = 28


def load_config(path: Path = CONFIG_PATH) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_whoop_last(db_path: Path, days: int) -> pd.DataFrame:
    """Whoop-Daily der letzten `days` Tage als DataFrame mit Datums-Index."""
    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(
            "SELECT date, recovery_score, hrv, sleep_hours, sleep_efficiency, strain "
            "FROM whoop_daily ORDER BY date",
            conn,
            parse_dates=["date"],
        )
    return df.tail(days).reset_index(drop=True)


def _load_checkin_map(db_path: Path) -> dict[str, dict]:
    """{date_str: {readiness, reason}} -- leer wenn Tabelle fehlt."""
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_checkin'"
        )
        if cur.fetchone() is None:
            return {}
        cur = conn.execute("SELECT date, readiness, reason FROM daily_checkin")
        return {d: {"readiness": r, "reason": rs} for d, r, rs in cur.fetchall()}


def _load_yazio_map(db_path: Path) -> dict[str, dict]:
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='yazio_daily'"
        )
        if cur.fetchone() is None:
            return {}
        cur = conn.execute("SELECT date, calories, protein, carbs FROM yazio_daily")
        return {
            d: {"calories": c, "protein": p, "carbs": cb}
            for d, c, p, cb in cur.fetchall()
        }


def _compute_adjusted_readiness(
    whoop_df: pd.DataFrame, config: dict, db_path: Path
) -> pd.Series:
    """Pro Zeile von whoop_df den adjusted_readiness berechnen."""
    checkin_map = _load_checkin_map(db_path)
    yazio_map = _load_yazio_map(db_path)

    weight_kg = float(config["athlete"]["weight_kg"])
    protein_target_g = float(config["nutrition"]["protein_target_per_kg"]) * weight_kg
    tdee = float(config["nutrition"]["tdee"])

    out: list[int | None] = []
    for _, row in whoop_df.iterrows():
        date_str = row["date"].strftime("%Y-%m-%d")
        yazio = yazio_map.get(date_str)
        checkin = checkin_map.get(date_str)

        nut = nutrition.compute(
            {
                "calories": yazio.get("calories") if yazio else None,
                "protein": yazio.get("protein") if yazio else None,
                "carbs": yazio.get("carbs") if yazio else None,
                "tdee": tdee,
                "protein_target_g": protein_target_g,
            },
            config,
        )

        try:
            r = readiness.compute(
                {
                    "recovery_score": row["recovery_score"],
                    "deficit_detected": nut["deficit_detected"],
                    "checkin": checkin["readiness"] if checkin else None,
                    "sleep_efficiency": row["sleep_efficiency"],
                    "sleep_hours": row["sleep_hours"],
                },
                config,
            )
            out.append(r["adjusted_readiness"])
        except ValueError:
            # recovery_score fehlt -> kein adjusted_readiness
            out.append(None)

    return pd.Series(out, index=whoop_df.index, dtype="Int64")


def _setup_axes(ax, title: str, ylabel: str) -> None:
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.3)
    ax.tick_params(axis="x", rotation=45)


def chart_hrv_trend(whoop_df: pd.DataFrame, output_path: Path) -> Path:
    """HRV-Verlauf mit 28-Tage-Baseline als horizontale Linie."""
    import matplotlib.pyplot as plt

    baseline_window = whoop_df.tail(HRV_BASELINE_DAYS)
    baseline = baseline_window["hrv"].mean(skipna=True)

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(
        whoop_df["date"],
        whoop_df["hrv"],
        marker="o",
        linewidth=1.5,
        markersize=4,
        color="#1f77b4",
        label="HRV (ms)",
    )
    if pd.notna(baseline):
        ax.axhline(
            baseline,
            color="#888",
            linestyle="--",
            linewidth=1.2,
            label=f"28-Tage-Baseline ({baseline:.1f} ms)",
        )
    _setup_axes(ax, "HRV-Trend (letzte 30 Tage)", "HRV (ms)")
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(output_path, dpi=120)
    plt.close(fig)
    return output_path


def chart_acwr(
    acwr_df: pd.DataFrame, config: dict, output_path: Path
) -> Path:
    """ACWR-Verlauf mit farbigen Zonen.

    Zonen-Faerbung als horizontale Bands ueber den gesamten Plot:
        gruen   detraining_threshold .. spike_threshold   (optimal)
        gelb    0 .. detraining_threshold                 (detraining)
        rot     spike_threshold .. oberes Y-Limit         (spike)
    """
    import matplotlib.pyplot as plt

    spike = float(config["acwr"]["spike_threshold"])
    detraining = float(config["acwr"]["detraining_threshold"])

    fig, ax = plt.subplots(figsize=(11, 5))

    # Y-Range so waehlen, dass die Bands sinnvoll greifen
    y_min = min(0.5, float(acwr_df["acwr"].min(skipna=True) or 0.5) - 0.1)
    y_max = max(1.6, float(acwr_df["acwr"].max(skipna=True) or 1.6) + 0.1)
    x_min, x_max = acwr_df["date"].min(), acwr_df["date"].max()

    # Reihenfolge: erst Bands (untenliegend), dann Linie drueber
    ax.axhspan(detraining, spike, color="#a6d8a6", alpha=0.35, label="optimal")
    ax.axhspan(y_min, detraining, color="#fde58a", alpha=0.35, label="detraining")
    ax.axhspan(spike, y_max, color="#f5a3a3", alpha=0.35, label="spike")

    ax.plot(
        acwr_df["date"],
        acwr_df["acwr"],
        marker="o",
        linewidth=1.8,
        markersize=4,
        color="#222",
        label="ACWR",
    )
    ax.axhline(1.0, color="#444", linestyle=":", linewidth=0.8)

    ax.set_xlim(x_min, x_max)
    ax.set_ylim(y_min, y_max)
    _setup_axes(ax, "ACWR-Verlauf (letzte 30 Tage)", "ACWR")
    ax.legend(loc="best", ncol=4)
    fig.tight_layout()
    fig.savefig(output_path, dpi=120)
    plt.close(fig)
    return output_path


def chart_recovery_vs_readiness(
    df: pd.DataFrame, output_path: Path
) -> Path:
    """Whoop Recovery und Adjusted Readiness nebeneinander (gruppierte Balken).

    `df` enthaelt Spalten: date, recovery_score, adjusted_readiness.
    """
    import matplotlib.pyplot as plt
    import numpy as np

    n = len(df)
    x = np.arange(n)
    width = 0.4

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.bar(
        x - width / 2,
        df["recovery_score"].astype(float),
        width,
        color="#86b6f6",
        label="Whoop Recovery",
    )
    ax.bar(
        x + width / 2,
        df["adjusted_readiness"].astype(float),
        width,
        color="#1f4f8a",
        label="Adjusted Readiness",
    )

    ax.set_xticks(x)
    ax.set_xticklabels([d.strftime("%m-%d") for d in df["date"]], rotation=45)
    ax.set_ylim(0, 100)
    _setup_axes(ax, "Whoop Recovery vs Adjusted Readiness (letzte 30 Tage)", "Score (0-100)")
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(output_path, dpi=120)
    plt.close(fig)
    return output_path


def render_all(config: dict | None = None) -> list[Path]:
    """Erzeugt alle drei Charts. Returns: Liste der geschriebenen Pfade."""
    try:
        import matplotlib  # noqa: F401  -- frueh fehlschlagen mit klarer Message
    except ImportError as e:
        raise RuntimeError(
            "matplotlib nicht installiert. Installiere mit: pip install matplotlib"
        ) from e

    cfg = config or load_config()
    db_path = PROJECT_ROOT / cfg["paths"]["database"]
    out_dir = PROJECT_ROOT / cfg["paths"]["outputs"]
    out_dir.mkdir(parents=True, exist_ok=True)

    whoop = _load_whoop_last(db_path, WINDOW_DAYS)
    if whoop.empty:
        raise RuntimeError("whoop_daily ist leer -- erst Ingest laufen lassen.")

    # ACWR fuer denselben 30-Tage-Window picken (compute liefert den vollen Verlauf).
    acwr_all = acwr.compute(db_path, cfg)
    acwr_all["date"] = pd.to_datetime(acwr_all["date"])
    acwr_window = acwr_all[acwr_all["date"].isin(whoop["date"])].reset_index(drop=True)

    whoop["adjusted_readiness"] = _compute_adjusted_readiness(whoop, cfg, db_path)

    paths = [
        chart_hrv_trend(whoop, out_dir / "hrv_trend.png"),
        chart_acwr(acwr_window, cfg, out_dir / "acwr.png"),
        chart_recovery_vs_readiness(whoop, out_dir / "recovery_vs_readiness.png"),
    ]
    return paths


if __name__ == "__main__":
    written = render_all()
    print("Geschriebene Charts:")
    for p in written:
        print(f"  {p}")
