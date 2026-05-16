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

# Engine-Imports defensiv -- das Dashboard soll auch laufen, wenn einzelne
# Module noch nicht existieren (z. B. technical.py beim Aufbau).
ENGINE_ERRORS: dict[str, str] = {}

try:
    from engine.calculate import calculate  # noqa: E402
except Exception as _e:  # pragma: no cover -- nur bei kaputtem Setup
    calculate = None  # type: ignore[assignment]
    ENGINE_ERRORS["engine.calculate"] = f"{type(_e).__name__}: {_e}"

try:
    from engine.models import acwr  # noqa: E402
except Exception as _e:
    acwr = None  # type: ignore[assignment]
    ENGINE_ERRORS["engine.models.acwr"] = f"{type(_e).__name__}: {_e}"

try:
    from engine.models.protocol import DailyData, generate_protocol  # noqa: E402
except Exception as _e:
    DailyData = None  # type: ignore[assignment]
    generate_protocol = None  # type: ignore[assignment]
    ENGINE_ERRORS["engine.models.protocol"] = f"{type(_e).__name__}: {_e}"

# Optional: Technical-Modul. Existiert (noch) nicht im Repo -- Sektion 6
# bleibt einfach ausgeblendet, bis es da ist.
try:
    from engine.models import technical as technical_mod  # noqa: E402
    HAS_TECHNICAL = True
except Exception:
    technical_mod = None
    HAS_TECHNICAL = False

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

# Ampel-Farben fuer die Metrik-Karten
TRAFFIC = {
    "green": "#3fbf6a",
    "yellow": "#e6c34f",
    "red": "#e64f4f",
    "muted": "#6a7280",
}


def _traffic_readiness(score: int) -> str:
    if score >= 75:
        return TRAFFIC["green"]
    if score >= 50:
        return TRAFFIC["yellow"]
    return TRAFFIC["red"]


def _traffic_acwr_zone(zone: str | None) -> str:
    return {
        "optimal": TRAFFIC["green"],
        "spike": TRAFFIC["red"],
        "detraining": TRAFFIC["yellow"],
    }.get(zone or "", TRAFFIC["muted"])


def _traffic_hrv(delta_pct: float | None) -> str:
    if delta_pct is None:
        return TRAFFIC["muted"]
    if delta_pct >= -5:
        return TRAFFIC["green"]
    if delta_pct >= -10:
        return TRAFFIC["yellow"]
    return TRAFFIC["red"]


def _traffic_sleep(hours: float | None, eff: float | None) -> str:
    if hours is None or eff is None:
        return TRAFFIC["muted"]
    # Voller Bonus: laenger UND effizient
    if hours >= 7.5 and eff >= 90:
        return TRAFFIC["green"]
    # Roter Bereich: sehr kurz ODER sehr ineffizient
    if hours < 6 or eff < 75:
        return TRAFFIC["red"]
    return TRAFFIC["yellow"]


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
    """Banner + Gruende. Flags wandern in render_flags_section() unten."""
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


