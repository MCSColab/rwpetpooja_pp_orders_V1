import asyncio
import sys
import warnings
import traceback
from execution.petpooja_automation import PetpoojaAutomation
from execution.logger_helper import LoggerHelper
from execution.gdrive_uploader import GDriveUploader


async def main():
    logger = LoggerHelper()
    logger.log_execution("INFO", "Starting Petpooja Order Summary Report Automation")

    try:
        automation = PetpoojaAutomation()
        await automation.run()
        logger.log_execution("INFO", "Automation process finished.")
        
        logger.log_execution("INFO", "Starting Google Drive upload process")
        uploader = GDriveUploader()
        uploader.process_files()
        logger.log_execution("INFO", "Google Drive upload process finished.")
    except Exception as e:
        error_msg = str(e) or type(e).__name__
        logger.log_execution("ERROR", f"Automation failed: {error_msg}")
        logger.log_execution("ERROR", f"Traceback: {traceback.format_exc()}")
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
    warnings.filterwarnings("ignore", category=RuntimeWarning, message="coroutine.*was never awaited")

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
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))

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
