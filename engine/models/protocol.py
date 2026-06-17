"""
Performance OS — Protocol Selector (engine/models/protocol.py)

RULE-BASED DECISION ENGINE. No LLM. No API calls. Deterministic.

Every rule is sourced from evidence-based sports science literature.
Source references are included as comments for academic validation.

Input: Daily calculation results from calculate.py
Output: Structured protocol dict that Layer 2 (Claude) formats into natural language.
"""

from dataclasses import dataclass, field
from typing import Optional


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class DailyData:
    """All calculated values from Layer 1, passed in from calculate.py."""
    # Readiness
    adjusted_readiness: int          # 0-100 (from readiness.py)
    whoop_recovery: int              # 0-100 raw
    discrepancy: int                 # whoop - subjective (from discrepancy.py)

    # ACWR
    acwr: float                      # ratio (from acwr.py)
    acwr_zone: str                   # optimal | spike | detraining

    # Subjective
    checkin: str                     # yes | limited | no
    checkin_reason: str              # soreness | fatigue | mental | sleep | none
    rpe_yesterday: Optional[float]   # 1-10 from yesterday's session

    # Whoop vitals
    hrv: float                       # ms
    hrv_baseline: float              # 28-day avg
    rhr: float                       # bpm
    rhr_baseline: float              # 28-day avg
    sleep_hours: float
    sleep_efficiency: float          # %

    # GPS (from STATSports, if available)
    gps_available: bool = False
    total_distance_m: Optional[float] = None
    hsr_m: Optional[float] = None
    hid_m: Optional[float] = None
    decelerations: Optional[int] = None
    decel_7day_avg: Optional[float] = None
    sprints: Optional[int] = None
    max_speed_kmh: Optional[float] = None

    # Bloodwork context (periodic, may be None)
    ferritin: Optional[float] = None       # ng/mL
    vitamin_d: Optional[float] = None      # ng/mL
    omega3_index: Optional[float] = None   # %
    cortisol: Optional[float] = None       # nmol/L
    ck: Optional[float] = None             # U/L

    # Context
    match_day_offset: Optional[int] = None  # MD-1, MD+1 etc. None if no match context
    match_strain: Optional[float] = None    # Whoop strain or STATSports strain from the match itself
    position: str = "FB"                    # GK|CB|FB|CM|AM|W|ST
    session_type_today: Optional[str] = None  # planned session type
    returning_from_injury: bool = False      # first 4 weeks post-injury = tighter thresholds
    active_negative_flags: int = 0           # counted by generate_flags(), used for interaction check


@dataclass
class ProtocolOutput:
    """Structured output passed to Layer 2 for natural language formatting."""
    # Core recommendation
    training_recommendation: str     # full_intensity | reduced | active_recovery | rest
    recommendation_reasons: list     # list of reason strings
    confidence: str                  # high | moderate | low

    # Flags and warnings
    flags: list = field(default_factory=list)           # warning strings
    bloodwork_flags: list = field(default_factory=list)  # periodic context

    # Recovery protocol
    recovery_protocol: list = field(default_factory=list)  # ordered list of actions

    # Match day specific
    match_day_protocol: Optional[dict] = None


# ============================================================
# CORE DECISION RULES
# ============================================================

