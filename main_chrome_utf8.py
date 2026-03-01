import asyncio
import sys
import os
import warnings
import traceback
from execution.petpooja_automation import PetpoojaAutomation
from execution.logger_helper import LoggerHelper
# from execution.gdrive_uploader import GDriveUploader
from execution.pgsql_uploader import PostgresUploader
from execution.data_cleaner import DataCleaner
from execution.notifier_helper import NotifierHelper
import pandas as pd


async def main():
    logger_helper = LoggerHelper()
    logger = logger_helper.logger
    notifier = NotifierHelper()

    logger.info("Starting Petpooja Order Summary Report Automation")
    success = False

    try:
        automation = PetpoojaAutomation()
        await automation.run()
        logger.info("Automation process finished.")

        logger.info("Starting Data Cleaning process")
        cleaner = DataCleaner()
        cleaned_file = cleaner.process_latest_report()
        if cleaned_file:
            logger.info(f"Data cleaning finished. Cleaned file: {cleaned_file.name}")
            
            # Step: Insert into PostgreSQL
            logger.info("Starting PostgreSQL upload process")
            df = pd.read_excel(cleaned_file)
            pgsql_uploader = PostgresUploader()
            if pgsql_uploader.insert_dataframe(df):
                logger.info("PostgreSQL upload process finished successfully.")
            else:
                logger.error("PostgreSQL upload process failed.")
                # We might want to set success to False here if DB upload is critical
                # success = False 
        else:
            logger.warning(
                "Data cleaning skipped (no new file found or error occurred)."
            )

        # logger.info("Starting Google Drive upload process")
        # uploader = GDriveUploader()
        # uploader.process_files()
        # logger.info("Google Drive upload process finished.")
        success = True

    except Exception as e:
        error_msg = str(e) or type(e).__name__
        logger.error(f"Automation failed: {error_msg}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        success = False
    finally:
        # Collect log data for the email
        log_content = ""
        try:
            if os.path.exists(logger_helper.log_file):
                with open(logger_helper.log_file, "r", encoding="utf-8") as f:
                    log_content = f.read()
        except Exception as log_err:
            logger.error(f"Could not read log file for email: {log_err}")

        notifier.send_status_email(success, log_content)

        if not success:
            sys.exit(1)


def suppress_cleanup_exceptions(args):
    """Suppress harmless exceptions during asyncio cleanup on Windows."""
    # These exceptions occur during __del__ of transport objects
    # when the event loop is closing - they're harmless
    if args.exc_type == ValueError and "closed pipe" in str(args.exc_value):
        return  # Suppress
    if args.exc_type == RuntimeWarning and "was never awaited" in str(args.exc_value):
        return  # Suppress
    # For other exceptions, use default handling
    sys.__unraisablehook__(args)


def run_with_cleanup():
    """Run the async main function with proper cleanup for Windows."""
    # Suppress ResourceWarnings about unclosed transports
    warnings.filterwarnings("ignore", category=ResourceWarning)
    warnings.filterwarnings(
        "ignore", category=RuntimeWarning, message="coroutine.*was never awaited"
    )

    # Install hook to suppress cleanup exceptions in __del__ methods
    sys.unraisablehook = suppress_cleanup_exceptions

    # Note: We must use ProactorEventLoop on Windows (the default) because
    # nodriver needs subprocess support which SelectorEventLoop doesn't provide

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(main())
    finally:
        # Properly shutdown async generators and cancel pending tasks
        try:
            # Cancel all pending tasks
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()

            # Allow cancelled tasks to finish
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )

            # Shutdown async generators
            loop.run_until_complete(loop.shutdown_asyncgens())

            # Shutdown default executor
            loop.run_until_complete(loop.shutdown_default_executor())
        except Exception:
            pass  # Ignore errors during cleanup
        finally:
            loop.close()


if __name__ == "__main__":
    run_with_cleanup()
