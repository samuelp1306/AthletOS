# src/filters.py
# -----------------------------------------------------------------------------
# Helper functions for FILTERING and searching the player pool.
#
# Once players are scored, you'll want to narrow them down: by age, by transfer
# value, by position, by contract status, etc. Those filters live here so the
# dashboard pages stay simple.
#
# Placeholder only — no logic yet.
# -----------------------------------------------------------------------------

import pandas as pd


def filter_by_position(df: pd.DataFrame, position: str) -> pd.DataFrame:
    """Return only the players who can play a given position.

    Args:
        df: A player DataFrame.
        position: A position code such as "DL" or "ST".

    Returns:
        A filtered DataFrame.
    """
    # TODO: match the position against the player's position column.
    raise NotImplementedError("filter_by_position is not implemented yet.")


def filter_by_range(
    df: pd.DataFrame, column: str, minimum=None, maximum=None
) -> pd.DataFrame:
    """Return players whose value in `column` falls within a range.

    Useful for age, transfer value, wage, etc. Either bound can be left as None
    to mean "no limit on that side".

    Args:
        df: A player DataFrame.
        column: The column to filter on (e.g. "Age").
        minimum: Lowest allowed value, or None for no lower bound.
        maximum: Highest allowed value, or None for no upper bound.

    Returns:
        A filtered DataFrame.
    """
    # TODO: apply the min/max bounds to the chosen column.
    raise NotImplementedError("filter_by_range is not implemented yet.")
