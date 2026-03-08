"""
Database Verification Script.
"""
import datetime
from execution.db_checker import get_missing_dates

if __name__ == "__main__":
    start = datetime.date(2026, 3, 3)
    end = datetime.date(2026, 3, 7)
    missing = get_missing_dates(start, end)
    if not missing:
        print(f"SUCCESS: All dates from {start} to {end} are present in the DB.")
    else:
        print(f"MISSING DATES: {missing}")
