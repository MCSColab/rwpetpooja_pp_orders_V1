import asyncio
import warnings
from execution.browser_helper import get_browser


async def main():
    print("Starting browser with persistent session...")
    print("Persistence directory: .tmp/browser_profile")

    browser = await get_browser()
    page = await browser.get("https://billing.petpooja.com/")

    print(f"Browser opened. Current URL: {page.url}")
    print("You can now perform manual actions (like login).")
    print("The session will be saved for the automation script.")
    print("\nPress Ctrl+C to close the browser and exit.")

    try:
        # Keep the connection alive indefinitely
        while True:
            await asyncio.sleep(1)
            # Optional: check if browser is still alive
            if not browser.connection:
                break
    except KeyboardInterrupt:
        print("\nClosing browser...")
    finally:
        try:
            await browser.stop()
            await asyncio.sleep(0.5)  # Allow cleanup time
        except Exception:
            pass


if __name__ == "__main__":
    # Suppress transport warnings during cleanup (harmless on Windows)
    warnings.filterwarnings("ignore", category=ResourceWarning)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
