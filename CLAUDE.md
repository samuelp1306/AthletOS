# Performance OS

## Purpose
A personal, two-layer performance system for a semi-professional footballer. It combines Whoop wearable data, Yazio nutrition tracking, training logs, and a daily subjective check-in into an adjusted readiness score — then uses the Claude API to generate a plain-language daily report.

The core problem it solves: Whoop Recovery Scores are systematically inaccurate in specific contexts (caloric deficit, psychological stress, alcohol) because they rely on HRV/RHR/sleep alone. This system adds the missing signals and corrects for known biases.

## Architecture — Two Layers (non-negotiable)

### Layer 1: Engine (`engine/`)
- Pure Python. No LLM calls. No API calls. No internet required.
- Deterministic: same inputs → same outputs, every time.
- Handles: data ingestion, ACWR calculation, readiness scoring, discrepancy detection, nutrition checks, Banister fitness-fatigue model.
- This layer DECIDES.

### Layer 2: Coach (`coach/`)
- Claude API (Sonnet). Receives Layer 1 outputs as structured JSON.
- Translates numbers into natural-language daily reports and recommendations.
- Never invents numbers. Never overrides Layer 1 calculations. Never hallucinates data.
- This layer EXPLAINS.

**Rule: Layer 1 must never import or call anything from Layer 2. Layer 2 receives Layer 1 output as a JSON dictionary — that is the only interface.**

## Tech Stack
- Python 3.11+
- pandas (data processing, rolling averages, EWMA)
- SQLite (single file: `db/performance.db`)
- Anthropic Python SDK (Layer 2 only)
- matplotlib or plotly (visualization)
- PyYAML (config parsing)
- Git + GitHub (version control)

## Project Structure

```
performance-os/
├── data/
│   ├── raw/                     # Whoop CSVs, Yazio exports
│   └── processed/               # Cleaned daily data
├── db/
│   └── performance.db           # SQLite database
├── engine/                      # LAYER 1 — Calculation Engine
│   ├── ingest/
│   │   ├── whoop.py             # Whoop CSV → SQLite
│   │   ├── yazio.py             # Yazio data → SQLite
│   │   ├── training.py          # Training log → SQLite
│   │   └── checkin.py           # Daily check-in → SQLite
│   ├── models/
│   │   ├── acwr.py              # Acute:Chronic Workload Ratio
│   │   ├── readiness.py         # Adjusted Readiness Score
│   │   ├── discrepancy.py       # Whoop vs. subjective delta
│   │   ├── banister.py          # Fitness-Fatigue model
│   │   └── nutrition.py         # Nutrition threshold checks
│   └── calculate.py             # Orchestrates all models
├── coach/                       # LAYER 2 — Interpretation
│   ├── prompts/
│   │   ├── daily_report.md      # System prompt: daily
│   │   └── weekly_summary.md    # System prompt: weekly
│   └── interpret.py             # Claude API call + response
├── viz/
│   └── charts.py                # Trend charts
├── outputs/                     # Generated reports + charts
├── run_daily.py                 # Main script: one command
├── run_weekly.py                # Weekly summary
├── config.yaml                  # Personal parameters
├── CLAUDE.md                    # This file
└── README.md
```

## Database Schema

```sql
-- Whoop daily data
CREATE TABLE whoop_daily (
    date TEXT PRIMARY KEY,
    recovery_score REAL,
    hrv REAL,
    rhr REAL,
    sleep_hours REAL,
    sleep_efficiency REAL,
    respiratory_rate REAL,
    skin_temp REAL,
    strain REAL,
    calories_burned REAL
);

-- Yazio nutrition data
CREATE TABLE yazio_daily (
    date TEXT PRIMARY KEY,
    calories REAL,
    protein REAL,
    carbs REAL,
    fat REAL,
    water_ml REAL
);

-- Training sessions (multiple per day possible)
CREATE TABLE training_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    session_type TEXT NOT NULL,  -- gym, speed, plyo, match, conditioning, recovery
    rpe REAL,                    -- 1-10
    duration_min REAL,
    notes TEXT
);

-- Daily subjective check-in
CREATE TABLE daily_checkin (
    date TEXT PRIMARY KEY,
    readiness TEXT NOT NULL,      -- yes, limited, no
    reason TEXT                   -- soreness, fatigue, mental, deficit, none
);
```

## Key Algorithms

### ACWR (engine/models/acwr.py)
- Acute load = 7-day EWMA of daily training load
- Chronic load = 28-day EWMA of daily training load
- Daily training load = Whoop Strain + (RPE × duration_min / 60) from training_log
- Output: ratio (float), zone (optimal | spike | detraining)
- Thresholds: spike > 1.3, detraining < 0.8 (from config.yaml)

### Readiness Score (engine/models/readiness.py)
- Base = Whoop Recovery Score (0–100)
- Corrections applied additively, result clamped to 0–100:
  - Caloric deficit (Yazio cals < config.tdee - 300) AND recovery > 80 → -15
  - Check-in "no" AND recovery > 70 → -20
  - Check-in "limited" AND recovery > 80 → -10
  - Sleep efficiency > 90% AND hours > 7.5 → +5
  - Sleep efficiency < 75% OR hours < 6 → -8
- Output: adjusted_readiness (int), corrections_applied (list of strings)

### Discrepancy (engine/models/discrepancy.py)
- Map check-in to numeric: yes=90, limited=60, no=30
- Delta = whoop_recovery - checkin_numeric
- If abs(delta) > 20 → flag as discrepancy
- Track discrepancy history for pattern detection

### Nutrition (engine/models/nutrition.py)
- protein_ok: protein >= config.protein_target_per_kg * config.weight_kg
- deficit_detected: calories < config.tdee - 300
- carb_low_pre_training: if tomorrow has planned session AND carbs < config.carb_target_pre_training
- Output: dict of boolean flags + context strings

## Coding Standards
- All functions have docstrings explaining inputs, outputs, and logic
- Type hints on all function signatures
- Error handling: if a data source is missing, continue with available data and log what's missing
- Date format: ISO 8601 (YYYY-MM-DD) everywhere
- All config values come from config.yaml — no hardcoded thresholds
- Tests: at minimum, each model function has one test with known inputs → expected outputs

## Whoop CSV Format
Whoop exports contain these relevant columns (names may vary slightly):
- Date, Recovery Score (%), HRV (ms), Resting Heart Rate (bpm)
- Sleep Duration (hours), Sleep Efficiency (%), Respiratory Rate
- Skin Temperature, Day Strain, Calories Burned
- Date format in CSV: MM/DD/YYYY (needs conversion to YYYY-MM-DD)

## Context: Who This Is For
- The user is a 17-year-old semi-professional footballer (left back / left midfielder)
- Currently ~66 kg, training 4-5x/week
- In active ATFL ankle rehabilitation
- Uses time-restricted eating (13:00–22:00), currently in mild caloric deficit
- Studies Sport & Trainingswissenschaft starting October 2026
- This system is both a personal tool AND a prototype for a future product (Athlet OS)

## What NOT to Build
- No web frontend. CLI only for v0.1.
- No user authentication or multi-user support.
- No real-time data sync. Manual CSV import is fine.
- No machine learning models. Rule-based logic only.
- No mobile app. No push notifications. No cloud deployment.
