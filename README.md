# Petpooja Automation Pipeline

A robust, headless automation pipeline designed to extract reports from Petpooja and synchronize them with a PostgreSQL database.

## Architecture
- **Extraction:** Powered by **Playwright (Firefox)**. Uses persistent browser profiles to bypass 1-time OTP requirements on servers.
- **Processing:** Automated data cleaning and transformation via **Pandas**.
- **Storage:** Direct ingestion into **PostgreSQL** with upsert logic to prevent duplicate records.
- **Timezone Aware:** Specifically designed for Indian Standard Time (IST) to ensure correct date resolution on UTC-based cloud servers.

## Project Structure
- `main.py`: The central orchestrator and entry point.
- `execution/`: Core logic modules (Playwright automation, data cleaning, and database uploading).
- `.tmp/playwright_profile/`: **Critical Folder.** Contains the authenticated browser session.
- `archive/`: Supporting scripts and documentation.
- `logs/`: Daily rotating execution logs (automated 30-day cleanup).

## Quick Start (Local)
1. Install dependencies: `pip install -r requirements.txt`
2. Install Playwright: `playwright install firefox`
3. Configure `.env` and `settings.json` with your credentials.
4. Run for yesterday: `python main.py`
5. Run for specific date: `python main.py 2026-02-20`

## Deployment
For detailed server setup instructions (Debian/Ubuntu/AWS), refer to the guide in [archive/playwright_deployment.md](archive/playwright_deployment.md).
