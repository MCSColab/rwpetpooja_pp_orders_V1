"""
Central Application Entry Point.

Orchestrates the Petpooja to PostgreSQL automation pipeline with a robust
Fallback architecture:
    1. Primary Route: Fast, low-RAM requests-based API client.
    2. Fallback Route: If API fails (e.g., expired cookies), launches
       Playwright headless Firefox to log in, export new cookies, and download.
    3. Cleaning: Processes the downloaded CSV.
    4. Database: Upserts records into PostgreSQL.
    5. Notifications: Sends an email summarizing success or failure.

Date Resolution Strategy
------------------------
- When NO date arguments are supplied, the pipeline automatically targets
  **yesterday in India Standard Time (IST / Asia/Kolkata, UTC+5:30)**.
  This is timezone-safe: even when running on a UTC AWS Lightsail server,
  the correct IST calendar date is derived.
- When --start / --end are supplied, the pipeline runs for every date in
  that inclusive range (useful for backfilling).
- When a single positional date (YYYY-MM-DD) is supplied, it is used
  directly without any timezone calculation.
"""

import os
import sys
import asyncio
import datetime
import argparse
import traceback
from zoneinfo import ZoneInfo  # stdlib since Python 3.9

import pandas as pd

from execution.petpooja_requests import PetpoojaRequestsClient
from execution.playwright_automation import PlaywrightAutomation
from execution.data_cleaner import DataCleaner
from execution.pgsql_uploader import PostgresUploader
from execution.notifier_helper import NotifierHelper
from execution.logger_helper import LoggerHelper

# India Standard Time — used for all "today / yesterday" calculations so that
# the program works correctly on UTC-based servers (e.g., AWS Lightsail Debian).
_IST = ZoneInfo("Asia/Kolkata")


def _yesterday_ist() -> datetime.date:
    """Return yesterday's date in Indian Standard Time (IST, UTC+5:30).

    Using IST ensures the correct calendar date is resolved even when the
    host machine (e.g., an AWS Lightsail Debian instance) runs on UTC.

    Returns:
        datetime.date: Yesterday's date as observed in the IST timezone.
    """
    today_ist: datetime.date = datetime.datetime.now(tz=_IST).date()
    return today_ist - datetime.timedelta(days=1)