def render_flags_section(protocol) -> None:
    """Eigenstaendige Sektion: jeder Flag als auffaellige Zeile.

    Drei Kategorien mit eigener Akzentfarbe:
        flags             -> rot     (Recovery/Training-Warnungen)
        nutrition_flags   -> orange  (Ernaehrungs-Hinweise)
        bloodwork_flags   -> violett (Blutwerte)

    Section wird nur gerendert, wenn mindestens ein Flag existiert.
    """
    flags = list(protocol.flags or [])
    nut = list(protocol.nutrition_flags or [])
    blood = list(protocol.bloodwork_flags or [])
    total = len(flags) + len(nut) + len(blood)
    if total == 0:
        return

    st.markdown(f"### Aktive Flags ({total})")

    def _row(text: str, accent: str, bg: str) -> str:
        return (
            f'<div style="'
            f'background:{bg};'
            f'border-left:4px solid {accent};'
            f'border-radius:6px;'
            f'padding:0.6rem 0.9rem;'
            f'margin:0.3rem 0;'
            f'color:#f0f0f0;'
            f'font-size:0.92rem;'
            f'line-height:1.4;'
            f'">{text}</div>'
        )

    html_parts: list[str] = []
    for f in flags:
        html_parts.append(_row(f, accent="#e64f4f", bg="#3a1f1f"))
    for f in nut:
        html_parts.append(_row(f, accent="#e89348", bg="#3a2a1f"))
    for f in blood:
        html_parts.append(_row(f, accent="#a070d0", bg="#2a1f3a"))

    st.markdown("".join(html_parts), unsafe_allow_html=True)


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

    # --- Adjusted Readiness (Ampel: >=75 gruen, 50-74 gelb, <50 rot) ---
    adj = int(layer1["adjusted_readiness"])
    corrs = layer1.get("corrections_applied") or []
    corr_text = ", ".join(corrs) if corrs else "keine Korrekturen"
    with col1:
        st.markdown(
            _card("ADJUSTED READINESS", f"{adj}", sub=corr_text, accent=_traffic_readiness(adj)),
            unsafe_allow_html=True,
        )

    # --- ACWR (Farbe = Zone) ---
    acwr_val = layer1.get("acwr")
    zone = layer1.get("acwr_zone")
    acwr_text = f"{acwr_val:.2f}" if acwr_val is not None else "—"
    with col2:
        st.markdown(
            _card("ACWR", acwr_text, sub=f"Zone: {zone or 'n/a'}", accent=_traffic_acwr_zone(zone)),
            unsafe_allow_html=True,
        )

    # --- HRV vs Baseline (>= -5% gruen, -5..-10 gelb, < -10 rot) ---
    hrv = whoop_row.get("hrv")
    if hrv is not None and hrv_baseline:
        delta_pct = ((hrv - hrv_baseline) / hrv_baseline) * 100
        hrv_text = f"{hrv:.0f} ms"
        hrv_sub = f"Baseline {hrv_baseline:.0f} ms · {delta_pct:+.1f}%"
        hrv_accent = _traffic_hrv(delta_pct)
    else:
        hrv_text, hrv_sub, hrv_accent = "—", "keine Daten", TRAFFIC["muted"]
    with col3:
        st.markdown(_card("HRV", hrv_text, sub=hrv_sub, accent=hrv_accent), unsafe_allow_html=True)

    # --- Sleep (>=7.5h & >=90% eff = gruen, <6h ODER <75% eff = rot, sonst gelb) ---
    h = whoop_row.get("sleep_hours")
    e = whoop_row.get("sleep_efficiency")
    if h is not None and e is not None:
        sleep_text = f"{h:.1f} h"
        sleep_sub = f"Effizienz {e:.0f}%"
        sleep_accent = _traffic_sleep(h, e)
    else:
        sleep_text, sleep_sub, sleep_accent = "—", "keine Daten", TRAFFIC["muted"]
    with col4:
        st.markdown(_card("SLEEP", sleep_text, sub=sleep_sub, accent=sleep_accent), unsafe_allow_html=True)


def _traffic_calories(deficit_kcal: float | None) -> str:
    """Farbe fuer Kalorien-Karte. Deficit positiv = unter TDEE.

    >400 rot, 200..400 gelb, <200 (inkl. Surplus) gruen.
    """
    if deficit_kcal is None:
        return TRAFFIC["muted"]
    if deficit_kcal > 400:
        return TRAFFIC["red"]
    if deficit_kcal >= 200:
        return TRAFFIC["yellow"]
    return TRAFFIC["green"]


