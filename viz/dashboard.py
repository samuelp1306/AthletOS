"""Performance OS Dashboard (Streamlit).

Lokales Dashboard, das die Layer-1-Werte zusammen mit dem Protocol-Output
und den Trend-Charts anzeigt. AI-Report wird nur auf Knopfdruck generiert,
damit jeder Reload nicht die API anschmeisst.

Start:
    streamlit run viz/dashboard.py
    (oder:  python -m streamlit run viz/dashboard.py )

Dark Theme kommt aus .streamlit/config.toml im Repo.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import date as date_cls
from pathlib import Path

import pandas as pd
import yaml

# --- Pfad-Setup, damit Streamlit das Modul auch ohne Project-Root in sys.path findet ---
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402

from engine.calculate import calculate  # noqa: E402
from engine.models import acwr  # noqa: E402
from engine.models.protocol import DailyData, generate_protocol  # noqa: E402

CONFIG_PATH = PROJECT_ROOT / "config.yaml"

# Mapping training_recommendation -> Banner-Farbe
RECO_COLORS: dict[str, tuple[str, str]] = {
    # (Hintergrund, Akzent)
    "full_intensity": ("#1f6f3a", "#3fbf6a"),
    "reduced": ("#8a6d1f", "#e6c34f"),
    "active_recovery": ("#8a4a1f", "#e6884f"),
    "rest": ("#7a1f1f", "#e64f4f"),
}
RECO_LABELS: dict[str, str] = {
    "full_intensity": "FULL INTENSITY",
    "reduced": "REDUCED",
    "active_recovery": "ACTIVE RECOVERY",
    "rest": "REST",
}


# ============================================================
# CACHED LOADERS
# ============================================================


@st.cache_data(show_spinner=False)
def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@st.cache_data(show_spinner=False)
def get_db_path() -> Path:
    cfg = load_config()
    return PROJECT_ROOT / cfg["paths"]["database"]


@st.cache_data(show_spinner=False)
def available_dates() -> list[str]:
    db_path = get_db_path()
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT date FROM whoop_daily ORDER BY date"
        ).fetchall()
    return [r[0] for r in rows]


@st.cache_data(show_spinner=False)
def load_whoop_window(end_date: str, days: int) -> pd.DataFrame:
    """whoop_daily-Zeilen bis einschliesslich end_date, letzte `days` Tage."""
    db_path = get_db_path()
    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(
            "SELECT date, recovery_score, hrv, rhr, sleep_hours, sleep_efficiency, strain "
            "FROM whoop_daily WHERE date <= ? ORDER BY date",
            conn,
            params=(end_date,),
            parse_dates=["date"],
        )
    return df.tail(days).reset_index(drop=True)


@st.cache_data(show_spinner=False)
def load_acwr_series() -> pd.DataFrame:
    db_path = get_db_path()
    cfg = load_config()
    df = acwr.compute(db_path, cfg)
    df["date"] = pd.to_datetime(df["date"])
    return df


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    )
    return cur.fetchone() is not None


def _fetch_one(conn: sqlite3.Connection, table: str, date: str) -> dict | None:
    if not _table_exists(conn, table):
        return None
    conn.row_factory = sqlite3.Row
    cur = conn.execute(f"SELECT * FROM {table} WHERE date = ?", (date,))
    row = cur.fetchone()
    return dict(row) if row else None


def _fetch_rpe_yesterday(conn: sqlite3.Connection, date: str) -> float | None:
    if not _table_exists(conn, "training_log"):
        return None
    cur = conn.execute(
        "SELECT MAX(rpe) FROM training_log WHERE date = date(?, '-1 day')",
        (date,),
    )
    row = cur.fetchone()
    return float(row[0]) if row and row[0] is not None else None


def build_daily_data(date: str, layer1: dict, cfg: dict) -> DailyData:
    """Fuellt das DailyData-Protocol fuer protocol.generate_protocol().

    Pflichtfelder aus dem Layer-1-Dict + zusaetzliche Werte direkt aus
    whoop_daily / yazio_daily / training_log + Baselines aus dem 28-Tage-Fenster.
    """
    db_path = get_db_path()
    weight_kg = float(cfg["athlete"]["weight_kg"])
    protein_target_g = float(cfg["nutrition"]["protein_target_per_kg"]) * weight_kg

    with sqlite3.connect(db_path) as conn:
        whoop = _fetch_one(conn, "whoop_daily", date) or {}
        yazio = _fetch_one(conn, "yazio_daily", date) or {}
        rpe_yesterday = _fetch_rpe_yesterday(conn, date)

    # Baselines: 28-Tage-Mittel BIS einschliesslich `date`.
    window = load_whoop_window(date, 28)
    hrv_baseline = float(window["hrv"].mean(skipna=True)) if not window.empty else float(whoop.get("hrv") or 0)
    rhr_baseline = float(window["rhr"].mean(skipna=True)) if not window.empty else float(whoop.get("rhr") or 0)

    # Discrepancy fuer Dashboard-Logik: System (adjusted) vs Whoop.
    # (Achtung: protocol.py interpretiert das Feld als Whoop-vs-Subjective laut
    # CLAUDE.md — hier verwenden wir die Dashboard-Variante. Sign-Konvention:
    # positiv = Whoop optimistischer als System.)
    whoop_recovery = int(layer1["whoop_recovery"]) if layer1.get("whoop_recovery") is not None else 0
    adjusted = int(layer1["adjusted_readiness"])
    discrepancy = whoop_recovery - adjusted

    return DailyData(
        adjusted_readiness=adjusted,
        whoop_recovery=whoop_recovery,
        discrepancy=discrepancy,
        acwr=float(layer1["acwr"]) if layer1.get("acwr") is not None else 1.0,
        acwr_zone=layer1.get("acwr_zone") or "optimal",
        checkin=layer1.get("checkin") or "yes",
        checkin_reason=layer1.get("checkin_reason") or "none",
        rpe_yesterday=rpe_yesterday,
        hrv=float(whoop.get("hrv") or 0),
        hrv_baseline=hrv_baseline if hrv_baseline else 1.0,
        rhr=float(whoop.get("rhr") or 0),
        rhr_baseline=rhr_baseline if rhr_baseline else 1.0,
        sleep_hours=float(whoop.get("sleep_hours") or 0),
        sleep_efficiency=float(whoop.get("sleep_efficiency") or 0),
        calories=float(yazio["calories"]) if yazio.get("calories") is not None else None,
        tdee=float(cfg["nutrition"]["tdee"]),
        protein_g=float(yazio["protein"]) if yazio.get("protein") is not None else None,
        protein_target_g=protein_target_g,
        carbs_g=float(yazio["carbs"]) if yazio.get("carbs") is not None else None,
        deficit_detected=bool(layer1.get("deficit_detected", False)),
        position=cfg["athlete"].get("position", "FB").split()[0],  # "LB / LM" -> "LB"
    )


# ============================================================
# RENDER-HELFER
# ============================================================


def _card(label: str, value: str, sub: str | None = None, accent: str = "#3b82f6") -> str:
    """HTML-Karte fuer die Readiness-Row."""
    sub_html = f'<div style="color:#9aa3b1;font-size:0.85rem;margin-top:0.25rem;">{sub}</div>' if sub else ""
    return f"""
    <div style="
        background:#1a1f2e;
        border-left:4px solid {accent};
        border-radius:8px;
        padding:1rem 1.25rem;
        height:100%;
    ">
        <div style="color:#9aa3b1;font-size:0.78rem;text-transform:uppercase;letter-spacing:0.06em;">{label}</div>
        <div style="color:#f0f0f0;font-size:1.85rem;font-weight:600;margin-top:0.2rem;line-height:1.1;">{value}</div>
        {sub_html}
    </div>
    """


def _badge(text: str, bg: str, fg: str = "#fff") -> str:
    return (
        f'<span style="display:inline-block;background:{bg};color:{fg};'
        f'padding:0.25rem 0.55rem;border-radius:6px;margin:0.15rem 0.25rem 0.15rem 0;'
        f'font-size:0.82rem;">{text}</span>'
    )


def render_protocol_banner(protocol) -> None:
    bg, accent = RECO_COLORS.get(protocol.training_recommendation, ("#444", "#888"))
    label = RECO_LABELS.get(protocol.training_recommendation, protocol.training_recommendation.upper())

    st.markdown(
        f"""
        <div style="
            background:{bg};
            border-left:8px solid {accent};
            border-radius:10px;
            padding:1.4rem 1.6rem;
            margin-bottom:0.8rem;
        ">
            <div style="color:#fff;opacity:0.85;font-size:0.85rem;letter-spacing:0.1em;">TRAINING RECOMMENDATION</div>
            <div style="color:#fff;font-size:2.2rem;font-weight:700;margin-top:0.2rem;line-height:1;">
                {label}
            </div>
            <div style="color:#fff;opacity:0.85;font-size:0.85rem;margin-top:0.5rem;">
                Confidence: {protocol.confidence}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if protocol.recommendation_reasons:
        st.markdown("**Gruende:**")
        for r in protocol.recommendation_reasons:
            st.markdown(f"- {r}")

    badges_html = ""
    for flag in protocol.flags:
        badges_html += _badge(flag, bg="#7a1f1f")
    for flag in protocol.nutrition_flags:
        badges_html += _badge(flag, bg="#8a4a1f")
    for flag in protocol.bloodwork_flags:
        badges_html += _badge(flag, bg="#4a1f7a")
    if badges_html:
        st.markdown(f'<div style="margin-top:0.6rem;">{badges_html}</div>', unsafe_allow_html=True)