def select_training_recommendation(data: DailyData) -> tuple[str, list, str]:
    """
    Select training intensity recommendation from predefined options.
    Returns: (recommendation, reasons, confidence)

    Decision hierarchy (order matters — first match wins):
    1. Injury/illness override
    2. ACWR danger zone
    3. Match day protocols
    4. Readiness-based selection
    5. Default

    Sources:
    - ACWR thresholds: Gabbett 2016, Injury Prevention Protocol doc
    - Readiness integration: Buchheit 2014, HRV doc
    - Match day logic: Match Day Protocol doc, Recovery Protocols doc
    """
    reasons = []
    confidence = "high"

    # --- Rule 1: ACWR Danger Zone (override everything) ---
    # Source: Injury Prevention Protocol §6, ACWR table
    if data.acwr > 1.5:
        reasons.append(f"ACWR at {data.acwr:.2f} — danger zone (>1.5). Very high injury risk.")
        return "rest", reasons, "high"

    if data.acwr > 1.3:
        reasons.append(f"ACWR at {data.acwr:.2f} — caution zone (1.3-1.5). Moderately elevated injury risk.")
        # Don't return yet — combine with readiness

    # --- Rule 2: Match Day Protocols ---
    # Source: Match Day Protocol doc §2-4
    if data.match_day_offset is not None:
        return _match_day_protocol(data, reasons)

    # --- Rule 3: Subjective override ---
    # Source: HRV doc §4.1 — individual perception is valid signal
    if data.checkin == "no":
        reasons.append(f"Subjective check-in: 'no'. Body says not ready.")
        if data.checkin_reason == "soreness":
            reasons.append("Reason: muscle soreness — likely DOMS or eccentric overload.")
        elif data.checkin_reason == "fatigue":
            reasons.append("Reason: general fatigue — CNS or sleep-related.")
        elif data.checkin_reason == "mental":
            reasons.append("Reason: mental/stress — psychological load affecting readiness.")
        return "active_recovery", reasons, "high"

    # --- Rule 4: Readiness-based selection ---
    if data.adjusted_readiness >= 75:
        if data.acwr_zone == "optimal":
            reasons.append(f"Adjusted readiness {data.adjusted_readiness}% + ACWR optimal ({data.acwr:.2f}).")
            return "full_intensity", reasons, "high"
        elif data.acwr > 1.3:
            reasons.append(f"Readiness high ({data.adjusted_readiness}%) but ACWR elevated ({data.acwr:.2f}). Reduce volume, maintain intensity.")
            return "reduced", reasons, "moderate"

    elif data.adjusted_readiness >= 50:
        reasons.append(f"Adjusted readiness moderate ({data.adjusted_readiness}%).")
        if data.checkin == "limited":
            reasons.append(f"Subjective: limited ({data.checkin_reason}).")
        return "reduced", reasons, "moderate"

    elif data.adjusted_readiness >= 30:
        reasons.append(f"Adjusted readiness low ({data.adjusted_readiness}%). Active recovery only.")
        return "active_recovery", reasons, "high"

    else:
        reasons.append(f"Adjusted readiness very low ({data.adjusted_readiness}%). Full rest recommended.")
        return "rest", reasons, "high"

    # Default fallback
    reasons.append("No clear signal — defaulting to reduced intensity.")
    return "reduced", reasons, "low"


def _match_day_protocol(data: DailyData, reasons: list) -> tuple[str, list, str]:
    """
    Match-day specific protocols.
    Source: Match Day Protocol doc §2-4, Recovery Protocols doc
    """
    offset = data.match_day_offset

    if offset == -1:  # MD-1
        reasons.append("MD-1: Activation day. CNS must be fresh for match.")
        reasons.append("No heavy training. Short activation + set pieces only.")
        return "reduced", reasons, "high"

    elif offset == -2:  # MD-2
        reasons.append("MD-2: Last training stimulus before match.")
        reasons.append("Moderate intensity, tactical focus. Avoid excessive volume.")
        return "reduced", reasons, "high"

    elif offset == 1:  # MD+1
        # Source: Recovery Protocols doc §4
        reasons.append("MD+1: Primary recovery day. No explosive or high-intensity work.")
        reasons.append("Active recovery: 20-30min at 50-60% HRmax (cycle, swim, walk).")
        return "active_recovery", reasons, "high"

    elif offset == 2:  # MD+2
        reasons.append("MD+2: CK peaks at 48h post-match. Neuromuscular system still recovering.")
        if data.adjusted_readiness >= 60:
            reasons.append("Readiness acceptable — light gym session possible (no maximal loads).")
            return "reduced", reasons, "moderate"
        else:
            reasons.append("Readiness still low — continue active recovery.")
            return "active_recovery", reasons, "high"

    elif offset == 3:  # MD+3 — intensity-dependent
        # Source: Recovery Protocols doc — CK normalizes 48-72h but functional recovery varies
        # Match strain determines whether MD+3 is return-to-full or still reduced
        high_intensity_match = False
        if data.match_strain is not None and data.match_strain > 15:
            high_intensity_match = True
        # Also check: if GPS data available from match, use HID as intensity proxy
        if data.gps_available and data.hid_m is not None and data.hid_m > 2000:
            high_intensity_match = True

        if high_intensity_match:
            reasons.append("MD+3: Match was high-intensity (strain >15 or HID >2000m).")
            if data.adjusted_readiness >= 65:
                reasons.append("Readiness recovering — moderate session possible. Avoid max velocity sprints.")
                return "reduced", reasons, "moderate"
            else:
                reasons.append("Readiness still depressed after intense match. One more recovery day.")
                return "active_recovery", reasons, "high"
        else:
            reasons.append("MD+3: Match was moderate intensity. Normal recovery timeline.")
            if data.adjusted_readiness >= 60:
                reasons.append("Readiness sufficient — return to normal training.")
                return "full_intensity", reasons, "moderate"
            else:
                reasons.append("Readiness still low despite moderate match. Reduced intensity.")
                return "reduced", reasons, "moderate"

    else:  # MD-3, MD-4, MD-5 etc.
        reasons.append(f"MD{offset:+d}: Normal training day within match week.")
        # Fall through to readiness-based logic
        if data.adjusted_readiness >= 70:
            return "full_intensity", reasons, "high"
        else:
            return "reduced", reasons, "moderate"


