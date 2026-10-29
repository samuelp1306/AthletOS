# src/clean_data.py
# -----------------------------------------------------------------------------
# Responsible for CLEANING the raw data loaded by load_data.py.
#
# FM exports are messy: numbers arrive as text, attributes may be ranges like
# "12-15", money has currency symbols, and column names vary. This module turns
# that raw DataFrame into a tidy, numeric, consistent one that scoring.py can
# trust.
#
# Placeholder only — no logic yet.
# -----------------------------------------------------------------------------

import pandas as pd


def clean_players(df: pd.DataFrame) -> pd.DataFrame:
    """Clean and normalize a raw player DataFrame.

    Typical steps (to be implemented):
      - standardize column names
      - convert attribute columns to numbers
      - parse value/wage/age fields
      - drop or flag rows with missing key data

    Args:
        df: The raw DataFrame from load_data.

    Returns:
        A cleaned DataFrame ready for scoring.
    """
    # TODO: implement cleaning steps.
    raise NotImplementedError("clean_players is not implemented yet.")