async def run_pipeline(target_date: datetime.date | None = None) -> bool:
    """Execute the dual-route automation pipeline for a single date.

    Args:
        target_date: The specific date for which to fetch and upload Petpooja
            data. If ``None``, defaults to **yesterday in IST** so that the
            pipeline is timezone-safe on UTC servers.

    Returns:
        bool: ``True`` if the full pipeline (download → clean → upload → notify)
            completed without errors, ``False`` otherwise.
    """
    logger_helper = LoggerHelper()
    logger = logger_helper.logger
    notifier = NotifierHelper()

    success = False
    downloaded_csv = None

    if target_date is None:
        # Always derive "yesterday" from IST so the result is correct on UTC
        # servers (AWS Lightsail Debian, etc.).
        target_date = _yesterday_ist()
        logger.info(
            f"No date supplied — resolved to yesterday in IST: {target_date}"
        )

    logger.info(f"--- Starting Pipeline for {target_date} ---")

    try:
        # ==========================================
        # 1. Primary Route: Requests API (Fast Path)
        # ==========================================
        logger.info("Attempting Fast Route (requests API)...")
        try:
            req_client = PetpoojaRequestsClient()
            downloaded_csv = req_client.run(target_date)
            if downloaded_csv:
                logger.info("Fast Route Success.")
        except Exception as e:
            logger.warning(f"Fast Route encountered an error during init: {e}")

        # ==========================================
        # 2. Fallback Route: Playwright Automation
        # ==========================================
        if not downloaded_csv:
            logger.warning("Fast Route failed. Initiating Playwright Fallback Route...")
            pw_bot = PlaywrightAutomation()
            downloaded_csv = await pw_bot.run(target_date)
            
            if downloaded_csv:
                logger.info("Fallback Route Success.")
            else:
                logger.error("Both Fast Route and Fallback Route failed to download the report.")
                raise RuntimeError("Report download failed on all routes.")

        # ==========================================
        # 3. Data Cleaning
        # ==========================================
        logger.info(f"Starting Data Cleaning for {downloaded_csv.name}...")
        cleaner = DataCleaner()
        cleaned_xlsx = cleaner.process_latest_report()
        
        if not cleaned_xlsx:
            raise RuntimeError("Data cleaning failed.")
        
        logger.info(f"Data cleaning finished: {cleaned_xlsx.name}")

        # ==========================================
        # 4. PostgreSQL Upload
        # ==========================================
        logger.info("Starting PostgreSQL upload process...")
        df = pd.read_excel(cleaned_xlsx)
        
        pgsql_uploader = PostgresUploader()
        if pgsql_uploader.insert_dataframe(df):
            logger.info(f"PostgreSQL upload success: {len(df)} records upserted.")
            success = True
        else:
            raise RuntimeError("PostgreSQL upload process failed.")

    except Exception as e:
        logger.error(f"Pipeline crashed: {str(e)}")
        logger.error(traceback.format_exc())
        success = False

    finally:
        # ==========================================
        # 5. Email Notification
        # ==========================================
        logger.info("Generating status email...")
        log_content = ""
        try:
            if os.path.exists(logger_helper.log_file):
                # Read the last 100 lines of the log for context
                with open(logger_helper.log_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    log_content = "".join(lines[-100:])
        except Exception as log_err:
            logger.error(f"Could not read log file for email: {log_err}")

        # Send email
        notifier.send_status_email(success, log_content)
        
        if success:
            logger.info("--- Pipeline Completed Successfully ---")
        else:
            logger.error("--- Pipeline Failed ---")
            
        return success


def main() -> None:
    """CLI entry point.

    Supports three invocation modes:

    1. **No arguments** — runs for yesterday in IST (timezone-safe default)::

           python main.py

    2. **Single positional date** — runs for that exact date::

           python main.py 2026-02-28

    3. **Date range** — runs for every date in [start, end] inclusive
       (useful for backfilling)::

           python main.py --start 2026-02-01 --end 2026-02-28

    Handles Windows ProactorEventLoop requirement for Playwright.
    """
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Petpooja → PostgreSQL pipeline",
    )
    parser.add_argument(
        "date",
        nargs="?",
        metavar="YYYY-MM-DD",
        help="Single target date (optional). Defaults to yesterday in IST.",
    )
    parser.add_argument(
        "--start",
        metavar="YYYY-MM-DD",
        help="Start of a date range (inclusive). Must be paired with --end.",
    )
    parser.add_argument(
        "--end",
        metavar="YYYY-MM-DD",
        help="End of a date range (inclusive). Must be paired with --start.",
    )
    args = parser.parse_args()

    # ── Resolve the list of dates to process ─────────────────────────────────
    dates_to_run: list[datetime.date] = []

    if args.start or args.end:
        # Range mode — both flags are required together
        if not (args.start and args.end):
            parser.error("Both --start and --end must be supplied together.")
        try:
            start_date = datetime.date.fromisoformat(args.start)
            end_date = datetime.date.fromisoformat(args.end)
        except ValueError as exc:
            parser.error(f"Invalid date format: {exc}")
        if start_date > end_date:
            parser.error("--start must be on or before --end.")
        # Build inclusive date list
        delta = (end_date - start_date).days
        dates_to_run = [
            start_date + datetime.timedelta(days=i) for i in range(delta + 1)
        ]
    elif args.date:
        # Single explicit date
        try:
            dates_to_run = [datetime.date.fromisoformat(args.date)]
        except ValueError:
            parser.error(
                f"Invalid date '{args.date}'. Expected format: YYYY-MM-DD."
            )
    else:
        # Default: yesterday in IST (timezone-safe for UTC servers)
        dates_to_run = [_yesterday_ist()]
        print(
            f"No date supplied — defaulting to yesterday in IST: {dates_to_run[0]}"
        )

    # ── Event loop setup (Windows Playwright requirement) ────────────────────
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    # ── Run the pipeline for each date ───────────────────────────────────────
    overall_success = True
    try:
        for run_date in dates_to_run:
            print(f"\n>>> Running pipeline for {run_date} ...")
            success = asyncio.run(run_pipeline(run_date))
            if not success:
                overall_success = False
                print(f"!!! Pipeline FAILED for {run_date}")
    except KeyboardInterrupt:
        print("\nPipeline interrupted by user.")
        sys.exit(130)

    sys.exit(0 if overall_success else 1)


if __name__ == "__main__":
    main()
