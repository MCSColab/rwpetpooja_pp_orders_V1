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

        self.logs_dir = Path("logs")
        self.logs_dir.mkdir(parents=True, exist_ok=True)

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
                # 2. Export Report
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

            except Exception as outer_e:
                self.logger.error(f"[FALLBACK] Unhandled exception in Playwright execution: {outer_e}")
                # We attempt to capture the error state if page was instantiated
                if 'page' in locals() and page:
                    await self._capture_error_state(page, target_date)
                return None

            finally:
                await context.close()

    async def _capture_error_state(self, page: Page, target_date: datetime.date) -> None:
        """
        Capture a screenshot and the HTML source of the current page for debugging.
        Saves files to the logs directory.
        """
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            base_name = f"error_{target_date}_{timestamp}"
            
            # 1. Take Screenshot
            screenshot_path = self.logs_dir / f"{base_name}.png"
            await page.screenshot(path=str(screenshot_path), full_page=True)
            self.logger.info(f"[FALLBACK] Error screenshot saved to {screenshot_path}")
            
            # 2. Save HTML Source
            html_content = await page.content()
            html_path = self.logs_dir / f"{base_name}.html"
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            self.logger.info(f"[FALLBACK] Error HTML source saved to {html_path}")
        except Exception as e:
            self.logger.error(f"[FALLBACK] Failed to capture error state: {e}")

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

            # Attempt robust Javascript date injection covering any date input
            js_date_injector = f"""
            (() => {{
                const inputs = document.querySelectorAll('input');
                let found = 0;
                inputs.forEach(i => {{
                    if (i.value && i.value.match(/^\\d{{4}}-\\d{{2}}-\\d{{2}}$/)) {{
                        i.value = "{date_str}";
                        i.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        i.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        found++;
                    }}
                }});
                
                // Fallback targeted attempts in case they are empty
                const fromInput = document.querySelector('input[name="from_date"]') || document.querySelector('#from_date');
                const toInput = document.querySelector('input[name="to_date"]') || document.querySelector('#to_date');
                if (fromInput) {{ fromInput.value = "{date_str}"; fromInput.dispatchEvent(new Event('change', {{bubbles:true}})); found++; }}
                if (toInput) {{ toInput.value = "{date_str}"; toInput.dispatchEvent(new Event('change', {{bubbles:true}})); found++; }}
                
                return found;
            }})()
            """
            
            try:
                # Give page a moment to render components
                await asyncio.sleep(2)  
                affected_inputs = await page.evaluate(js_date_injector)
                self.logger.info(f"[FALLBACK] JS injected date into {affected_inputs} inputs.")
            except Exception as wait_err:
                self.logger.warning(f"[FALLBACK] Could not set dates via JS: {wait_err}")

            # 3. Click Export
            export_btn = page.locator("#order_search, button:has-text('Export'), a:has-text('Export')").first
            await export_btn.scroll_into_view_if_needed()
            await export_btn.click(force=True)
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
            await self._capture_error_state(page, target_date)
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
