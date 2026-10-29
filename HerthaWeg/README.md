# HerthaWeg

**FM Moneyball Recruitment Dashboard**

A Football Manager scouting dashboard inspired by professional recruitment
tools such as Schalke's *StatsLibuda*. HerthaWeg takes exported Football
Manager player data, cleans it, scores players against role-based profiles,
and helps you find undervalued signings — a "Moneyball" approach to FM
recruitment.

> ⚠️ **Status: early scaffold.** Only the project structure and placeholder
> pages exist right now. The scoring logic is not built yet.

## Features (planned)

- **Upload Data** — import FM player exports (HTML / Excel / CSV).
- **Top Targets** — rank every player by overall Moneyball score.
- **Position Finder** — find the best players for a given position and role.
- **Player Profile** — deep-dive on a single player with attribute breakdowns.
- **Shortlist Export** — save chosen targets and export them back to FM.

## Project structure

```
HerthaWeg/
├── app.py                       # Streamlit entry point (the dashboard)
├── requirements.txt             # Python dependencies
├── README.md                    # This file
├── data/
│   ├── raw/                     # Raw FM exports (untouched)
│   └── processed/               # Cleaned, ready-to-use data
├── outputs/                     # Generated shortlists and exports
├── config/
│   └── search_profiles.json     # Role/position scoring profiles
└── src/
    ├── load_data.py             # Read raw FM exports into DataFrames
    ├── clean_data.py            # Normalize and clean the raw data
    ├── scoring.py               # Score players against role profiles
    ├── filters.py               # Filter/search players
    ├── export.py                # Export shortlists to CSV/Excel
    └── utils.py                 # Shared helper functions
```

## Getting started

1. **(Recommended) Create a virtual environment:**

   ```bash
   python -m venv .venv
   # Windows
   .venv\Scripts\activate
   # macOS / Linux
   source .venv/bin/activate
   ```

2. **Install the dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

3. **Run the dashboard:**

   ```bash
   streamlit run app.py
   ```

   Streamlit will open the app in your browser (usually at
   http://localhost:8501).

## Tech stack

- Python 3.11+
- [Streamlit](https://streamlit.io/) — the web dashboard
- pandas + numpy — data processing
- plotly — interactive charts
- openpyxl — Excel import/export
- beautifulsoup4 + lxml — parsing FM HTML exports