def render_nutrition_row(date_str: str, cfg: dict) -> None:
    """4 Karten: Kalorien, Protein, Carbs, Deficit-Status.

    Liest yazio_daily fuer date_str. Fehlt die Zeile -> dezente Hinweiszeile.
    Schwellen fuer das Kalorien-Banner: >400 rot, 200..400 gelb, <200 gruen.
    Status 'DEFICIT' bindet an config.nutrition.deficit_threshold (300),
    damit das Banner mit dem Engine-Wert deficit_detected konsistent ist.
    """
    with sqlite3.connect(get_db_path()) as conn:
        yazio = _fetch_one(conn, "yazio_daily", date_str)

    if not yazio:
        st.markdown(
            '<div style="background:#1a1f2e;border-left:4px solid #6a7280;'
            'border-radius:6px;padding:0.55rem 0.85rem;margin:0.3rem 0;'
            'color:#9aa3b1;font-size:0.9rem;">'
            'Keine Ernaehrungsdaten fuer diesen Tag</div>',
            unsafe_allow_html=True,
        )
        return

    # Config-Werte
    weight_kg = float(cfg["athlete"]["weight_kg"])
    tdee = float(cfg["nutrition"]["tdee"])
    protein_target_g = float(cfg["nutrition"]["protein_target_per_kg"]) * weight_kg
    deficit_threshold = float(cfg["nutrition"].get("deficit_threshold", 300))

    # Yazio-Werte (defensiv -- None bleibt None)
    cals = yazio.get("calories")
    protein = yazio.get("protein")
    carbs = yazio.get("carbs")

    deficit_kcal = (tdee - float(cals)) if cals is not None else None
    deficit_detected = deficit_kcal is not None and deficit_kcal > deficit_threshold

    col1, col2, col3, col4 = st.columns(4)

    # --- Spalte 1: Kalorien ---
    with col1:
        if cals is not None:
            sub = (
                f"TDEE {tdee:.0f} · "
                + (f"-{deficit_kcal:.0f} kcal" if deficit_kcal > 0 else f"+{abs(deficit_kcal):.0f} kcal")
            )
            st.markdown(
                _card("KALORIEN", f"{cals:.0f} kcal",
                      sub=sub, accent=_traffic_calories(deficit_kcal)),
                unsafe_allow_html=True,
            )
        else:
            st.markdown(_card("KALORIEN", "—", sub="keine Daten",
                              accent=TRAFFIC["muted"]),
                        unsafe_allow_html=True)

    # --- Spalte 2: Protein ---
    with col2:
        if protein is not None:
            protein_f = float(protein)
            protein_ok = protein_f >= protein_target_g
            accent = TRAFFIC["green"] if protein_ok else TRAFFIC["red"]
            sub = f"Target {protein_target_g:.0f} g · {protein_f/protein_target_g*100:.0f}%"
            st.markdown(
                _card("PROTEIN", f"{protein_f:.0f} g", sub=sub, accent=accent),
                unsafe_allow_html=True,
            )
        else:
            st.markdown(_card("PROTEIN", "—", sub="keine Daten",
                              accent=TRAFFIC["muted"]),
                        unsafe_allow_html=True)

    # --- Spalte 3: Kohlenhydrate ---
    with col3:
        if carbs is not None:
            carbs_f = float(carbs)
            per_kg = carbs_f / weight_kg
            st.markdown(
                _card("CARBS", f"{carbs_f:.0f} g",
                      sub=f"{per_kg:.1f} g/kg",
                      accent="#3b82f6"),
                unsafe_allow_html=True,
            )
        else:
            st.markdown(_card("CARBS", "—", sub="keine Daten",
                              accent=TRAFFIC["muted"]),
                        unsafe_allow_html=True)

    # --- Spalte 4: Deficit-Status (grosses Label) ---
    with col4:
        if cals is not None:
            status_label = "DEFICIT" if deficit_detected else "ON TARGET"
            status_accent = TRAFFIC["red"] if deficit_detected else TRAFFIC["green"]
            status_sub = (
                f"{deficit_kcal:+.0f} kcal vs TDEE"
                if deficit_kcal is not None else "—"
            )
            st.markdown(
                _card("STATUS", status_label, sub=status_sub, accent=status_accent),
                unsafe_allow_html=True,
            )
        else:
            st.markdown(_card("STATUS", "—", sub="keine Daten",
                              accent=TRAFFIC["muted"]),
                        unsafe_allow_html=True)