# ============================================================
# FLAG GENERATORS
# ============================================================

def generate_flags(data: DailyData) -> list:
    """
    Generate warning flags based on thresholds.
    Each flag is a string that Layer 2 includes in the report.
    """
    flags = []

    # --- ACWR flags ---
    # Source: Injury Prevention Protocol §6
    if data.acwr > 1.3:
        flags.append(f"⚠ ACWR SPIKE: {data.acwr:.2f} — week-to-week load increase too high. Injury risk elevated.")
    if data.acwr < 0.8:
        flags.append(f"⚠ ACWR LOW: {data.acwr:.2f} — detraining zone. Gradually increase load to avoid deconditioning.")

    # --- Discrepancy flag ---
    # Source: Core thesis — Whoop scores can be misleading
    if abs(data.discrepancy) > 20:
        direction = "over-estimating" if data.discrepancy > 0 else "under-estimating"
        flags.append(f"⚠ DISCREPANCY: Whoop is {direction} by {abs(data.discrepancy)} points. Trust adjusted score.")

    # --- HRV trend flag ---
    # Source: HRV doc §4.1, Buchheit diagnostic matrix
    hrv_delta_pct = ((data.hrv - data.hrv_baseline) / data.hrv_baseline) * 100
    if hrv_delta_pct < -10:
        flags.append(f"⚠ HRV DROP: {hrv_delta_pct:.0f}% below baseline. Possible overreaching or acute stress.")
    # Source: HRV doc §4.2 — parasympathetic saturation
    if data.hrv > data.hrv_baseline * 1.3 and data.rhr < data.rhr_baseline - 5:
        flags.append("⚠ POSSIBLE SATURATION: HRV very high + RHR very low. May indicate parasympathetic saturation, not optimal recovery.")

    # --- Sleep flags ---
    # Source: Recovery Protocols doc §2
    if data.sleep_hours < 6:
        flags.append(f"⚠ SLEEP CRITICAL: {data.sleep_hours:.1f}h — well below 8-9h target. Sprint performance, reaction time, and decision-making impaired.")
    elif data.sleep_hours < 7:
        flags.append(f"⚠ SLEEP LOW: {data.sleep_hours:.1f}h — below optimal. GH secretion and CNS restoration compromised.")

    # --- Deceleration load flag ---
    # Source: Injury Prevention Protocol §5, Position Demands doc
    if data.gps_available and data.decelerations:
        # Relative threshold: >130% of personal 7-day avg
        if data.decel_7day_avg and data.decelerations > data.decel_7day_avg * 1.3:
            flags.append(f"⚠ HIGH DECEL LOAD (relative): {data.decelerations} decelerations vs 7-day avg {data.decel_7day_avg:.0f}. Eccentric muscle stress elevated. Avoid heavy lower body work for 48h.")

        # Absolute threshold: position-specific
        # Source: Position Specific Demands doc — different positions have different normal ranges
        pos_decel_limits = {
            "GK": 15, "CB": 30, "FB": 45, "CM": 40,
            "AM": 40, "W": 50, "ST": 40,
        }
        pos_limit = pos_decel_limits.get(data.position, 40)
        if data.decelerations > pos_limit:
            flags.append(f"⚠ HIGH DECEL LOAD (absolute): {data.decelerations} exceeds position norm for {data.position} (>{pos_limit}). Elevated eccentric injury risk.")

    # --- RPE flag ---
    if data.rpe_yesterday and data.rpe_yesterday >= 9:
        flags.append(f"⚠ HIGH RPE: Yesterday's session rated {data.rpe_yesterday}/10. Consider reduced intensity today.")

    return flags


