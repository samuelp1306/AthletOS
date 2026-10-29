# src/utils.py
# -----------------------------------------------------------------------------
# Small SHARED helper functions used across the other modules.
#
# Anything that doesn't clearly belong to loading, cleaning, scoring, filtering,
# or exporting — but is useful in more than one place — lives here. Keeping
# these in one spot avoids copy-pasting the same helper into several files.
#
# Placeholder only — no logic yet.
# -----------------------------------------------------------------------------

from pathlib import Path


# Absolute path to the project root (the folder that contains app.py).
# `Path(__file__)` is this file; `.parent.parent` walks up out of `src/`.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def project_path(*parts: str) -> Path:
    """Build a path relative to the project root.

    Example:
        project_path("data", "raw")  ->  <project>/data/raw

    Args:
        *parts: Folder/file names to join onto the project root.

    Returns:
        A pathlib.Path pointing inside the project.
    """
    return PROJECT_ROOT.joinpath(*parts)


def to_number(value) -> float:
    """Best-effort conversion of a messy value into a float.

    FM exports often contain numbers as text, ranges like "12-15", or values
    with symbols. This helper will centralize that parsing.

    Args:
        value: The raw value to convert.

    Returns:
        The value as a float.
    """
    # TODO: handle ranges, currency symbols, thousands separators, etc.
    raise NotImplementedError("to_number is not implemented yet.")
