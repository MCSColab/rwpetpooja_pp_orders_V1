"""
Petpooja Playwright Fallback Automation.

This module provides a headless browser fallback when the fast `requests`
pipeline fails (e.g., due to expired session cookies).

Architecture:
    1. Launches a headless Firefox instance using Playwright.
    2. Uses a persistent profile directory (`.tmp/playwright_profile`) to retain
       session state across runs.
    3. Navigates to Petpooja. If not authenticated, performs a UI login sequence.
    4. Navigates to the report dashboard, selects the target date, and triggers
       the export.
    5. Extracts the updated session cookies and saves them back to `cookies.json`,
       repairing the fast `requests` pipeline for future runs.
    6. Returns the downloaded CSV file path.
"""

import os
import sys
import json
import asyncio
import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

from playwright.async_api import async_playwright, Page, BrowserContext
from execution.logger_helper import LoggerHelper
from execution.file_downloader import download_file


class PlaywrightAutomation:
    """
    Playwright-based browser automation for Petpooja.
    """

    def __init__(self, settings_path: str = "settings.json"):
        self.logger_helper = LoggerHelper()
        self.logger = self.logger_helper.logger

        with open(settings_path, "r", encoding="utf-8") as f:
            self.settings = json.load(f)

        self.username = os.getenv("PETPOOJA_USERNAME")
        self.password = os.getenv("PETPOOJA_PASSWORD")

        self.download_dir = Path(self.settings.get("download_dir", ".tmp/downloads"))
        self.download_dir.mkdir(parents=True, exist_ok=True)

        self.profile_dir = Path(self.settings.get("playwright_profile_dir", ".tmp/playwright_profile"))
        self.profile_dir.mkdir(parents=True, exist_ok=True)

        self.cookie_file = Path(self.settings.get("cookie_file", "cookies.json"))

    async def run(self, target_date: Optional[datetime.date] = None) -> Optional[Path]:
        """
        Execute the full Playwright fallback pipeline.

        Args:
            target_date: Date to download the report for.

        Returns:
            Path to the downloaded CSV, or None if failed.
        """
        if target_date is None:
            target_date = datetime.date.today() - datetime.timedelta(days=1)

        self.logger.info(f"[FALLBACK] Starting Playwright automation for {target_date}")

        async with async_playwright() as p:
            # Launch persistent Firefox context
            # Firefox is much lighter on RAM (~350MB) compared to Chromium (~600MB+)
            try:
                context = await p.firefox.launch_persistent_context(
                    user_data_dir=str(self.profile_dir),
                    headless=True,
                    args=["--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage"],
                    viewport={"width": 1280, "height": 720},
                    accept_downloads=True
                )
            except Exception as e:
                self.logger.error(f"[FALLBACK] Failed to launch Playwright: {e}")
                return None

            try:
                page = context.pages[0] if context.pages else await context.new_page()

                # 1. Login Flow
                logged_in = await self._ensure_logged_in(page)
                if not logged_in:
                    self.logger.error("[FALLBACK] Failed to authenticate.")
                    return None

                # 2. Export Cookies to repair the fast route
                await self._export_cookies_to_json(context)

                # 3. Export Report
                report_url = await self._trigger_and_get_download_link(page, target_date)
                if not report_url:
                    self.logger.error(f"[FALLBACK] Failed to extract download link for {target_date}")
                    return None

                # 4. Download File
                target_path = self.download_dir / f"{target_date}_report.csv"
                self.logger.info(f"[FALLBACK] Downloading report to {target_path}")
                success = download_file(report_url, str(target_path))

                if success and target_path.exists() and target_path.stat().st_size > 0:
                    self.logger.info(f"[FALLBACK] Download completed successfully: {target_path.name}")
                    return target_path
                else:
                    self.logger.error("[FALLBACK] File download failed or resulted in 0 bytes.")
                    return None

            finally:
                await context.close()

    async def _ensure_logged_in(self, page: Page) -> bool:
        """
        Navigate to Petpooja and perform login if necessary.
        """
        report_url = self.settings.get("petpooja_url", "https://billing.petpooja.com/reports/order_summary_ho")
        self.logger.info(f"[FALLBACK] Navigating to {report_url}")
        
        await page.goto(report_url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3)

        # Check if we were redirected to login
        if "login" not in page.url.lower():
            self.logger.info("[FALLBACK] Already authenticated via persistent profile.")
            return True

        self.logger.info("[FALLBACK] Session expired in profile. Attempting UI login...")

        if not self.username or not self.password:
            self.logger.error("[FALLBACK] Missing credentials in .env. Cannot auto-login.")
            return False

        try:
            # Standard Petpooja Login Flow
            email_input = page.locator("input[name*='email'], #UserEmail").first
            await email_input.wait_for(timeout=10000)
            await email_input.fill(self.username)
            
            continue_btn = page.locator("button[type='submit'], button:has-text('Continue')").first
            await continue_btn.click()
            await asyncio.sleep(2)

            password_input = page.locator("input[type='password'], #UserPassword").first
            await password_input.wait_for(timeout=5000)
            await password_input.fill(self.password)

            signin_btn = page.locator("button[type='submit'], button:has-text('Sign In')").first
            await signin_btn.click()

            # Wait for dashboard
            await page.wait_for_url("**/dashboard*", timeout=15000)
            self.logger.info("[FALLBACK] Login successful.")

            # Navigate to reports page if needed
            if report_url not in page.url:
                await page.goto(report_url, wait_until="domcontentloaded")
                await asyncio.sleep(2)

            return True

        except Exception as e:
            self.logger.error(f"[FALLBACK] Automated UI login failed: {e}")
            return False

    async def _export_cookies_to_json(self, context: BrowserContext) -> None:
        """
        Extract billing.petpooja.com cookies and save to cookies.json.
        """
        try:
            cookies = await context.cookies("https://billing.petpooja.com")
            cookie_dict = {c["name"]: c["value"] for c in cookies}

            if not cookie_dict:
                self.logger.warning("[FALLBACK] No cookies found for petpooja.com")
                return

            with open(self.cookie_file, "w", encoding="utf-8") as f:
                json.dump(cookie_dict, f, indent=2)

            self.logger.info(f"[FALLBACK] Extracted and saved {len(cookie_dict)} cookies to {self.cookie_file.name}. Fast route repaired.")
        except Exception as e:
            self.logger.error(f"[FALLBACK] Failed to export cookies: {e}")

    async def _trigger_and_get_download_link(self, page: Page, target_date: datetime.date) -> Optional[str]:
        """
        Set date inputs, click export, and extract S3 URL.
        """
        date_str = target_date.strftime("%Y-%m-%d")
        
        try:
            # 1. Intercept the AJAX response directly to get the URL
            # This is more robust than scraping the DOM table
            ajax_url = "https://billing.petpooja.com/reports/order_summary_ho_ajax/0"
            
            download_url = None
            
            async def handle_response(response):
                nonlocal download_url
                if response.url == ajax_url and response.status == 200:
                    try:
                        data = await response.json()
                        directories = data.get("directory_path", "")
                        files = data.get("file_name", [])
                        
                        date_range = f"{date_str} to {date_str}"
                        for file_info in files:
                            if file_info.get("date") == date_range:
                                download_url = directories.replace("\\/", "/") + file_info["name"]
                                break
                    except Exception:
                        pass
                        
            page.on("response", handle_response)

            # 2. Fill dates using JS (since they are datepickers)
            await page.evaluate(f'document.querySelector("#from_date").value = "{date_str}";')
            await page.evaluate(f'document.querySelector("#to_date").value = "{date_str}";')

            # 3. Click Export
            export_btn = page.locator("#order_searc1h, button:has-text('Export')").first
            await export_btn.click()
            self.logger.info("[FALLBACK] Clicked Export button.")

            # 4. Wait for the response handler to catch the URL
            for _ in range(15):
                if download_url:
                    self.logger.info(f"[FALLBACK] Extracted S3 URL from network: {download_url}")
                    return download_url
                await asyncio.sleep(1)

            self.logger.warning("[FALLBACK] Network interception timed out. Fallback to DOM parsing...")

            # Fallback string
            # Petpooja sometimes renders dates simply as "28-02-2026" or similar, 
            # so we'll do a partial match instead of an exact match
            date_search = target_date.strftime("%d-%m-%Y")
            date_search_alt = target_date.strftime("%Y-%m-%d")
            js_code = f'''
            (() => {{
                const rows = document.querySelectorAll('#reports_data tr');
                for (const row of rows) {{
                    const dateCell = row.querySelector('td:first-child');
                    if (dateCell && (dateCell.textContent.includes("{date_search}") || dateCell.textContent.includes("{date_search_alt}"))) {{
                        const link = row.querySelector('a[href*="s3"]');
                        if (link) return link.href;
                    }}
                }}
                return null;
            }})()
            '''
            
            for _ in range(15):
                dom_url = await page.evaluate(js_code)
                if dom_url:
                    self.logger.info(f"[FALLBACK] Extracted S3 URL from DOM: {dom_url}")
                    return dom_url
                await asyncio.sleep(1)

            return None
            
        except Exception as e:
            self.logger.error(f"[FALLBACK] Error during export trigger: {e}")
            return None


if __name__ == "__main__":
    # Test standalone execution
    async def main():
        bot = PlaywrightAutomation()
        res = await bot.run()
        if res:
            print(f"Success: {res}")
        else:
            print("Failed")
            sys.exit(1)
            
    asyncio.run(main())
