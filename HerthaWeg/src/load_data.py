# src/load_data.py
# -----------------------------------------------------------------------------
# Responsible for READING raw Football Manager exports into pandas DataFrames.
#
# Football Manager can export a player search view as an HTML table. This module
# will turn those files (HTML, and optionally Excel/CSV) into a DataFrame that
# the rest of the app can work with.
#
# Nothing here is implemented yet — these are placeholder function signatures
# so the shape of the module is clear.
# -----------------------------------------------------------------------------

import pandas as pd


def load_fm_html(file_path: str) -> pd.DataFrame:
    """Load a Football Manager HTML export into a DataFrame.

    Args:
        file_path: Path to the exported .html file from FM.

    Returns:
        A pandas DataFrame with one row per player.
    """
    # TODO: parse the HTML table (pandas.read_html uses lxml/bs4 under the hood).
    raise NotImplementedError("load_fm_html is not implemented yet.")


def load_spreadsheet(file_path: str) -> pd.DataFrame:
    """Load player data from an Excel (.xlsx) or CSV file.

    Args:
        file_path: Path to the .xlsx or .csv file.

    Returns:
        A pandas DataFrame with one row per player.
    """
    # TODO: dispatch to pandas.read_excel or pandas.read_csv based on extension.
    raise NotImplementedError("load_spreadsheet is not implemented yet.")