def generate_bloodwork_flags(data: DailyData) -> list:
    """
    Periodic bloodwork context flags. Only generated when bloodwork data exists.
    Source: Bloodwork panel design, Performance Nutrition Blueprint
    """
    flags = []

    if data.ferritin is not None:
        if data.ferritin < 30:
            flags.append(f"🩸 FERRITIN LOW: {data.ferritin} ng/mL — below clinical range. Iron supplementation likely needed. Consult physician.")
        elif data.ferritin < 50:
            flags.append(f"🩸 FERRITIN SUBOPTIMAL: {data.ferritin} ng/mL — below athlete target (>50). Optimize iron intake: vitamin C with iron-rich meals.")

    if data.vitamin_d is not None and data.vitamin_d < 50:
        flags.append(f"🩸 VITAMIN D: {data.vitamin_d} ng/mL — below athlete target (>50). Continue supplementation (4000 IU). Retest in 3 months.")

    if data.omega3_index is not None and data.omega3_index < 8.0:
        flags.append(f"🩸 OMEGA-3 INDEX: {data.omega3_index}% — below target (>8%). Continue EPA/DHA supplementation (2g/day).")

    if data.cortisol is not None and data.cortisol > 500:
        flags.append(f"🩸 CORTISOL ELEVATED: {data.cortisol} nmol/L — upper range. Monitor for overtraining signs. Prioritize sleep and stress management.")

    if data.ck is not None and data.ck > 500:
        if data.match_day_offset and data.match_day_offset in [1, 2]:
            flags.append(f"🩸 CK ELEVATED: {data.ck} U/L — expected 24-72h post-match. No action needed, will normalize.")
        else:
            flags.append(f"🩸 CK ELEVATED: {data.ck} U/L — outside match window. Possible accumulated muscle damage. Consider reducing eccentric load.")

    return flags


# ============================================================
# RECOVERY PROTOCOL SELECTOR
# ============================================================

def select_recovery_protocol(data: DailyData) -> list:
    """
    Select appropriate recovery interventions.
    Ordered by evidence level (Cake before Icing).
    Source: Recovery Protocols doc §1-6
    """
    protocol = []

    # THE CAKE (always)
    # Source: Recovery Protocols §1 — Cake vs Icing model
    if data.sleep_hours < 8:
        protocol.append(f"SLEEP: Target 8-9h tonight. Current avg {data.sleep_hours:.1f}h. Sleep is the primary recovery tool — 70-80% of GH released during deep sleep.")
    else:
        protocol.append(f"SLEEP: On target ({data.sleep_hours:.1f}h). Maintain consistency.")

    # THE ICING (conditional)
    # Source: Recovery Protocols §3, §6

    # CWI — after matches and heavy conditioning, NOT after strength
    if data.match_day_offset == 0 or (data.rpe_yesterday and data.rpe_yesterday >= 8):
        protocol.append("CWI: 11-15°C for 10-15min within 60min post-session. Do NOT use after strength/hypertrophy sessions (blunts adaptation).")

    # Active recovery on MD+1
    # Source: Recovery Protocols §4
    if data.match_day_offset == 1:
        protocol.append("ACTIVE RECOVERY: 20-30min at 50-60% HRmax. Light cycle, swimming, or walking. No explosive movements.")
        protocol.append("TART CHERRY: 480ml tonight + tomorrow morning. Reduces DOMS by 20-30%.")

    # Compression
    if data.match_day_offset and data.match_day_offset in [0, 1]:
        protocol.append("COMPRESSION: Wear compression garments during travel and post-match. Moderate evidence for reducing perceived soreness.")

    return protocol