def render_acwr_chart(acwr_df: pd.DataFrame, cfg: dict) -> None:
    """ACWR-Verlauf mit 4 abgestuften Zonen-Bands.

    Zonen:
        gruen   detraining_threshold .. spike_threshold    (optimal, dominant)
        gelb    0 .. detraining_threshold                  (detraining)
        orange  spike_threshold .. danger_threshold        (caution 1.3-1.5)
        rot     danger_threshold .. oben                   (danger >1.5)
    """
    import matplotlib.pyplot as plt

    spike = float(cfg["acwr"]["spike_threshold"])           # 1.3
    detraining = float(cfg["acwr"]["detraining_threshold"]) # 0.8
    danger = 1.5  # zweite Stufe aus protocol.py — bewusst hardgecoded weil
                  # die Schwelle dort fix ist (siehe protocol.select_training_recommendation)

    fig, ax = plt.subplots(figsize=(11, 4))
    fig.patch.set_facecolor("#1a1f2e")
    ax.set_facecolor("#1a1f2e")

    y_min = min(0.5, float(acwr_df["acwr"].min(skipna=True) or 0.5) - 0.1)
    y_max = max(1.7, float(acwr_df["acwr"].max(skipna=True) or 1.7) + 0.1)

    # Reihenfolge: erst Bands, dann Linie drueber.
    # Alphas absichtlich asymmetrisch: gruen am dominantesten, rot am signal-staerksten.
    ax.axhspan(detraining, spike, color="#3fbf6a", alpha=0.32, label="optimal")
    ax.axhspan(y_min, detraining, color="#e6c34f", alpha=0.18, label="detraining")
    ax.axhspan(spike, min(danger, y_max), color="#e89348", alpha=0.22, label="caution")
    if y_max > danger:
        ax.axhspan(danger, y_max, color="#e64f4f", alpha=0.32, label="danger >1.5")

    # Trennlinien fuer die Schwellen, damit die Grenzen klar erkennbar bleiben
    for thr in (detraining, spike, danger):
        if y_min <= thr <= y_max:
            ax.axhline(thr, color="#3a3f4e", linestyle="-", linewidth=0.5, alpha=0.8)

    ax.plot(
        acwr_df["date"],
        acwr_df["acwr"],
        marker="o",
        color="#f0f0f0",
        linewidth=1.8,
        markersize=4.5,
        markeredgecolor="#1a1f2e",
        markeredgewidth=0.8,
    )
    ax.axhline(1.0, color="#9aa3b1", linestyle=":", linewidth=0.7, alpha=0.5)

    ax.set_ylim(y_min, y_max)
    ax.set_title("ACWR — letzte 30 Tage", color="#e6e6e6")
    ax.tick_params(colors="#9aa3b1")
    for spine in ax.spines.values():
        spine.set_color("#2a2f3e")
    ax.grid(True, alpha=0.1, color="#9aa3b1")
    ax.legend(
        loc="upper left",
        facecolor="#1a1f2e",
        edgecolor="#2a2f3e",
        labelcolor="#e6e6e6",
        fontsize=8,
        ncol=4,
    )
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
# TECHNICAL PERFORMANCE (Section 6)
# ============================================================

# Mapping fuer Athlete-Position aus config -> Kuerzel, die protocol.py und
# technical.py erwarten (GK|CB|FB|CM|AM|W|ST).
_POSITION_MAP = {
    "GK": "GK", "TW": "GK",
    "CB": "CB", "IV": "CB",
    "FB": "FB", "LB": "FB", "RB": "FB",
    "CM": "CM", "ZM": "CM", "DM": "CM",
    "AM": "AM", "OM": "AM", "ZOM": "AM",
    "W": "W", "LW": "W", "RW": "W", "LM": "W", "RM": "W",
    "ST": "ST", "CF": "ST",
}


