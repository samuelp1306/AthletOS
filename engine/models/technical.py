"""
Performance OS — Technical Performance Module v2.0 (engine/models/technical.py)

RULE-BASED ANALYSIS of Playermaker boot sensor data.
No LLM. Deterministic. Every rule has a sports science rationale.

This module does NOT affect the Readiness Score.
It generates its own flags and recommendations that Layer 2 presents
alongside the physical readiness report.

v2.0 improvements over v1.0:
- Fatigue Composite Score (multi-metric fatigue detection)
- Session-type normalization (match vs training have different baselines)
- Asymmetry detection beyond L/R balance (velocity, acceleration per foot)
- Dribble analysis and progressive carrying metrics
- Injury early warning system (velocity + decel + asymmetry combination)
- Multi-session trend tracking (not just today vs baseline)
- Minimum data thresholds (don't flag on insufficient data)
- Position-specific benchmarks for all metrics
- Edge case handling for short sessions, drills, and keeper data

Data source: Playermaker UNO / 2.0 boot-mounted sensors
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


# ============================================================
# ENUMS & CONSTANTS
# ============================================================

class SessionType(Enum):
    MATCH = "match"
    TEAM_TRAINING = "team_training"
    INDIVIDUAL = "individual"
    DRILL = "drill"


class Severity(Enum):
    """Flag severity levels for Layer 2 color-coding."""
    INFO = "info"           # green — positive or neutral observation
    MONITOR = "monitor"     # yellow — worth watching
    WARNING = "warning"     # orange — needs attention
    CRITICAL = "critical"   # red — immediate action needed


# Minimum thresholds to avoid flagging on insufficient data
MIN_TOUCHES_FOR_BALANCE = 15       # Need at least 15 touches to judge L/R
MIN_POSSESSIONS_FOR_RELEASE = 8    # Need enough possessions to judge tempo
MIN_SESSION_DURATION_MIN = 20      # Sessions shorter than 20min are drills
MIN_BASELINE_SESSIONS = 5          # Need 5+ sessions for reliable baseline

# Session-type normalization factors
# Match data is naturally different from training — normalize before comparing
# Source: Position Specific Demands doc — match intensity ≠ training intensity
SESSION_NORMALIZATION = {
    "match": {
        "touch_factor": 1.0,        # matches are the reference
        "velocity_factor": 1.0,
        "sprint_factor": 1.0,
    },
    "team_training": {
        "touch_factor": 1.15,       # ~15% more touches in training (more reps)
        "velocity_factor": 0.90,    # ~10% lower kick velocity (less pressure)
        "sprint_factor": 0.80,      # ~20% less sprinting
    },
    "individual": {
        "touch_factor": 1.4,        # much more ball contact
        "velocity_factor": 0.85,    # less match-intensity shooting
        "sprint_factor": 0.50,      # minimal sprinting
    },
    "drill": {
        "touch_factor": 2.0,        # drills are repetition-heavy
        "velocity_factor": 0.80,
        "sprint_factor": 0.30,
    },
}


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class TechnicalSessionData:
    """Single session data from Playermaker sensors."""
    date: str
    session_type: str               # match | team_training | individual | drill
    duration_min: float             # v2: added for per-minute normalization

    # Physical metrics (Playermaker also tracks these)
    total_distance_m: float
    sprint_distance_m: float
    num_sprints: int
    top_speed_kmh: float
    accelerations: int              # high-intensity >3m/s²
    decelerations: int
    work_rate: float                # m/min

    # Technical metrics (unique to Playermaker)
    total_touches: int
    touches_left: int
    touches_right: int
    kick_velocity_max_kmh: float
    kick_velocity_avg_kmh: float
    time_on_ball_sec: float         # total seconds in possession
    num_possessions: int
    avg_possession_duration_sec: float
    one_touch_pct: float            # % of possessions that were one-touch
    time_to_release_sec: float      # avg time from receiving to passing/shooting

    # v2: Per-foot velocity (if available from Playermaker 2.0)
    kick_velocity_left_kmh: Optional[float] = None
    kick_velocity_right_kmh: Optional[float] = None

    # v2: Advanced metrics
    first_touch_quality: Optional[float] = None    # 0-100 if available
    dribble_distance_m: Optional[float] = None
    dribble_count: Optional[int] = None            # number of carries >5m
    successful_passes: Optional[int] = None
    total_passes: Optional[int] = None
    turnovers: Optional[int] = None                # lost possessions


@dataclass
class TechnicalBaseline:
    """Rolling baselines calculated from the last 28 days of sessions."""
    avg_touches_per_session: float
    avg_touch_balance_pct: float        # left / (left + right) * 100
    avg_kick_velocity_kmh: float
    avg_kick_velocity_left_kmh: Optional[float]     # v2: per-foot baseline
    avg_kick_velocity_right_kmh: Optional[float]
    avg_time_on_ball_sec: float
    avg_time_to_release_sec: float
    avg_one_touch_pct: float
    avg_top_speed_kmh: float
    avg_sprint_distance_m: float
    avg_decelerations: float                        # v2: for relative comparison
    avg_work_rate: float                            # v2: m/min baseline
    sessions_count: int

    # v2: Standard deviations for SWC (Smallest Worthwhile Change)
    sd_kick_velocity: Optional[float] = None
    sd_touches: Optional[float] = None
    sd_top_speed: Optional[float] = None

    # v2: Recent trend (last 5 sessions)
    recent_kick_velocity_trend: Optional[str] = None    # rising | stable | falling
    recent_balance_trend: Optional[str] = None
    recent_top_speed_trend: Optional[str] = None


@dataclass
class TechnicalFlag:
    """Structured flag with severity and category."""
    severity: Severity
    category: str           # balance | quality | physical | injury_warning | fatigue
    message: str
    metric: str             # which metric triggered this
    value: float            # current value
    baseline: float         # baseline value
    delta_pct: float        # % change from baseline


@dataclass
class TechnicalAnalysis:
    """Output from analyze_technical_session. Passed to Layer 2."""
    # Balance analysis
    left_right_balance: str             # balanced | left_dominant | right_dominant
    balance_pct: float                  # left foot % (50 = perfect)
    balance_trend: str                  # improving | stable | declining
    balance_flags: list                 # list of TechnicalFlag

    # Technical quality flags
    quality_flags: list

    # Physical flags from boot data
    physical_flags: list

    # v2: Fatigue composite
    fatigue_composite_score: float      # 0-100 (100 = fresh, 0 = exhausted)
    fatigue_signals: list               # which metrics contribute

    # v2: Injury early warning
    injury_warnings: list               # combined multi-metric warnings

    # Development recommendations
    recommendations: list

    # Raw comparison vs baseline
    vs_baseline: dict

    # v2: Data quality indicator
    data_quality: str                   # good | limited | insufficient
    data_quality_notes: list


# ============================================================
# DATA QUALITY CHECK
# ============================================================

def check_data_quality(session: TechnicalSessionData, baseline: TechnicalBaseline) -> tuple:
    """
    Verify we have enough data to make meaningful analysis.
    Returns: (quality_level, notes)
    """
    notes = []
    quality = "good"

    total_touches = session.touches_left + session.touches_right

    if baseline.sessions_count < MIN_BASELINE_SESSIONS:
        quality = "limited"
        notes.append(
            f"Baseline has only {baseline.sessions_count} sessions "
            f"(minimum {MIN_BASELINE_SESSIONS} for reliable analysis). "
            f"Flags may be less accurate."
        )

    if total_touches < MIN_TOUCHES_FOR_BALANCE:
        quality = "limited" if quality == "good" else quality
        notes.append(
            f"Only {total_touches} touches recorded — L/R balance analysis unreliable."
        )

    if session.num_possessions < MIN_POSSESSIONS_FOR_RELEASE:
        notes.append(
            f"Only {session.num_possessions} possessions — "
            f"time-to-release analysis unreliable."
        )

    if session.duration_min < MIN_SESSION_DURATION_MIN:
        quality = "limited" if quality == "good" else quality
        notes.append(
            f"Short session ({session.duration_min:.0f} min). "
            f"Physical metrics may not reflect true capacity."
        )

    if baseline.sessions_count < 3:
        quality = "insufficient"
        notes.append("Fewer than 3 baseline sessions. Analysis is preliminary only.")

    return quality, notes


# ============================================================
# BALANCE ANALYSIS (v2: improved)
# ============================================================

def analyze_balance(
    session: TechnicalSessionData,
    baseline: TechnicalBaseline,
    position: str = "FB"
) -> tuple:
    """
    v2 improvements:
    - Minimum touch threshold before flagging
    - Per-foot velocity asymmetry (not just touch count)
    - Position-specific balance targets
    - Graduated severity levels
    """
    total = session.touches_left + session.touches_right
    if total < MIN_TOUCHES_FOR_BALANCE:
        return "insufficient_data", 0.0, []

    left_pct = (session.touches_left / total) * 100
    flags = []

    # Position-specific targets
    # Source: Position Demands doc — some positions need better balance than others
    balance_targets = {
        "GK": 55,   # keepers can be more dominant-foot biased (distribution)
        "CB": 55,   # center-backs need decent balance for build-up
        "FB": 58,   # fullbacks cross from one side but need both feet in buildup
        "CM": 55,   # central midfielders need strong balance for 360° play
        "AM": 55,   # attacking mids need creativity with both feet
        "W": 60,    # wingers can be more one-footed (cut inside or cross)
        "ST": 55,   # strikers need finishing with both feet
    }
    acceptable_dominance = balance_targets.get(position, 58)

    # Classify balance
    dominant_pct = max(left_pct, 100 - left_pct)
    if dominant_pct <= 55:
        classification = "balanced"
    elif left_pct > 55:
        classification = "left_dominant"
    else:
        classification = "right_dominant"

    # Flag based on severity
    if dominant_pct > 80:
        flags.append(TechnicalFlag(
            severity=Severity.WARNING,
            category="balance",
            message=(
                f"Severe foot imbalance: dominant foot used {dominant_pct:.0f}% of touches. "
                f"This limits your tactical options and makes you predictable. "
                f"Dedicate 15 min/session exclusively to weak-foot work."
            ),
            metric="touch_balance", value=dominant_pct,
            baseline=max(baseline.avg_touch_balance_pct, 100 - baseline.avg_touch_balance_pct),
            delta_pct=0,
        ))
    elif dominant_pct > 70:
        flags.append(TechnicalFlag(
            severity=Severity.MONITOR,
            category="balance",
            message=(
                f"Significant imbalance: {dominant_pct:.0f}% dominant foot. "
                f"Target for {position}: <{acceptable_dominance}%. "
                f"Include weak-foot rondos in individual sessions."
            ),
            metric="touch_balance", value=dominant_pct,
            baseline=max(baseline.avg_touch_balance_pct, 100 - baseline.avg_touch_balance_pct),
            delta_pct=0,
        ))
    elif dominant_pct > acceptable_dominance:
        flags.append(TechnicalFlag(
            severity=Severity.INFO,
            category="balance",
            message=(
                f"Foot balance at {dominant_pct:.0f}/{100-dominant_pct:.0f}. "
                f"Room for improvement — target <{acceptable_dominance}% for your position."
            ),
            metric="touch_balance", value=dominant_pct,
            baseline=max(baseline.avg_touch_balance_pct, 100 - baseline.avg_touch_balance_pct),
            delta_pct=0,
        ))

    # v2: Per-foot kick velocity asymmetry
    # A large velocity difference between feet reveals training gaps
    if session.kick_velocity_left_kmh and session.kick_velocity_right_kmh:
        vel_diff_pct = abs(session.kick_velocity_left_kmh - session.kick_velocity_right_kmh) \
                       / max(session.kick_velocity_left_kmh, session.kick_velocity_right_kmh) * 100
        if vel_diff_pct > 25:
            weaker = "left" if session.kick_velocity_left_kmh < session.kick_velocity_right_kmh else "right"
            flags.append(TechnicalFlag(
                severity=Severity.MONITOR,
                category="balance",
                message=(
                    f"Kick velocity asymmetry: {vel_diff_pct:.0f}% difference between feet. "
                    f"{weaker.capitalize()} foot significantly weaker "
                    f"(L:{session.kick_velocity_left_kmh:.0f} vs R:{session.kick_velocity_right_kmh:.0f} km/h). "
                    f"Add {weaker}-foot shooting/passing drills."
                ),
                metric="kick_velocity_asymmetry", value=vel_diff_pct,
                baseline=0, delta_pct=0,
            ))

    # Trend vs baseline
    current_dist = abs(left_pct - 50)
    baseline_dist = abs(baseline.avg_touch_balance_pct - 50)
    if abs(current_dist - baseline_dist) > 3:
        if current_dist < baseline_dist:
            flags.append(TechnicalFlag(
                severity=Severity.INFO, category="balance",
                message=(
                    f"Balance improving: closer to 50/50 than 28-day average "
                    f"({left_pct:.0f}% L vs baseline {baseline.avg_touch_balance_pct:.0f}% L)."
                ),
                metric="balance_trend", value=left_pct,
                baseline=baseline.avg_touch_balance_pct, delta_pct=0,
            ))
        else:
            flags.append(TechnicalFlag(
                severity=Severity.MONITOR, category="balance",
                message=(
                    f"Balance declining: further from 50/50 than baseline "
                    f"({left_pct:.0f}% L vs baseline {baseline.avg_touch_balance_pct:.0f}% L)."
                ),
                metric="balance_trend", value=left_pct,
                baseline=baseline.avg_touch_balance_pct, delta_pct=0,
            ))

    return classification, left_pct, flags


# ============================================================
# TECHNICAL QUALITY ANALYSIS (v2: improved)
# ============================================================

def analyze_quality(
    session: TechnicalSessionData,
    baseline: TechnicalBaseline
) -> list:
    """
    v2 improvements:
    - Session-type normalization before comparison
    - SWC (Smallest Worthwhile Change) awareness
    - Graduated severity
    - Dribble and passing analysis
    - Turnover tracking
    """
    flags = []
    norm = SESSION_NORMALIZATION.get(session.session_type, SESSION_NORMALIZATION["team_training"])

    # --- Kick velocity ---
    if baseline.avg_kick_velocity_kmh > 0:
        # Normalize: training velocity is naturally lower than match
        normalized_vel = session.kick_velocity_avg_kmh / norm["velocity_factor"]
        vel_delta_pct = ((normalized_vel - baseline.avg_kick_velocity_kmh)
                         / baseline.avg_kick_velocity_kmh) * 100

        # Use SWC if available, otherwise use fixed thresholds
        swc = baseline.sd_kick_velocity * 0.2 if baseline.sd_kick_velocity else None
        swc_pct = (swc / baseline.avg_kick_velocity_kmh * 100) if swc else 5.0

        if vel_delta_pct < -15:
            flags.append(TechnicalFlag(
                severity=Severity.WARNING, category="quality",
                message=(
                    f"Kick velocity significantly down: {vel_delta_pct:.0f}% below baseline "
                    f"({session.kick_velocity_avg_kmh:.1f} vs baseline {baseline.avg_kick_velocity_kmh:.1f} km/h). "
                    f"Possible neuromuscular fatigue or developing muscle tightness. "
                    f"Monitor hamstring and hip flexor. If persistent for 2+ sessions, reduce lower body load."
                ),
                metric="kick_velocity", value=session.kick_velocity_avg_kmh,
                baseline=baseline.avg_kick_velocity_kmh, delta_pct=vel_delta_pct,
            ))
        elif vel_delta_pct < -swc_pct * 2:
            flags.append(TechnicalFlag(
                severity=Severity.MONITOR, category="quality",
                message=(
                    f"Kick velocity slightly down: {vel_delta_pct:.0f}% below baseline. "
                    f"Within normal variation but worth monitoring."
                ),
                metric="kick_velocity", value=session.kick_velocity_avg_kmh,
                baseline=baseline.avg_kick_velocity_kmh, delta_pct=vel_delta_pct,
            ))
        elif vel_delta_pct > 10:
            flags.append(TechnicalFlag(
                severity=Severity.INFO, category="quality",
                message=f"Kick velocity up: +{vel_delta_pct:.0f}% above baseline. Good power output.",
                metric="kick_velocity", value=session.kick_velocity_avg_kmh,
                baseline=baseline.avg_kick_velocity_kmh, delta_pct=vel_delta_pct,
            ))

    # --- Decision speed: time to release ---
    if baseline.avg_time_to_release_sec > 0 and session.num_possessions >= MIN_POSSESSIONS_FOR_RELEASE:
        release_delta = session.time_to_release_sec - baseline.avg_time_to_release_sec

        if release_delta > 0.5:
            flags.append(TechnicalFlag(
                severity=Severity.WARNING, category="quality",
                message=(
                    f"Slow release: {session.time_to_release_sec:.1f}s vs baseline "
                    f"{baseline.avg_time_to_release_sec:.1f}s (+{release_delta:.1f}s). "
                    f"Significant decision slowdown. Check fatigue, tactical role change, "
                    f"or lack of passing options."
                ),
                metric="time_to_release", value=session.time_to_release_sec,
                baseline=baseline.avg_time_to_release_sec, delta_pct=0,
            ))
        elif release_delta > 0.2:
            flags.append(TechnicalFlag(
                severity=Severity.MONITOR, category="quality",
                message=(
                    f"Release slightly slower: {session.time_to_release_sec:.1f}s "
                    f"vs baseline {baseline.avg_time_to_release_sec:.1f}s."
                ),
                metric="time_to_release", value=session.time_to_release_sec,
                baseline=baseline.avg_time_to_release_sec, delta_pct=0,
            ))
        elif release_delta < -0.3:
            flags.append(TechnicalFlag(
                severity=Severity.INFO, category="quality",
                message=(
                    f"Quick release: {session.time_to_release_sec:.1f}s vs baseline "
                    f"{baseline.avg_time_to_release_sec:.1f}s. Playing fast."
                ),
                metric="time_to_release", value=session.time_to_release_sec,
                baseline=baseline.avg_time_to_release_sec, delta_pct=0,
            ))

    # --- One-touch percentage ---
    if baseline.avg_one_touch_pct > 0 and session.num_possessions >= MIN_POSSESSIONS_FOR_RELEASE:
        ot_delta = session.one_touch_pct - baseline.avg_one_touch_pct
        if ot_delta < -15:
            flags.append(TechnicalFlag(
                severity=Severity.MONITOR, category="quality",
                message=(
                    f"One-touch play down significantly: {session.one_touch_pct:.0f}% "
                    f"vs baseline {baseline.avg_one_touch_pct:.0f}%. "
                    f"More extra touches than usual."
                ),
                metric="one_touch_pct", value=session.one_touch_pct,
                baseline=baseline.avg_one_touch_pct, delta_pct=ot_delta,
            ))
        elif ot_delta > 10:
            flags.append(TechnicalFlag(
                severity=Severity.INFO, category="quality",
                message=(
                    f"One-touch play up: {session.one_touch_pct:.0f}% vs "
                    f"baseline {baseline.avg_one_touch_pct:.0f}%. Sharp awareness."
                ),
                metric="one_touch_pct", value=session.one_touch_pct,
                baseline=baseline.avg_one_touch_pct, delta_pct=ot_delta,
            ))

    # --- Touch volume (normalized for session type) ---
    if baseline.avg_touches_per_session > 0:
        normalized_touches = session.total_touches / norm["touch_factor"]
        touch_delta_pct = ((normalized_touches - baseline.avg_touches_per_session)
                           / baseline.avg_touches_per_session) * 100
        if touch_delta_pct < -35:
            flags.append(TechnicalFlag(
                severity=Severity.MONITOR, category="quality",
                message=(
                    f"Low involvement: {session.total_touches} touches "
                    f"(normalized: {normalized_touches:.0f}) vs baseline "
                    f"{baseline.avg_touches_per_session:.0f}. "
                    f"{touch_delta_pct:.0f}% below normal."
                ),
                metric="touches", value=session.total_touches,
                baseline=baseline.avg_touches_per_session, delta_pct=touch_delta_pct,
            ))

    # v2: --- Passing accuracy (if available) ---
    if session.successful_passes is not None and session.total_passes and session.total_passes > 5:
        pass_pct = (session.successful_passes / session.total_passes) * 100
        if pass_pct < 70:
            flags.append(TechnicalFlag(
                severity=Severity.MONITOR, category="quality",
                message=(
                    f"Passing accuracy low: {pass_pct:.0f}% "
                    f"({session.successful_passes}/{session.total_passes}). "
                    f"Check decision-making under pressure."
                ),
                metric="pass_accuracy", value=pass_pct,
                baseline=0, delta_pct=0,
            ))

    # v2: --- Turnovers (if available) ---
    if session.turnovers is not None and session.total_touches > 0:
        turnover_rate = session.turnovers / session.total_touches * 100
        if turnover_rate > 8:
            flags.append(TechnicalFlag(
                severity=Severity.MONITOR, category="quality",
                message=(
                    f"High turnover rate: {turnover_rate:.1f}% "
                    f"({session.turnovers} turnovers in {session.total_touches} touches). "
                    f"Losing possession more than expected."
                ),
                metric="turnover_rate", value=turnover_rate,
                baseline=0, delta_pct=0,
            ))

    return flags


# ============================================================
# v2: FATIGUE COMPOSITE SCORE
# ============================================================

def calculate_fatigue_composite(
    session: TechnicalSessionData,
    baseline: TechnicalBaseline
) -> tuple:
    """
    Composite fatigue score based on multiple technical metrics.

    When a player is fatigued, multiple signals drop simultaneously:
    - Kick velocity drops (neuromuscular fatigue)
    - Top speed drops (CNS fatigue)
    - Time-to-release increases (cognitive fatigue)
    - One-touch % drops (processing speed)
    - Work rate drops (aerobic fatigue)

    Each metric contributes to a composite score (0-100).
    Source: Recovery Protocols doc — multi-signal fatigue detection
    is more reliable than any single metric.

    Returns: (score, contributing_signals)
    """
    signals = []
    penalties = 0
    max_penalty = 0

    # Kick velocity vs baseline
    if baseline.avg_kick_velocity_kmh > 0:
        delta = ((session.kick_velocity_avg_kmh - baseline.avg_kick_velocity_kmh)
                 / baseline.avg_kick_velocity_kmh) * 100
        max_penalty += 25
        if delta < -15:
            penalties += 25
            signals.append(f"Kick velocity {delta:.0f}% below baseline")
        elif delta < -8:
            penalties += 12
            signals.append(f"Kick velocity {delta:.0f}% below baseline (mild)")

    # Top speed vs baseline
    if baseline.avg_top_speed_kmh > 0:
        delta = ((session.top_speed_kmh - baseline.avg_top_speed_kmh)
                 / baseline.avg_top_speed_kmh) * 100
        max_penalty += 25
        if delta < -10:
            penalties += 25
            signals.append(f"Top speed {delta:.0f}% below baseline")
        elif delta < -5:
            penalties += 10
            signals.append(f"Top speed {delta:.0f}% below baseline (mild)")

    # Time to release vs baseline
    if baseline.avg_time_to_release_sec > 0 and session.num_possessions >= MIN_POSSESSIONS_FOR_RELEASE:
        delta_sec = session.time_to_release_sec - baseline.avg_time_to_release_sec
        max_penalty += 20
        if delta_sec > 0.4:
            penalties += 20
            signals.append(f"Decision speed +{delta_sec:.1f}s slower")
        elif delta_sec > 0.2:
            penalties += 8
            signals.append(f"Decision speed +{delta_sec:.1f}s slower (mild)")

    # Work rate vs baseline
    if baseline.avg_work_rate > 0:
        delta = ((session.work_rate - baseline.avg_work_rate)
                 / baseline.avg_work_rate) * 100
        max_penalty += 20
        if delta < -15:
            penalties += 20
            signals.append(f"Work rate {delta:.0f}% below baseline")
        elif delta < -8:
            penalties += 8
            signals.append(f"Work rate {delta:.0f}% below baseline (mild)")

    # One-touch %
    if baseline.avg_one_touch_pct > 0 and session.num_possessions >= MIN_POSSESSIONS_FOR_RELEASE:
        delta = session.one_touch_pct - baseline.avg_one_touch_pct
        max_penalty += 10
        if delta < -15:
            penalties += 10
            signals.append(f"One-touch play down {abs(delta):.0f}pp")
        elif delta < -8:
            penalties += 4
            signals.append(f"One-touch play down {abs(delta):.0f}pp (mild)")

    # Calculate score (100 = fresh, 0 = exhausted)
    if max_penalty > 0:
        score = max(0, 100 - (penalties / max_penalty * 100))
    else:
        score = 100  # no data to judge

    return score, signals


# ============================================================
# v2: INJURY EARLY WARNING
# ============================================================

def check_injury_signals(
    session: TechnicalSessionData,
    baseline: TechnicalBaseline,
    position: str = "FB"
) -> list:
    """
    Multi-metric injury early warning system.

    Key insight: No single metric predicts injury. But COMBINATIONS do.
    Source: Injury Prevention Protocol doc — load spikes + neuromuscular
    fatigue + asymmetry = high-risk combination.

    Returns: list of TechnicalFlag with severity CRITICAL or WARNING
    """
    warnings = []
    risk_signals = 0

    # Signal 1: Velocity drop + high decel load
    # A player who is slower but still decelerating hard = muscles under stress
    # they can't adequately handle
    vel_drop = False
    if baseline.avg_kick_velocity_kmh > 0:
        vel_delta = ((session.kick_velocity_avg_kmh - baseline.avg_kick_velocity_kmh)
                     / baseline.avg_kick_velocity_kmh) * 100
        if vel_delta < -10:
            vel_drop = True
            risk_signals += 1

    high_decel = False
    if baseline.avg_decelerations > 0 and session.decelerations > baseline.avg_decelerations * 1.3:
        high_decel = True
        risk_signals += 1

    if vel_drop and high_decel:
        warnings.append(TechnicalFlag(
            severity=Severity.WARNING, category="injury_warning",
            message=(
                f"COMBINATION RISK: Kick velocity dropped while deceleration load is high. "
                f"Muscles are under eccentric stress while showing fatigue signs. "
                f"Avoid heavy lower body and max-velocity work for 48h. "
                f"Prioritize eccentric hamstring maintenance (Nordic curls, controlled only)."
            ),
            metric="velocity_decel_combo",
            value=session.kick_velocity_avg_kmh,
            baseline=baseline.avg_kick_velocity_kmh,
            delta_pct=vel_delta if vel_drop else 0,
        ))

    # Signal 2: Speed drop + high sprint volume
    # Running a lot but slower = pushing through fatigue
    speed_drop = False
    if baseline.avg_top_speed_kmh > 0:
        speed_delta = ((session.top_speed_kmh - baseline.avg_top_speed_kmh)
                       / baseline.avg_top_speed_kmh) * 100
        if speed_delta < -8:
            speed_drop = True
            risk_signals += 1

    high_sprint = False
    if baseline.avg_sprint_distance_m > 0 and session.sprint_distance_m > baseline.avg_sprint_distance_m * 1.3:
        high_sprint = True
        risk_signals += 1

    if speed_drop and high_sprint:
        warnings.append(TechnicalFlag(
            severity=Severity.WARNING, category="injury_warning",
            message=(
                f"COMBINATION RISK: Top speed down {speed_delta:.0f}% but sprint volume "
                f"up {((session.sprint_distance_m/baseline.avg_sprint_distance_m)-1)*100:.0f}%. "
                f"Running more distance at lower quality — hamstring strain risk elevated. "
                f"Source: >70% of hamstring tears occur during high-speed running "
                f"when neuromuscular capacity is reduced."
            ),
            metric="speed_sprint_combo",
            value=session.top_speed_kmh,
            baseline=baseline.avg_top_speed_kmh,
            delta_pct=speed_delta,
        ))

    # Signal 3: Asymmetry spike
    # Sudden increase in L/R imbalance can indicate protective movement pattern
    # (subconscious favoring = something hurts)
    if session.kick_velocity_left_kmh and session.kick_velocity_right_kmh:
        current_asym = abs(session.kick_velocity_left_kmh - session.kick_velocity_right_kmh) \
                       / max(session.kick_velocity_left_kmh, session.kick_velocity_right_kmh) * 100
        baseline_asym = 0
        if baseline.avg_kick_velocity_left_kmh and baseline.avg_kick_velocity_right_kmh:
            baseline_asym = abs(baseline.avg_kick_velocity_left_kmh - baseline.avg_kick_velocity_right_kmh) \
                            / max(baseline.avg_kick_velocity_left_kmh, baseline.avg_kick_velocity_right_kmh) * 100

        if current_asym > baseline_asym + 15:
            risk_signals += 1
            weaker = "left" if session.kick_velocity_left_kmh < session.kick_velocity_right_kmh else "right"
            warnings.append(TechnicalFlag(
                severity=Severity.WARNING, category="injury_warning",
                message=(
                    f"ASYMMETRY SPIKE: Kick velocity asymmetry jumped from "
                    f"{baseline_asym:.0f}% to {current_asym:.0f}%. "
                    f"{weaker.capitalize()} foot significantly weaker than usual. "
                    f"This may indicate subconscious protection of the {weaker} leg. "
                    f"Check for groin, hip flexor, or ankle discomfort."
                ),
                metric="velocity_asymmetry_spike",
                value=current_asym, baseline=baseline_asym,
                delta_pct=current_asym - baseline_asym,
            ))

    # Signal 4: Multi-signal compound risk
    if risk_signals >= 3:
        warnings.append(TechnicalFlag(
            severity=Severity.CRITICAL, category="injury_warning",
            message=(
                f"MULTI-SIGNAL ALERT: {risk_signals} injury risk signals active simultaneously. "
                f"Reduce training intensity immediately. Consult with physio/S&C coach before "
                f"next high-intensity session. This combination has the highest predictive "
                f"value for soft-tissue injury."
            ),
            metric="compound_risk", value=float(risk_signals),
            baseline=0, delta_pct=0,
        ))

    return warnings


# ============================================================
# RECOMMENDATIONS (v2: expanded)
# ============================================================

def generate_recommendations(
    session: TechnicalSessionData,
    baseline: TechnicalBaseline,
    balance_class: str,
    balance_pct: float,
    quality_flags: list,
    fatigue_score: float,
    injury_warnings: list,
    position: str = "FB"
) -> list:
    """v2: More specific, actionable, and position-aware recommendations."""
    recs = []

    # Injury warnings override everything
    if any(f.severity == Severity.CRITICAL for f in injury_warnings):
        recs.append(
            "IMMEDIATE: Multiple injury risk signals detected. "
            "Reduce next session to active recovery or technical-only at low intensity. "
            "Do NOT sprint or perform maximal efforts until signals normalize."
        )
        return recs  # Don't dilute critical advice with development tips

    # Fatigue-based recommendations
    if fatigue_score < 40:
        recs.append(
            "FATIGUE DETECTED: Technical performance significantly below baseline across "
            "multiple metrics. Next session should be reduced intensity. "
            "Focus on recovery: sleep, nutrition, and light movement."
        )
    elif fatigue_score < 65:
        recs.append(
            "MILD FATIGUE: Some technical metrics below baseline. "
            "Training is fine but avoid maximal efforts. Good day for tactical work."
        )

    # Balance
    if balance_class in ("left_dominant", "right_dominant"):
        weak_foot = "right" if balance_class == "left_dominant" else "left"
        dominant_pct = max(balance_pct, 100 - balance_pct)

        if dominant_pct > 75:
            recs.append(
                f"WEAK FOOT PRIORITY: {weak_foot.capitalize()} foot used only "
                f"{100-dominant_pct:.0f}% of touches. "
                f"Add 10-15 min {weak_foot}-foot-only work per individual session: "
                f"wall passes, rondos (weak foot only), crossing ({weak_foot}), "
                f"and finishing from the {weak_foot} side."
            )
        elif dominant_pct > 60:
            recs.append(
                f"BALANCE: {dominant_pct:.0f}/{100-dominant_pct:.0f} split. "
                f"Consciously seek {weak_foot}-foot options in team sessions."
            )

    # Position-specific
    pos_recs = {
        "FB": (
            "FULLBACK FOCUS: Track crossing accuracy and first-touch quality under press. "
            "As a modern fullback, your value in buildup depends on comfort with both feet."
        ),
        "CB": (
            "CENTRE-BACK FOCUS: Distribution quality under pressure is your technical differentiator. "
            "Track passing accuracy and progressive passes (forward passes into midfield/attack)."
        ),
        "CM": (
            "CENTRAL MID FOCUS: Time-to-release is your primary technical KPI. "
            "Faster processing = better tempo for the team. Target: <1.5s average."
        ),
        "W": (
            "WINGER FOCUS: 1v1 success rate and crossing quality define your position. "
            "Track dribble success and how often you beat your defender."
        ),
        "ST": (
            "STRIKER FOCUS: Finishing under fatigue is the differentiator. "
            "Monitor kick velocity in the last 20 min vs first 20 min of sessions."
        ),
        "AM": (
            "ATTACKING MID FOCUS: Creative passing under pressure separates good from great. "
            "Track through-ball attempts and final-third involvement."
        ),
        "GK": (
            "GOALKEEPER FOCUS: Distribution accuracy with both feet is increasingly critical. "
            "Track L/R balance specifically for goal kicks and build-up passes."
        ),
    }
    if position in pos_recs:
        recs.append(pos_recs[position])

    # Quality-based specific recommendations
    velocity_dropped = any(f.metric == "kick_velocity" and f.delta_pct < -10
                           for f in quality_flags if hasattr(f, 'delta_pct'))
    slow_release = any(f.metric == "time_to_release" for f in quality_flags
                       if hasattr(f, 'severity') and f.severity in (Severity.WARNING, Severity.MONITOR))

    if velocity_dropped and not any(f.severity == Severity.CRITICAL for f in injury_warnings):
        recs.append(
            "POWER OUTPUT: Kick velocity below baseline. If this persists for 2+ sessions: "
            "check hamstring/hip flexor tightness, review sleep quality, and consider "
            "reducing lower body training volume for one microcycle."
        )

    if slow_release:
        recs.append(
            "DECISION SPEED: Time-to-release elevated. "
            "Add small-sided games with constraints (2-touch max, 3-second possession limit) "
            "to train processing speed under pressure."
        )

    return recs


# ============================================================
# MAIN ANALYSIS FUNCTION (v2)
# ============================================================

def analyze_technical_session(
    session: TechnicalSessionData,
    baseline: TechnicalBaseline,
    position: str = "FB"
) -> TechnicalAnalysis:
    """
    v2 master function. Full analysis pipeline.
    """
    # Data quality check
    data_quality, data_notes = check_data_quality(session, baseline)

    # Balance
    balance_class, balance_pct, balance_flags = analyze_balance(session, baseline, position)

    # Balance trend
    current_dist = abs(balance_pct - 50) if balance_pct > 0 else 50
    baseline_dist = abs(baseline.avg_touch_balance_pct - 50)
    if current_dist < baseline_dist - 3:
        balance_trend = "improving"
    elif current_dist > baseline_dist + 3:
        balance_trend = "declining"
    else:
        balance_trend = "stable"

    # Override with multi-session trend if available
    if baseline.recent_balance_trend:
        balance_trend = baseline.recent_balance_trend

    # Quality
    quality_flags = analyze_quality(session, baseline)

    # Physical flags
    physical_flags = []
    if baseline.avg_decelerations > 0 and session.decelerations > baseline.avg_decelerations * 1.3:
        physical_flags.append(TechnicalFlag(
            severity=Severity.MONITOR, category="physical",
            message=(
                f"High deceleration count: {session.decelerations} vs baseline "
                f"{baseline.avg_decelerations:.0f}. Cross-reference with GPS vest. "
                f"Eccentric load elevated."
            ),
            metric="decelerations", value=float(session.decelerations),
            baseline=baseline.avg_decelerations, delta_pct=0,
        ))

    if baseline.avg_sprint_distance_m > 0 and session.sprint_distance_m > baseline.avg_sprint_distance_m * 1.3:
        delta_pct = ((session.sprint_distance_m / baseline.avg_sprint_distance_m) - 1) * 100
        physical_flags.append(TechnicalFlag(
            severity=Severity.MONITOR, category="physical",
            message=(
                f"High sprint volume: {session.sprint_distance_m:.0f}m vs baseline "
                f"{baseline.avg_sprint_distance_m:.0f}m (+{delta_pct:.0f}%)."
            ),
            metric="sprint_distance", value=session.sprint_distance_m,
            baseline=baseline.avg_sprint_distance_m, delta_pct=delta_pct,
        ))

    # v2: Dribble analysis
    if session.dribble_distance_m and session.dribble_count and session.dribble_count > 0:
        avg_carry = session.dribble_distance_m / session.dribble_count
        if avg_carry > 15:
            physical_flags.append(TechnicalFlag(
                severity=Severity.INFO, category="quality",
                message=(
                    f"Progressive carrying: {session.dribble_count} carries, "
                    f"avg {avg_carry:.0f}m per carry. Good ball progression."
                ),
                metric="dribble_carry", value=avg_carry,
                baseline=0, delta_pct=0,
            ))

    # Fatigue composite
    fatigue_score, fatigue_signals = calculate_fatigue_composite(session, baseline)

    # Injury early warning
    injury_warnings = check_injury_signals(session, baseline, position)

    # Recommendations
    recommendations = generate_recommendations(
        session, baseline, balance_class, balance_pct,
        quality_flags, fatigue_score, injury_warnings, position
    )

    # Baseline comparison
    vs_baseline = {
        "touches": {
            "today": session.total_touches,
            "baseline": baseline.avg_touches_per_session,
            "delta_pct": ((session.total_touches - baseline.avg_touches_per_session)
                          / baseline.avg_touches_per_session * 100)
                         if baseline.avg_touches_per_session > 0 else 0,
        },
        "kick_velocity": {
            "today": session.kick_velocity_avg_kmh,
            "baseline": baseline.avg_kick_velocity_kmh,
            "delta_pct": ((session.kick_velocity_avg_kmh - baseline.avg_kick_velocity_kmh)
                          / baseline.avg_kick_velocity_kmh * 100)
                         if baseline.avg_kick_velocity_kmh > 0 else 0,
        },
        "time_to_release": {
            "today": session.time_to_release_sec,
            "baseline": baseline.avg_time_to_release_sec,
            "delta_sec": session.time_to_release_sec - baseline.avg_time_to_release_sec,
        },
        "balance": {
            "today_left_pct": balance_pct,
            "baseline_left_pct": baseline.avg_touch_balance_pct,
            "trend": balance_trend,
        },
        "top_speed": {
            "today": session.top_speed_kmh,
            "baseline": baseline.avg_top_speed_kmh,
            "delta_pct": ((session.top_speed_kmh - baseline.avg_top_speed_kmh)
                          / baseline.avg_top_speed_kmh * 100)
                         if baseline.avg_top_speed_kmh > 0 else 0,
        },
        "fatigue_composite": {
            "score": fatigue_score,
            "signals": fatigue_signals,
        },
    }

    return TechnicalAnalysis(
        left_right_balance=balance_class,
        balance_pct=balance_pct,
        balance_trend=balance_trend,
        balance_flags=balance_flags,
        quality_flags=quality_flags,
        physical_flags=physical_flags,
        fatigue_composite_score=fatigue_score,
        fatigue_signals=fatigue_signals,
        injury_warnings=injury_warnings,
        recommendations=recommendations,
        vs_baseline=vs_baseline,
        data_quality=data_quality,
        data_quality_notes=data_notes,
    )


# ============================================================
# DATABASE SCHEMA (for CLAUDE.md reference)
# ============================================================
"""
-- Playermaker technical session data (v2)
CREATE TABLE technical_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    session_type TEXT,               -- match, team_training, individual, drill
    duration_min REAL,
    -- Physical (boot-measured)
    total_distance_m REAL,
    sprint_distance_m REAL,
    num_sprints INTEGER,
    top_speed_kmh REAL,
    accelerations INTEGER,
    decelerations INTEGER,
    work_rate REAL,                  -- m/min
    -- Technical
    total_touches INTEGER,
    touches_left INTEGER,
    touches_right INTEGER,
    kick_velocity_max_kmh REAL,
    kick_velocity_avg_kmh REAL,
    kick_velocity_left_kmh REAL,     -- v2: per-foot
    kick_velocity_right_kmh REAL,    -- v2: per-foot
    time_on_ball_sec REAL,
    num_possessions INTEGER,
    avg_possession_duration_sec REAL,
    one_touch_pct REAL,
    time_to_release_sec REAL,
    first_touch_quality REAL,
    dribble_distance_m REAL,
    dribble_count INTEGER,           -- v2
    successful_passes INTEGER,       -- v2
    total_passes INTEGER,            -- v2
    turnovers INTEGER                -- v2
);
"""


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    # Fatigued session sample — should trigger multiple warnings
    session = TechnicalSessionData(
        date="2026-07-15",
        session_type="team_training",
        duration_min=90,
        total_distance_m=7800,
        sprint_distance_m=720,       # high sprint volume
        num_sprints=14,
        top_speed_kmh=26.8,          # speed drop
        accelerations=35,
        decelerations=44,            # high
        work_rate=62.0,              # low work rate
        total_touches=58,
        touches_left=15,
        touches_right=43,
        kick_velocity_max_kmh=88.0,
        kick_velocity_avg_kmh=62.5,  # big velocity drop
        kick_velocity_left_kmh=55.0,
        kick_velocity_right_kmh=70.0,
        time_on_ball_sec=38.2,
        num_possessions=28,
        avg_possession_duration_sec=1.4,
        one_touch_pct=30.0,          # low
        time_to_release_sec=1.9,     # slow
        turnovers=6,
        successful_passes=18,
        total_passes=24,
    )

    baseline = TechnicalBaseline(
        avg_touches_per_session=72,
        avg_touch_balance_pct=35.0,
        avg_kick_velocity_kmh=75.1,
        avg_kick_velocity_left_kmh=65.0,
        avg_kick_velocity_right_kmh=72.0,
        avg_time_on_ball_sec=52.0,
        avg_time_to_release_sec=1.4,
        avg_one_touch_pct=42.0,
        avg_top_speed_kmh=29.2,
        avg_sprint_distance_m=520,
        avg_decelerations=32,
        avg_work_rate=72.0,
        sessions_count=18,
        sd_kick_velocity=4.2,
    )

    result = analyze_technical_session(session, baseline, position="FB")

    print("=" * 60)
    print("TECHNICAL ANALYSIS v2.0 — FATIGUED SESSION TEST")
    print("=" * 60)
    print(f"\nDATA QUALITY: {result.data_quality}")
    for n in result.data_quality_notes:
        print(f"  {n}")

    print(f"\nBALANCE: {result.left_right_balance} ({result.balance_pct:.0f}% left) — trend: {result.balance_trend}")
    for f in result.balance_flags:
        print(f"  [{f.severity.value}] {f.message}")

    print(f"\nFATIGUE COMPOSITE: {result.fatigue_composite_score:.0f}/100")
    for s in result.fatigue_signals:
        print(f"  - {s}")

    print(f"\nQUALITY FLAGS:")
    for f in result.quality_flags:
        print(f"  [{f.severity.value}] {f.message}")

    print(f"\nPHYSICAL FLAGS:")
    for f in result.physical_flags:
        print(f"  [{f.severity.value}] {f.message}")

    print(f"\nINJURY WARNINGS:")
    for f in result.injury_warnings:
        print(f"  [{f.severity.value}] {f.message}")

    print(f"\nRECOMMENDATIONS:")
    for r in result.recommendations:
        print(f"  → {r}")
