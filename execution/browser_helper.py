import nodriver as uc
import asyncio
import os
import json

# Load settings once at module level
_settings = None

def _get_settings():
    global _settings
    if _settings is None:
        settings_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'settings.json')
        with open(settings_path, 'r') as f:
            _settings = json.load(f)
    return _settings


async def get_browser():
    """
    Initializes and returns a stealthy browser instance using nodriver.
    Uses a persistent profile directory configured in settings.json.
    The profile retains cookies, sessions, and login state across runs.
    """
    settings = _get_settings()

    # Use absolute path from settings, fallback to default
    if 'browser_profile_dir' in settings:
        profile_path = settings['browser_profile_dir']
    else:
        # Fallback: use project root directory (not .tmp which suggests temporary)
        profile_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'browser_profile')

    # Ensure path uses proper separators for the OS
    profile_path = os.path.normpath(profile_path)
    os.makedirs(profile_path, exist_ok=True)

    # Start browser with persistent profile
    # The user_data_dir parameter ensures all cookies, localStorage,
    # and session data are saved and restored
    browser = await uc.start(user_data_dir=profile_path)
    return browser

async def wait_for_login(page, timeout=60):
    """
    Waits for the user to be logged in or for a specific element that indicates 
    a successful login/dashboard access.
    """
    # Check if we are redirected to login
    current_url = page.url
    if "billing.petpooja.com/users/dashboard" in current_url or "reports/order_summary_ho" in current_url:
        return True
        
    print("Waiting for login...")
    # This is a placeholder for actual login logic or waiting for manual login if needed
    # In a fully automated flow, we would call a login function here.
    return False

if __name__ == "__main__":
    import warnings

    async def test():
        browser = None
        try:
            browser = await get_browser()
            page = await browser.get("https://billing.petpooja.com/")
            print(f"Opened: {page.url}")
            await asyncio.sleep(5)
        finally:
            if browser:
                try:
                    await browser.stop()
                    await asyncio.sleep(0.5)  # Allow cleanup
                except Exception:
                    pass

    # Suppress transport warnings during cleanup (harmless on Windows)
    warnings.filterwarnings("ignore", category=ResourceWarning)

    asyncio.run(test())
