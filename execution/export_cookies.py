"""
Cookie Export Utility for Petpooja Requests Client.

Provides two methods to export Petpooja session cookies into a portable
`cookies.json` file that the requests-based automation can consume:

    Method 1 (Automatic): Reads cookies from the existing nodriver/Chrome
    browser profile's SQLite database.

    Method 2 (Manual Guide): Prints instructions for manually copying
    cookie values from Chrome DevTools.

Usage:
    python -m execution.export_cookies           # Auto-export from browser profile
    python -m execution.export_cookies --manual   # Print manual export guide
"""

import os
import sys
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Dict, Optional


# Cookies required for Petpooja API authentication
REQUIRED_COOKIES = [
    "PETPOOJA_CO",
    "CakeCookie[google_user_token]",
]

# Additional cookies that may help maintain the session
OPTIONAL_COOKIES = [
    "_fbp",
    "_ga",
    "_ga_D59C80DKJH",
    "_ga_3PQV9C1C97",
    "_gid",
    "WZRK_G",
]

# Domain filter for cookie extraction
TARGET_DOMAIN = ".petpooja.com"


def export_from_browser_profile(
    profile_dir: str,
    output_path: str = "cookies.json",
) -> bool:
    """
    Extract Petpooja cookies from the Chrome/nodriver browser profile.

    Chrome stores cookies in an SQLite database at:
        <profile_dir>/Default/Network/Cookies
    or in older versions:
        <profile_dir>/Default/Cookies

    Note: Chrome encrypts cookie values on Windows using DPAPI.
    This function handles both encrypted and unencrypted scenarios.

    Args:
        profile_dir: Path to the Chrome user data directory
                     (same as browser_profile_dir in settings.json).
        output_path: Path to write the cookies.json file.

    Returns:
        True if cookies were exported successfully, False otherwise.
    """
    profile_path = Path(profile_dir)

    # Locate the Cookies database file
    cookie_db_paths = [
        profile_path / "Default" / "Network" / "Cookies",
        profile_path / "Default" / "Cookies",
        profile_path / "Cookies",  # nodriver sometimes uses flat structure
    ]

    cookie_db = None
    for path in cookie_db_paths:
        if path.exists():
            cookie_db = path
            break

    if cookie_db is None:
        print(f"ERROR: Could not find Chrome Cookies database in: {profile_dir}")
        print("Searched paths:")
        for p in cookie_db_paths:
            print(f"  - {p}")
        print("\nTry the manual method instead: python -m execution.export_cookies --manual")
        return False

    print(f"Found cookie database: {cookie_db}")

    # Chrome locks the Cookies file while running.
    # Copy it to a temp location to avoid locking issues.
    temp_dir = tempfile.mkdtemp()
    temp_db = Path(temp_dir) / "Cookies_copy"

    try:
        shutil.copy2(str(cookie_db), str(temp_db))
    except PermissionError:
        print(
            "ERROR: Cannot copy cookie database. "
            "Close Chrome/browser completely and try again."
        )
        return False

    cookies: Dict[str, str] = {}

    try:
        conn = sqlite3.connect(str(temp_db))
        cursor = conn.cursor()

        # Query cookies for Petpooja domain
        cursor.execute(
            """
            SELECT name, value, encrypted_value, host_key
            FROM cookies
            WHERE host_key LIKE ?
            """,
            (f"%{TARGET_DOMAIN}%",),
        )

        rows = cursor.fetchall()
        print(f"Found {len(rows)} Petpooja cookies in the database.")

        for name, value, encrypted_value, host_key in rows:
            # Use the plain-text value if available
            if value:
                cookies[name] = value
            elif encrypted_value:
                # On Windows, Chrome encrypts cookie values with DPAPI.
                # Attempt decryption (requires running on the same Windows
                # user account that created the cookies).
                try:
                    decrypted = _decrypt_windows_cookie(encrypted_value)
                    if decrypted:
                        cookies[name] = decrypted
                    else:
                        print(
                            f"  WARNING: Could not decrypt cookie '{name}'. "
                            "Use --manual method for this cookie."
                        )
                except Exception:
                    print(
                        f"  WARNING: Decryption failed for '{name}'. "
                        "Use --manual method."
                    )

        conn.close()

    except sqlite3.OperationalError as e:
        print(f"ERROR: SQLite error: {e}")
        return False
    finally:
        # Cleanup temp file
        try:
            os.unlink(str(temp_db))
            os.rmdir(temp_dir)
        except Exception:
            pass

    if not cookies:
        print("ERROR: No cookies could be extracted.")
        print("Use the manual method: python -m execution.export_cookies --manual")
        return False

    # Check for required cookies
    missing = [c for c in REQUIRED_COOKIES if c not in cookies]
    if missing:
        print(f"WARNING: Missing required cookies: {missing}")
        print("The automation may fail without these. Consider using --manual method.")

    # Save to JSON
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(cookies, f, indent=2)

    print(f"\nSUCCESS: Exported {len(cookies)} cookies to {output_path}")
    print(f"Required cookies present: {[c for c in REQUIRED_COOKIES if c in cookies]}")
    return True


