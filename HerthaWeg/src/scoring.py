# src/scoring.py
# -----------------------------------------------------------------------------
# The heart of the "Moneyball" idea: score each player against role profiles.
#
# A profile (see config/search_profiles.json) is a set of attributes with
# weights. A player's score for a role is a weighted combination of their
# attributes for that role. This lets us rank players by how well they fit a
# specific job, not just by their raw ability.
#
# Placeholder only — the real math comes later.
# -----------------------------------------------------------------------------

import pandas as pd


def load_profiles(config_path: str = "config/search_profiles.json") -> dict:
    """Load the role/position scoring profiles from JSON.

    Args:
        config_path: Path to the search_profiles.json file.

    Returns:
        A dictionary of profiles keyed by profile id.
    """
    # TODO: read the JSON file and return the "profiles" dict.
    raise NotImplementedError("load_profiles is not implemented yet.")


def score_players(df: pd.DataFrame, profile: dict) -> pd.DataFrame:
    """Score every player against a single role profile.

    Args:
        df: A cleaned player DataFrame.
        profile: One profile dict (with a "weights" mapping).

    Returns:
        The DataFrame with an added score column, sorted best-first.
    """
    # TODO: multiply each attribute by its weight, sum, and normalize.
    raise NotImplementedError("score_players is not implemented yet.")