def _normalize_position(cfg: dict) -> str:
    """Athletes config-Position (z. B. 'LB / LM') -> Kuerzel fuer Modelle."""
    raw = (cfg.get("athlete", {}).get("position") or "FB").upper()
    # Erstes Token vor '/', ',' oder Whitespace -> Mapping.
    token = raw.replace(",", " ").replace("/", " ").split()
    if not token:
        return "FB"
    return _POSITION_MAP.get(token[0], "FB")


def _technical_row_for_date(conn: sqlite3.Connection, date_str: str) -> dict | None:
    """Single technical_sessions-Zeile fuer date_str, oder None."""
    if not _table_exists(conn, "technical_sessions"):
        return None
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        "SELECT * FROM technical_sessions WHERE date = ? ORDER BY id DESC LIMIT 1",
        (date_str,),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def _compute_technical_baseline(conn: sqlite3.Connection, end_date: str):
    """28-Tage-Rolling-Baseline (strict before end_date). None bei 0 Sessions."""
    if not HAS_TECHNICAL or not _table_exists(conn, "technical_sessions"):
        return None

    agg = conn.execute(
        """
        SELECT
            COUNT(*)                                       AS n,
            AVG(total_touches)                             AS avg_touches,
            AVG((touches_left * 1.0)
                / NULLIF(touches_left + touches_right, 0)) AS avg_left_share,
            AVG(kick_velocity_avg_kmh)                     AS avg_kv,
            AVG(kick_velocity_left_kmh)                    AS avg_kv_l,
            AVG(kick_velocity_right_kmh)                   AS avg_kv_r,
            AVG(time_on_ball_sec)                          AS avg_tob,
            AVG(time_to_release_sec)                       AS avg_ttr,
            AVG(one_touch_pct)                             AS avg_one_touch,
            AVG(top_speed_kmh)                             AS avg_top_speed,
            AVG(sprint_distance_m)                         AS avg_sprint,
            AVG(decelerations)                             AS avg_decel,
            AVG(work_rate)                                 AS avg_work_rate
        FROM technical_sessions
        WHERE date < ? AND date >= date(?, '-28 day')
        """,
        (end_date, end_date),
    ).fetchone()

    if not agg or not agg[0]:
        return None

    # Sample-SD fuer kick_velocity (sqlite hat kein STDDEV)
    kv_vals = [
        r[0] for r in conn.execute(
            "SELECT kick_velocity_avg_kmh FROM technical_sessions "
            "WHERE date < ? AND date >= date(?, '-28 day') "
            "AND kick_velocity_avg_kmh IS NOT NULL",
            (end_date, end_date),
        ).fetchall()
    ]
    sd_kv = None
    if len(kv_vals) >= 2:
        import statistics
        sd_kv = statistics.stdev(kv_vals)

    return technical_mod.TechnicalBaseline(
        avg_touches_per_session=float(agg[1] or 0),
        avg_touch_balance_pct=float((agg[2] or 0) * 100),
        avg_kick_velocity_kmh=float(agg[3] or 0),
        avg_kick_velocity_left_kmh=float(agg[4]) if agg[4] is not None else None,
        avg_kick_velocity_right_kmh=float(agg[5]) if agg[5] is not None else None,
        avg_time_on_ball_sec=float(agg[6] or 0),
        avg_time_to_release_sec=float(agg[7] or 0),
        avg_one_touch_pct=float(agg[8] or 0),
        avg_top_speed_kmh=float(agg[9] or 0),
        avg_sprint_distance_m=float(agg[10] or 0),
        avg_decelerations=float(agg[11] or 0),
        avg_work_rate=float(agg[12] or 0),
        sessions_count=int(agg[0]),
        sd_kick_velocity=sd_kv,
    )