def _decrypt_windows_cookie(encrypted_value: bytes) -> Optional[str]:
    """
    Attempt to decrypt a Chrome cookie value on Windows using DPAPI.

    Chrome uses two encryption methods:
    - v10 prefix: AES-256-GCM with key from Local State
    - No prefix: Legacy DPAPI encryption

    Args:
        encrypted_value: The raw encrypted bytes from the SQLite database.

    Returns:
        Decrypted string value, or None if decryption fails.
    """
    if sys.platform != "win32":
        return None

    try:
        import win32crypt  # type: ignore[import-untyped]

        # Try legacy DPAPI decryption first
        if not encrypted_value.startswith(b"v10") and not encrypted_value.startswith(b"v11"):
            decrypted = win32crypt.CryptUnprotectData(
                encrypted_value, None, None, None, 0
            )
            return decrypted[1].decode("utf-8")
    except ImportError:
        print(
            "  NOTE: Install pywin32 for automatic cookie decryption: "
            "pip install pywin32"
        )
    except Exception:
        pass

    return None


def print_manual_guide() -> None:
    """
    Print step-by-step instructions for manually exporting cookies
    from Chrome DevTools into cookies.json.
    """
    print(
        """
╔══════════════════════════════════════════════════════════════╗
║          MANUAL COOKIE EXPORT GUIDE                         ║
╚══════════════════════════════════════════════════════════════╝

Follow these steps to manually create your cookies.json file:

1. Open Chrome and navigate to: https://billing.petpooja.com/
   (Make sure you are logged in)

2. Open DevTools (F12) → Application tab → Cookies →
   https://billing.petpooja.com

3. Copy the VALUE of these two critical cookies:
   - PETPOOJA_CO
   - CakeCookie[google_user_token]

4. Create a file called 'cookies.json' in the project root with:

   {
       "PETPOOJA_CO": "<paste PETPOOJA_CO value here>",
       "CakeCookie[google_user_token]": "<paste token value here>"
   }

5. Save the file. You're done!

OPTIONAL: Also include these cookies for better session stability:
   - _fbp
   - _ga
   - _gid
   - WZRK_G

NOTE: Cookies expire periodically. When the automation reports
"Session expired", repeat this process to refresh them.
"""
    )


if __name__ == "__main__":
    if "--manual" in sys.argv:
        print_manual_guide()
        sys.exit(0)

    # Load settings to find the browser profile directory
    settings_path = Path(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "settings.json")
    )

    if settings_path.exists():
        with open(settings_path, "r", encoding="utf-8") as f:
            settings = json.load(f)
        profile_dir = settings.get("browser_profile_dir", ".tmp/browser_profile")
    else:
        profile_dir = ".tmp/browser_profile"

    output = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "cookies.json"
    )

    print(f"Attempting to export cookies from: {profile_dir}")
    success = export_from_browser_profile(profile_dir, output)

    if not success:
        print("\nFalling back to manual instructions...")
        print_manual_guide()
