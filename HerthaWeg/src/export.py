# src/export.py
# -----------------------------------------------------------------------------
# Responsible for EXPORTING a shortlist of players out of the app.
#
# After you've found your targets, you'll want to save them — as a CSV or Excel
# file in the `outputs/` folder — so you can reference them back in Football
# Manager. This module handles that.
#
# Placeholder only — no logic yet.
# -----------------------------------------------------------------------------

import pandas as pd


def export_csv(df: pd.DataFrame, file_path: str) -> None:
    """Write a shortlist DataFrame to a CSV file.

    Args:
        df: The shortlist of players to export.
        file_path: Where to save the .csv file (e.g. "outputs/shortlist.csv").
    """
    # TODO: df.to_csv(file_path, index=False)
    raise NotImplementedError("export_csv is not implemented yet.")


def export_excel(df: pd.DataFrame, file_path: str) -> None:
    """Write a shortlist DataFrame to an Excel file.

    Args:
        df: The shortlist of players to export.
        file_path: Where to save the .xlsx file (e.g. "outputs/shortlist.xlsx").
    """
    # TODO: df.to_excel(file_path, index=False)  # uses openpyxl under the hood
    raise NotImplementedError("export_excel is not implemented yet.")