def _session_data_from_row(row: dict):
    """DB-Row -> TechnicalSessionData. Fuellt fehlende Werte mit 0 / None."""
    def f(key, default=0.0):
        v = row.get(key)
        return float(v) if v is not None else default

    def i(key, default=0):
        v = row.get(key)
        return int(v) if v is not None else default

    def opt(key):
        v = row.get(key)
        return float(v) if v is not None else None

    return technical_mod.TechnicalSessionData(
        date=row["date"],
        session_type=row.get("session_type") or "team_training",
        duration_min=f("duration_min"),
        total_distance_m=f("total_distance_m"),
        sprint_distance_m=f("sprint_distance_m"),
        num_sprints=i("num_sprints"),
        top_speed_kmh=f("top_speed_kmh"),
        accelerations=i("accelerations"),
        decelerations=i("decelerations"),
        work_rate=f("work_rate"),
        total_touches=i("total_touches"),
        touches_left=i("touches_left"),
        touches_right=i("touches_right"),
        kick_velocity_max_kmh=f("kick_velocity_max_kmh"),
        kick_velocity_avg_kmh=f("kick_velocity_avg_kmh"),
        time_on_ball_sec=f("time_on_ball_sec"),
        num_possessions=i("num_possessions"),
        avg_possession_duration_sec=f("avg_possession_duration_sec"),
        one_touch_pct=f("one_touch_pct"),
        time_to_release_sec=f("time_to_release_sec"),
        kick_velocity_left_kmh=opt("kick_velocity_left_kmh"),
        kick_velocity_right_kmh=opt("kick_velocity_right_kmh"),
        first_touch_quality=opt("first_touch_quality"),
        dribble_distance_m=opt("dribble_distance_m"),
        dribble_count=int(row["dribble_count"]) if row.get("dribble_count") is not None else None,
        successful_passes=int(row["successful_passes"]) if row.get("successful_passes") is not None else None,
        total_passes=int(row["total_passes"]) if row.get("total_passes") is not None else None,
        turnovers=int(row["turnovers"]) if row.get("turnovers") is not None else None,
    )


def _traffic_kick_velocity(delta_pct: float | None) -> str:
    if delta_pct is None:
        return TRAFFIC["muted"]
    if delta_pct >= -5:
        return TRAFFIC["green"]
    if delta_pct >= -15:
        return TRAFFIC["yellow"]
    return TRAFFIC["red"]


def _traffic_release(delta_sec: float | None) -> str:
    if delta_sec is None:
        return TRAFFIC["muted"]
    # Hoehere Zeit = schlechter
    if delta_sec < 0.2:
        return TRAFFIC["green"]
    if delta_sec < 0.5:
        return TRAFFIC["yellow"]
    return TRAFFIC["red"]


def _traffic_fatigue(score: float | None) -> str:
    if score is None:
        return TRAFFIC["muted"]
    if score >= 65:
        return TRAFFIC["green"]
    if score >= 40:
        return TRAFFIC["yellow"]
    return TRAFFIC["red"]


def _balance_trend_color(trend: str) -> tuple[str, str]:
    """Returns (background, accent)."""
    return {
        "improving": ("#1f4a2a", "#3fbf6a"),
        "stable": ("#2a2f3e", "#6a7280"),
        "declining": ("#4a1f1f", "#e64f4f"),
    }.get(trend, ("#2a2f3e", "#6a7280"))


def _severity_styling(severity_value: str) -> tuple[str, str]:
    """Severity-String aus TechnicalFlag.severity.value -> (accent, bg)."""
    return {
        "info": ("#3fbf6a", "#1f3a2a"),
        "monitor": ("#e6c34f", "#3a2f1f"),
        "warning": ("#e89348", "#3a2a1f"),
        "critical": ("#e64f4f", "#3a1f1f"),
    }.get(severity_value, ("#6a7280", "#2a2f3e"))