def render_discrepancy_card(whoop: int, adjusted: int) -> None:
    delta = whoop - adjusted
    abs_delta = abs(delta)
    if abs_delta < 10:
        bg, accent, label = "#1f6f3a", "#3fbf6a", "OK"
    elif abs_delta <= 20:
        bg, accent, label = "#8a6d1f", "#e6c34f", "WATCH"
    else:
        bg, accent, label = "#7a1f1f", "#e64f4f", "ALERT"

    direction = "" if delta == 0 else (
        "Whoop ueberschaetzt." if delta > 0 else "Whoop unterschaetzt."
    )

    st.markdown(
        f"""
        <div style="
            background:{bg};
            border-left:8px solid {accent};
            border-radius:10px;
            padding:1.2rem 1.4rem;
            margin:0.4rem 0 1rem 0;
        ">
            <div style="color:#fff;opacity:0.85;font-size:0.8rem;letter-spacing:0.1em;">
                DISKREPANZ · {label}
            </div>
            <div style="color:#fff;font-size:1.6rem;font-weight:600;margin-top:0.3rem;line-height:1.3;">
                Whoop sagt <strong>{whoop}%</strong>. System sagt <strong>{adjusted}%</strong>.
                <span style="opacity:0.9;">&nbsp;&nbsp;&Delta; {delta:+d}</span>
            </div>
            <div style="color:#fff;opacity:0.85;font-size:0.9rem;margin-top:0.3rem;">{direction}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_readiness_row(layer1: dict, whoop_row: dict, hrv_baseline: float) -> None:
    col1, col2, col3, col4 = st.columns(4)

    # Adjusted Readiness
    adj = int(layer1["adjusted_readiness"])
    corrs = layer1.get("corrections_applied") or []
    corr_text = ", ".join(corrs) if corrs else "keine Korrekturen"
    with col1:
        st.markdown(_card("ADJUSTED READINESS", f"{adj}", sub=corr_text), unsafe_allow_html=True)

    # ACWR
    acwr_val = layer1.get("acwr")
    zone = layer1.get("acwr_zone") or "n/a"
    zone_color = {"optimal": "#3fbf6a", "spike": "#e64f4f", "detraining": "#e6c34f"}.get(zone, "#888")
    acwr_text = f"{acwr_val:.2f}" if acwr_val is not None else "—"
    with col2:
        st.markdown(_card("ACWR", acwr_text, sub=f"Zone: {zone}", accent=zone_color), unsafe_allow_html=True)

    # HRV vs Baseline
    hrv = whoop_row.get("hrv")
    if hrv is not None and hrv_baseline:
        delta_pct = ((hrv - hrv_baseline) / hrv_baseline) * 100
        hrv_text = f"{hrv:.0f} ms"
        hrv_sub = f"Baseline {hrv_baseline:.0f} ms · {delta_pct:+.1f}%"
        hrv_accent = "#3fbf6a" if delta_pct >= -10 else "#e64f4f"
    else:
        hrv_text, hrv_sub, hrv_accent = "—", "keine Daten", "#888"
    with col3:
        st.markdown(_card("HRV", hrv_text, sub=hrv_sub, accent=hrv_accent), unsafe_allow_html=True)

    # Sleep
    h = whoop_row.get("sleep_hours")
    e = whoop_row.get("sleep_efficiency")
    if h is not None and e is not None:
        sleep_text = f"{h:.1f} h"
        sleep_sub = f"Effizienz {e:.0f}%"
        sleep_accent = "#3fbf6a" if (h >= 7.5 and e >= 90) else ("#e64f4f" if (h < 6 or e < 75) else "#3b82f6")
    else:
        sleep_text, sleep_sub, sleep_accent = "—", "keine Daten", "#888"
    with col4:
        st.markdown(_card("SLEEP", sleep_text, sub=sleep_sub, accent=sleep_accent), unsafe_allow_html=True)


def render_acwr_chart(acwr_df: pd.DataFrame, cfg: dict) -> None:
    import matplotlib.pyplot as plt

    spike = float(cfg["acwr"]["spike_threshold"])
    detraining = float(cfg["acwr"]["detraining_threshold"])

    fig, ax = plt.subplots(figsize=(11, 4))
    fig.patch.set_facecolor("#1a1f2e")
    ax.set_facecolor("#1a1f2e")

    y_min = min(0.5, float(acwr_df["acwr"].min(skipna=True) or 0.5) - 0.1)
    y_max = max(1.6, float(acwr_df["acwr"].max(skipna=True) or 1.6) + 0.1)

    ax.axhspan(detraining, spike, color="#3fbf6a", alpha=0.18)
    ax.axhspan(y_min, detraining, color="#e6c34f", alpha=0.18)
    ax.axhspan(spike, y_max, color="#e64f4f", alpha=0.18)
    ax.plot(acwr_df["date"], acwr_df["acwr"], marker="o", color="#e6e6e6", linewidth=1.6, markersize=4)
    ax.axhline(1.0, color="#888", linestyle=":", linewidth=0.8)

    ax.set_ylim(y_min, y_max)
    ax.set_title("ACWR — letzte 30 Tage", color="#e6e6e6")
    ax.tick_params(colors="#9aa3b1")
    for spine in ax.spines.values():
        spine.set_color("#2a2f3e")
    ax.grid(True, alpha=0.15, color="#9aa3b1")
    fig.autofmt_xdate()
    fig.tight_layout()
    st.pyplot(fig)


def render_hrv_chart(whoop_df: pd.DataFrame) -> None:
    import matplotlib.pyplot as plt

    baseline = whoop_df.tail(28)["hrv"].mean(skipna=True)

    fig, ax = plt.subplots(figsize=(11, 4))
    fig.patch.set_facecolor("#1a1f2e")
    ax.set_facecolor("#1a1f2e")

    ax.plot(whoop_df["date"], whoop_df["hrv"], marker="o", color="#3b82f6", linewidth=1.6, markersize=4)
    if pd.notna(baseline):
        ax.axhline(
            baseline,
            color="#9aa3b1",
            linestyle="--",
            linewidth=1.2,
            label=f"28-Tage-Baseline {baseline:.0f} ms",
        )
        ax.legend(loc="best", facecolor="#1a1f2e", edgecolor="#2a2f3e", labelcolor="#e6e6e6")
    ax.set_title("HRV-Trend — letzte 30 Tage", color="#e6e6e6")
    ax.set_ylabel("HRV (ms)", color="#9aa3b1")
    ax.tick_params(colors="#9aa3b1")
    for spine in ax.spines.values():
        spine.set_color("#2a2f3e")
    ax.grid(True, alpha=0.15, color="#9aa3b1")
    fig.autofmt_xdate()
    fig.tight_layout()
    st.pyplot(fig)


# ============================================================
# MAIN APP
# ============================================================


def main() -> None:
    st.set_page_config(
        page_title="Performance OS",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    cfg = load_config()
    dates = available_dates()

    # --- Sidebar: Date Picker ---
    with st.sidebar:
        st.markdown("### Performance OS")
        if not dates:
            st.error("whoop_daily ist leer. Erst `python -m engine.ingest.whoop` laufen lassen.")
            st.stop()

        min_d = date_cls.fromisoformat(dates[0])
        max_d = date_cls.fromisoformat(dates[-1])
        default_d = max_d  # zuletzt verfuegbarer Tag

        picked = st.date_input(
            "Datum",
            value=default_d,
            min_value=min_d,
            max_value=max_d,
        )
        date_str = picked.isoformat() if hasattr(picked, "isoformat") else str(picked)

        st.divider()
        st.caption(f"Verfuegbar: {dates[0]} → {dates[-1]} ({len(dates)} Tage)")

    # --- Header ---
    h1, h2 = st.columns([3, 1])
    with h1:
        st.markdown(f"## Performance OS · {date_str}")
    with h2:
        st.markdown(
            f'<div style="text-align:right;color:#9aa3b1;font-size:0.9rem;padding-top:0.7rem;">'
            f'Heute: {date_cls.today().isoformat()}</div>',
            unsafe_allow_html=True,
        )

    # --- Layer 1 berechnen ---
    try:
        layer1 = calculate(date_str, cfg)
    except ValueError as e:
        st.error(f"Layer 1: {e}")
        st.stop()

    # Whoop-Zeile fuer die Karten
    with sqlite3.connect(get_db_path()) as conn:
        whoop_row = _fetch_one(conn, "whoop_daily", date_str) or {}

    # Baseline aus 28-Tage-Fenster
    window28 = load_whoop_window(date_str, 28)
    hrv_baseline = float(window28["hrv"].mean(skipna=True)) if not window28.empty else 0.0

    # --- DailyData bauen + Protocol generieren ---
    try:
        daily_data = build_daily_data(date_str, layer1, cfg)
        protocol = generate_protocol(daily_data)
    except Exception as e:
        st.warning(f"Protocol konnte nicht erzeugt werden: {type(e).__name__}: {e}")
        protocol = None

    # --- 2. PROTOCOL BANNER ---
    if protocol is not None:
        render_protocol_banner(protocol)

    # --- 3. DISKREPANZ-KARTE ---
    render_discrepancy_card(
        whoop=int(layer1["whoop_recovery"]) if layer1.get("whoop_recovery") is not None else 0,
        adjusted=int(layer1["adjusted_readiness"]),
    )

    # --- 4. READINESS-ROW ---
    render_readiness_row(layer1, whoop_row, hrv_baseline)

    st.markdown("&nbsp;", unsafe_allow_html=True)  # Abstand

    # --- 5. CHARTS ---
    acwr_all = load_acwr_series()
    window30 = load_whoop_window(date_str, 30)
    acwr_window = acwr_all[acwr_all["date"].isin(window30["date"])].reset_index(drop=True)

    c1, c2 = st.columns(2)
    with c1:
        render_acwr_chart(acwr_window, cfg)
    with c2:
        render_hrv_chart(window30)

    # --- 6. AI REPORT ---
    st.divider()
    st.markdown("### AI Report")
    import os

    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.info("ANTHROPIC_API_KEY nicht gesetzt — Report nicht verfuegbar.")
    else:
        key = f"report::{date_str}"
        if st.button("Generate AI Report", type="primary"):
            with st.spinner("Calling Claude API..."):
                try:
                    from coach.interpret import generate_daily_report

                    report = generate_daily_report(layer1, cfg)
                    st.session_state[key] = report
                except Exception as e:
                    st.error(f"Layer 2 abgebrochen: {type(e).__name__}: {e}")

        if key in st.session_state:
            st.markdown(st.session_state[key])


if __name__ == "__main__":
    main()