# ============================================================
# POSITION-SPECIFIC ADJUSTMENTS
# ============================================================

def get_position_context(data: DailyData) -> dict:
    """
    Position-specific thresholds and notes.
    Source: Position Specific Demands doc §2-8
    """
    profiles = {
        "GK": {
            "key_quality": "Explosive power, lateral agility",
            "energy_system": "ATP-PCr (anaerobic alactic)",
            "carb_needs": "4-5g/kg (lower than outfield)",
            "calorie_adjustment": -600,  # kcal vs outfield on match days
            "hsr_benchmark_m": "100-300",
            "sprint_benchmark": "5-15",
            "injury_focus": "Lateral movement injuries, shoulder",
        },
        "CB": {
            "key_quality": "Maximum strength, aerial power",
            "energy_system": "Mixed — high internal load despite lower running volume",
            "carb_needs": "5-6g/kg",
            "calorie_adjustment": 0,
            "hsr_benchmark_m": "300-500",
            "sprint_benchmark": "20-35",
            "injury_focus": "Hamstring (recovery sprints), groin (wide defensive movements). Nordic curls + Copenhagen critical.",
        },
        "FB": {
            "key_quality": "Speed endurance, repeated sprint ability",
            "energy_system": "Aerobic + repeated anaerobic",
            "carb_needs": "6-8g/kg",
            "calorie_adjustment": 0,
            "hsr_benchmark_m": "800-1200",
            "sprint_benchmark": "40-60",
            "injury_focus": "Hamstring (HSR volume highest after wingers), ankle. Nordic curls essential.",
        },
        "CM": {
            "key_quality": "Aerobic capacity, work rate",
            "energy_system": "Primarily aerobic — highest total distance",
            "carb_needs": "8-10g/kg on heavy days",
            "calorie_adjustment": +200,  # highest energy expenditure
            "hsr_benchmark_m": "500-900",
            "sprint_benchmark": "25-40",
            "injury_focus": "Overuse injuries from high volume. Recovery investment must be highest.",
        },
        "AM": {
            "key_quality": "Agility, acceleration",
            "energy_system": "Mixed aerobic-anaerobic",
            "carb_needs": "6-8g/kg",
            "calorie_adjustment": 0,
            "hsr_benchmark_m": "600-1000",
            "sprint_benchmark": "30-50",
            "injury_focus": "Ankle (change of direction), hamstring. Deceleration training critical.",
        },
        "W": {
            "key_quality": "Maximum velocity, repeated sprint ability",
            "energy_system": "Anaerobic + aerobic base",
            "carb_needs": "6-8g/kg",
            "calorie_adjustment": 0,
            "hsr_benchmark_m": "1000-1800",
            "sprint_benchmark": "50-80",
            "injury_focus": "HAMSTRING #1 PRIORITY. Highest sprint volume = highest risk. Nordic curl compliance is non-negotiable.",
        },
        "ST": {
            "key_quality": "Explosive acceleration (5-15m), aerial power",
            "energy_system": "Anaerobic dominant",
            "carb_needs": "6-8g/kg",
            "calorie_adjustment": 0,
            "hsr_benchmark_m": "800-1400",
            "sprint_benchmark": "40-65",
            "injury_focus": "Hamstring (sprint quality), groin. Nordic curls + Copenhagen.",
        },
    }
    return profiles.get(data.position, profiles["FB"])


# ============================================================
# MAIN PROTOCOL FUNCTION
# ============================================================