def _render_balance_bar(balance_pct: float, trend: str) -> None:
    """Horizontaler L/R-Balance-Balken mit 50%-Marker."""
    left = max(0.0, min(100.0, balance_pct))
    right = 100.0 - left
    trend_bg, trend_accent = _balance_trend_color(trend)

    st.markdown(
        f"""
        <div style="margin: 0.3rem 0 1rem 0;">
            <div style="display:flex;justify-content:space-between;
                        color:#9aa3b1;font-size:0.78rem;margin-bottom:0.3rem;
                        text-transform:uppercase;letter-spacing:0.06em;">
                <span>Links {left:.0f}%</span>
                <span style="background:{trend_bg};color:#f0f0f0;
                            border-left:3px solid {trend_accent};
                            padding:0.15rem 0.55rem;border-radius:4px;
                            font-size:0.75rem;letter-spacing:0.04em;">
                    Trend: {trend}
                </span>
                <span>{right:.0f}% Rechts</span>
            </div>
            <div style="position:relative;background:#0f1419;border-radius:6px;
                        height:18px;overflow:hidden;border:1px solid #2a2f3e;">
                <div style="position:absolute;left:0;top:0;bottom:0;
                            width:{left}%;background:#3b82f6;"></div>
                <div style="position:absolute;left:{left}%;top:0;bottom:0;
                            right:0;background:#1f4a8a;"></div>
                <div style="position:absolute;left:50%;top:-2px;bottom:-2px;
                            width:1px;background:#f0f0f0;opacity:0.6;"></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_technical_section(date_str: str, cfg: dict) -> None:
    """Sektion 6 -- nur sichtbar wenn technical-Modul + Tabelle + Zeile vorhanden."""
    if not HAS_TECHNICAL:
        return

    with sqlite3.connect(get_db_path()) as conn:
        row = _technical_row_for_date(conn, date_str)
        if row is None:
            return  # Sektion komplett ausgeblendet
        baseline = _compute_technical_baseline(conn, date_str)

    if baseline is None:
        # Erste Session ueberhaupt -- Baseline nicht berechenbar.
        st.divider()
        st.markdown("### Technical Performance")
        st.info(
            "Erste Technical Session erfasst -- keine 28-Tage-Baseline vorhanden. "
            "Analyse-Flags brauchen mindestens 3 Vergleichs-Sessions."
        )
        return

    session = _session_data_from_row(row)
    position = _normalize_position(cfg)
    analysis = technical_mod.analyze_technical_session(session, baseline, position=position)

    st.divider()
    head_l, head_r = st.columns([3, 1])
    with head_l:
        st.markdown("### Technical Performance")
    with head_r:
        quality_color = {
            "good": TRAFFIC["green"],
            "limited": TRAFFIC["yellow"],
            "insufficient": TRAFFIC["red"],
        }.get(analysis.data_quality, TRAFFIC["muted"])
        st.markdown(
            f'<div style="text-align:right;padding-top:0.6rem;">'
            f'<span style="background:#1a1f2e;border-left:3px solid {quality_color};'
            f'padding:0.25rem 0.6rem;border-radius:4px;color:#9aa3b1;'
            f'font-size:0.78rem;text-transform:uppercase;letter-spacing:0.06em;">'
            f'Daten-Qualitaet: {analysis.data_quality}</span></div>',
            unsafe_allow_html=True,
        )

    # L/R Balance Bar
    _render_balance_bar(analysis.balance_pct, analysis.balance_trend)

    # Drei Delta-Karten
    vs = analysis.vs_baseline
    c1, c2, c3 = st.columns(3)
    with c1:
        kv = vs["kick_velocity"]
        st.markdown(
            _card(
                "KICK VELOCITY",
                f"{kv['today']:.1f} km/h",
                sub=f"Baseline {kv['baseline']:.1f} · {kv['delta_pct']:+.1f}%",
                accent=_traffic_kick_velocity(kv["delta_pct"]),
            ),
            unsafe_allow_html=True,
        )
    with c2:
        ttr = vs["time_to_release"]
        st.markdown(
            _card(
                "TIME TO RELEASE",
                f"{ttr['today']:.2f} s",
                sub=f"Baseline {ttr['baseline']:.2f}s · {ttr['delta_sec']:+.2f}s",
                accent=_traffic_release(ttr["delta_sec"]),
            ),
            unsafe_allow_html=True,
        )
    with c3:
        fc = vs["fatigue_composite"]
        st.markdown(
            _card(
                "FATIGUE COMPOSITE",
                f"{fc['score']:.0f}/100",
                sub=f"{len(fc['signals'])} Signal(e)",
                accent=_traffic_fatigue(fc["score"]),
            ),
            unsafe_allow_html=True,
        )

    # Flags zusammenfassen (balance + quality + physical + injury)
    all_flags = (
        list(analysis.balance_flags)
        + list(analysis.quality_flags)
        + list(analysis.physical_flags)
        + list(analysis.injury_warnings)
    )

    if analysis.data_quality_notes or all_flags:
        st.markdown(f"#### Technical Flags ({len(all_flags)})")

    # Data-quality-Notes als dezente, neutrale Zeilen
    for note in analysis.data_quality_notes:
        st.markdown(
            f'<div style="background:#1a1f2e;border-left:4px solid #6a7280;'
            f'border-radius:6px;padding:0.55rem 0.85rem;margin:0.25rem 0;'
            f'color:#9aa3b1;font-size:0.85rem;">{note}</div>',
            unsafe_allow_html=True,
        )

    # TechnicalFlag-Objekte mit severity-gefaerbten Zeilen
    for flag in all_flags:
        sev = getattr(getattr(flag, "severity", None), "value", "monitor")
        accent, bg = _severity_styling(sev)
        st.markdown(
            f'<div style="background:{bg};border-left:4px solid {accent};'
            f'border-radius:6px;padding:0.6rem 0.9rem;margin:0.3rem 0;'
            f'color:#f0f0f0;font-size:0.9rem;line-height:1.4;">'
            f'<strong style="color:{accent};text-transform:uppercase;font-size:0.75rem;'
            f'letter-spacing:0.06em;">[{sev}] {flag.category}</strong><br>{flag.message}</div>',
            unsafe_allow_html=True,
        )


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
        st.warning(f"Keine Whoop-Daten fuer {date_str}.")
        if dates:
            latest = dates[-1]
            st.info(
                f"Letzter verfuegbarer Tag: **{latest}**. "
                f"Waehle ihn im Sidebar-Picker, oder fuehre erst "
                f"`python -m engine.ingest.whoop` aus."
            )
        else:
            st.info("`python -m engine.ingest.whoop` zuerst laufen lassen.")
        st.caption(f"Detail: {e}")
        st.stop()
    except Exception as e:  # weitere Engine-Fehler nicht stumm sterben lassen
        st.error(f"Layer 1: {type(e).__name__}: {e}")
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

    # --- 4a. NUTRITION-ROW ---
    render_nutrition_row(date_str, cfg)

    st.markdown("&nbsp;", unsafe_allow_html=True)  # Abstand

    # --- 4b. FLAGS-SEKTION (nur wenn vorhanden) ---
    if protocol is not None:
        render_flags_section(protocol)

    # --- 5. CHARTS ---
    acwr_all = load_acwr_series()
    window30 = load_whoop_window(date_str, 30)
    acwr_window = acwr_all[acwr_all["date"].isin(window30["date"])].reset_index(drop=True)

    c1, c2 = st.columns(2)
    with c1:
        render_acwr_chart(acwr_window, cfg)
    with c2:
        render_hrv_chart(window30)

    # --- 6. TECHNICAL PERFORMANCE (optional) ---
    render_technical_section(date_str, cfg)

    # --- 7. AI REPORT ---
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
