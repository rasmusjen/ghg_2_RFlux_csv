"""Input-to-output column mappings for the LI-COR ``.data`` payload.

``VARS_SUBSET1`` / ``VARS_SUBSET2`` and ``VARS_RENAME`` are transplanted verbatim
from the original script (GHG2RFLUX.py:46-64). The two subsets differ only in how
the sonic channels are named; layout ``auto`` reproduces the original detection.
"""

from __future__ import annotations

VARS_SUBSET1: list[str] = [
    "U (m/s)",
    "V (m/s)",
    "W (m/s)",
    "T (C)",
    "Anemometer Diagnostics",
    "Diagnostic Value",
    "CO2 dry(umol/mol)",
    "H2O dry(mmol/mol)",
    "Cell Temperature (C)",
    "Temperature In (C)",
    "Temperature Out (C)",
    "Total Pressure (kPa)",
]

VARS_SUBSET2: list[str] = [
    "Aux 1 - U (m/s)",
    "Aux 2 - V (m/s)",
    "Aux 3 - W (m/s)",
    "Aux 4 - Ts (C)",
    "Anemometer Diagnostics",
    "Diagnostic Value",
    "CO2 dry(umol/mol)",
    "H2O dry(mmol/mol)",
    "Cell Temperature (C)",
    "Temperature In (C)",
    "Temperature Out (C)",
    "Total Pressure (kPa)",
]

VARS_RENAME: list[str] = [
    "U",
    "V",
    "W",
    "T_SONIC",
    "SA_DIAG",
    "GA_DIAG",
    "CO2",
    "H2O",
    "T_CELL",
    "T_CELL_IN",
    "T_CELL_OUT",
    "PRESS_CELL",
]

#: Named column layouts selectable from a directory marker (``layout = ...``).
LAYOUTS: dict[str, list[str]] = {
    "licor_std": VARS_SUBSET1,
    "licor_aux": VARS_SUBSET2,
}

#: The layout name used when nothing overrides it; reproduces the original
#: ``'U (m/s)' in df.columns`` probe at GHG2RFLUX.py:600.
AUTO = "auto"


def select_layout(columns: list[str], layout: str = AUTO) -> tuple[str, list[str]]:
    """Return ``(layout_name, input_columns)`` for a parsed ``.data`` frame.

    With ``layout='auto'`` this is exactly the original behaviour: use
    ``VARS_SUBSET1`` when both ``U (m/s)`` and ``V (m/s)`` are present, else
    ``VARS_SUBSET2``. A named layout is returned as-is so an unexpected header
    set fails loudly at the ``df.loc[:, cols]`` call rather than being guessed.
    """
    if layout != AUTO:
        try:
            return layout, LAYOUTS[layout]
        except KeyError:
            known = ", ".join(sorted(LAYOUTS)) or "(none)"
            raise KeyError(f"Unknown column layout {layout!r}. Known layouts: {known}") from None

    if "U (m/s)" in columns and "V (m/s)" in columns:
        return "licor_std", VARS_SUBSET1
    return "licor_aux", VARS_SUBSET2


def validate_layout(layout: str) -> None:
    """Raise if ``layout`` names no known preset.

    Called once per run, before any file is opened: inside ``process_ghg_file``
    this would be swallowed by the per-file exception handler and a single typo
    would surface as every file in the folder "failing to parse".
    """
    if layout != AUTO and layout not in LAYOUTS:
        known = ", ".join([AUTO, *sorted(LAYOUTS)])
        raise KeyError(f"Unknown column layout {layout!r}. Known layouts: {known}")