def generate_protocol(data: DailyData) -> ProtocolOutput:
    """
    Master function. Runs all rules and returns complete ProtocolOutput.
    This is called by calculate.py and passed to interpret.py (Layer 2).
    """
    # Flags first — we need the count for interaction effects
    flags = generate_flags(data)
    bloodwork_flags = generate_bloodwork_flags(data)

    # --- Lücke 4: INTERACTION EFFECTS ---
    # Count negative signals for compound-risk override
    negative_count = 0
    if data.sleep_hours < 7:
        negative_count += 1
    if data.rpe_yesterday and data.rpe_yesterday >= 8:
        negative_count += 1
    if data.checkin in ("no", "limited"):
        negative_count += 1
    if data.acwr > 1.2:
        negative_count += 1
    hrv_delta = ((data.hrv - data.hrv_baseline) / data.hrv_baseline) * 100
    if hrv_delta < -10:
        negative_count += 1
    data.active_negative_flags = negative_count

    # Core recommendation
    recommendation, reasons, confidence = select_training_recommendation(data)

    # --- Lücke 4: Compound-risk safety override ---
    # If 3+ negative signals active simultaneously, override to active_recovery max
    # Source: Accumulated stress theory — multiple mild stressors compound non-linearly
    if negative_count >= 4 and recommendation == "full_intensity":
        recommendation = "active_recovery"
        reasons.append(f"⚠ COMPOUND RISK: {negative_count} negative signals active simultaneously. Overriding to active recovery as safety measure.")
        confidence = "high"
    elif negative_count >= 3 and recommendation == "full_intensity":
        recommendation = "reduced"
        reasons.append(f"⚠ COMPOUND RISK: {negative_count} negative signals active. Reducing from full intensity as precaution.")
        confidence = "moderate"

    # --- Lücke 5: Injury return — tighter ACWR thresholds ---
    # Source: Injury Prevention Protocol — returning athletes have lower tissue tolerance
    if data.returning_from_injury:
        if data.acwr > 1.2 and recommendation in ("full_intensity", "reduced"):
            recommendation = "reduced"
            reasons.append("INJURY RETURN: ACWR threshold lowered to 1.2 (from 1.3) for first 4 weeks post-injury. Protecting tissue tolerance.")
            flags.append("⚠ INJURY RETURN PROTOCOL: Tighter load thresholds active. ACWR spike threshold = 1.2.")

    # Recovery protocol
    recovery = select_recovery_protocol(data)

    # Match day specific
    match_protocol = None
    if data.match_day_offset is not None:
        pos = get_position_context(data)
        match_protocol = {
            "offset": data.match_day_offset,
            "position_profile": pos,
        }

    return ProtocolOutput(
        training_recommendation=recommendation,
        recommendation_reasons=reasons,
        confidence=confidence,
        flags=flags,
        bloodwork_flags=bloodwork_flags,
        recovery_protocol=recovery,
        match_day_protocol=match_protocol,
    )


# ============================================================
# EXAMPLE USAGE (for testing)
# ============================================================

if __name__ == "__main__":
    import sys
    # cp1252-Konsole (Windows) crasht beim Drucken von ⚠ / 🩸 -> UTF-8 erzwingen.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    # Sample data matching the dashboard sample
    sample = DailyData(
        adjusted_readiness=67,
        whoop_recovery=88,
        discrepancy=21,
        acwr=1.12,
        acwr_zone="optimal",
        checkin="limited",
        checkin_reason="soreness",
        rpe_yesterday=7,
        hrv=102,
        hrv_baseline=96,
        rhr=43,
        rhr_baseline=46,
        sleep_hours=8.2,
        sleep_efficiency=95,
        gps_available=True,
        total_distance_m=8420,
        hsr_m=612,
        hid_m=1840,
        decelerations=38,
        decel_7day_avg=29,
        sprints=14,
        max_speed_kmh=29.4,
        ferritin=48,
        vitamin_d=38,
        omega3_index=6.2,
        cortisol=520,
        ck=380,
        position="FB",
    )

    result = generate_protocol(sample)

    print(f"RECOMMENDATION: {result.training_recommendation}")
    print(f"CONFIDENCE: {result.confidence}")
    print(f"\nREASONS:")
    for r in result.recommendation_reasons:
        print(f"  - {r}")
    print(f"\nFLAGS:")
    for f in result.flags:
        print(f"  {f}")
    print(f"\nBLOODWORK:")
    for b in result.bloodwork_flags:
        print(f"  {b}")
    print(f"\nRECOVERY PROTOCOL:")
    for p in result.recovery_protocol:
        print(f"  → {p}")
