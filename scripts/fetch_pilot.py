"""Pilot fetch on 3 stocks to verify the driver before the full 755 run."""
import sys
from pathlib import Path
sys.path.insert(0, r"C:\Users\adars\sss\scripts")
import fetch_all as F

# monkeypatch the constituents loader to a 3-stock list
def _pilot_consts():
    return [
        {"Symbol": "RELIANCE", "Company Name": "Reliance Industries", "Industry": "Oil Gas"},
        {"Symbol": "INFY",     "Company Name": "Infosys",             "Industry": "IT"},
        {"Symbol": "IGIL",     "Company Name": "IGI",                 "Industry": "Consumer Services"},
    ]
F.load_constituents = _pilot_consts
F.PROG_FILE = Path(r"C:\Users\adars\sss\data\fetch_progress_pilot.json")
F.ERR_FILE  = Path(r"C:\Users\adars\sss\data\fetch_errors_pilot.csv")
F.main()
