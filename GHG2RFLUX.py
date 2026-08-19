"""Backwards-compatible entry point.

Created on Thu Sep 28 14:27:32 2023
@author: au710242

The implementation now lives in the ``ghg2rflux`` package under ``src/``; this
file is kept so that ``python GHG2RFLUX.py`` continues to work exactly as it did,
reading ``config.ini`` and converting the single station-year it names.

Prefer the CLI for anything new -- it takes multiple years and per-folder
settings::

    ghg2rflux -site GL-ZaF -years 2020 2021 2022
    ghg2rflux -site GL-Dsk -years 2020 --dry-run
    ghg2rflux scan -site GL-Dsk -years 2020
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from ghg2rflux.cli import main

if __name__ == "__main__":
    raise SystemExit(main([]))
