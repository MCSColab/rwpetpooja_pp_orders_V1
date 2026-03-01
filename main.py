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
"""

import os
import sys
import asyncio
import datetime
import traceback

import pandas as pd

from execution.petpooja_requests import PetpoojaRequestsClient
from execution.playwright_automation import PlaywrightAutomation
from execution.data_cleaner import DataCleaner
from execution.pgsql_uploader import PostgresUploader
from execution.notifier_helper import NotifierHelper
from execution.logger_helper import LoggerHelper


async def run_pipeline(target_date: datetime.date | None = None) -> bool:
    """Execute the dual-route automation pipeline."""
    logger_helper = LoggerHelper()
    logger = logger_helper.logger
    notifier = NotifierHelper()
    
    success = False
    downloaded_csv = None

    if target_date is None:
        target_date = datetime.date.today() - datetime.timedelta(days=1)

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


def main():
    """CLI Entry point. Handles Windows event loop politics."""
    # Parse optional date argument
    target_date = None
    for arg in sys.argv[1:]:
        if arg.startswith("-"):
            continue
        try:
            target_date = datetime.date.fromisoformat(arg)
        except ValueError:
            print(f"WARNING: Invalid date '{arg}', using yesterday.")

    # Playwright on Windows works best with the ProactorEventLoop (default in 3.8+)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    try:
        success = asyncio.run(run_pipeline(target_date))
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nPipeline interrupted by user.")
        sys.exit(130)


if __name__ == "__main__":
    main()
