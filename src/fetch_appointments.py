"""
fetch_appointments.py
=====================

Playwright-based scraper for the NJ MVC *License / Non-Driver ID Renewal* appointment page.

**Output**
A list of dictionaries:
    - "Location": str
    - "Next Available": formatted date string `%Y-%m-%d %I:%M %p`
    - "Map Link": Google Maps URL or `"N/A"`

**Usage (Standalone)**
    python fetch_appointments.py

**Usage (Import)**
    from fetch_appointments import fetch_appointments
    import asyncio
    rows = asyncio.run(fetch_appointments())

**Notes / Considerations**
- Selectors may change; if scraping breaks, inspect live DOM and adjust.
- Respect the site’s terms of service and avoid excessive request frequency.
- Headless mode is configurable; run headful for debugging.
"""

from __future__ import annotations
import sys
import asyncio
from datetime import datetime
from typing import List, Dict, Iterable, Optional
from playwright.async_api import (
    async_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

APPOINTMENT_URL = "https://telegov.njportal.com/njmvc/AppointmentWizard/11"
DATE_INPUT_FORMATS = ["%m/%d/%Y %I:%M %p"]
OUTPUT_DATE_FORMAT = "%Y-%m-%d %I:%M %p"

# Windows event loop policy fix for Playwright
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


# --------------------------------------------------------------------------------------
# Internal Helpers
# --------------------------------------------------------------------------------------
def _parse_date(raw: str) -> datetime | None:
    """
    Try multiple input formats to parse a raw date string.

    Args:
        raw: Date string extracted from webpage.

    Returns:
        datetime instance or None if parsing fails.
    """
    raw = raw.strip()
    for fmt in DATE_INPUT_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _fmt_date(dt: datetime) -> str:
    """
    Format a datetime in the canonical output format.

    Args:
        dt: Parsed datetime.

    Returns:
        Formatted string (YYYY-MM-DD HH:MM AM/PM).
    """
    return dt.strftime(OUTPUT_DATE_FORMAT)


# --------------------------------------------------------------------------------------
# Public Scraper
# --------------------------------------------------------------------------------------
async def fetch_appointments(
    target_locations: Optional[Iterable[str]] = None,
    headless: bool = True,
    timeout_ms: int = 25_000,
) -> List[Dict[str, str]]:
    """
    Scrape the NJ MVC appointment list.

    Args:
        target_locations: If provided, a collection of substrings; only matching
                          locations (case-insensitive) are returned.
        headless: Run Chromium in headless mode (set False for debugging).
        timeout_ms: Page navigation / wait timeout in milliseconds.

    Returns:
        List of dictionaries describing appointments.
    """
    target_set = {t.lower() for t in target_locations} if target_locations else None
    results: List[Dict[str, str]] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        page = await browser.new_page()
        try:
            await page.goto(APPOINTMENT_URL, timeout=timeout_ms)
        except PlaywrightTimeoutError:
            await browser.close()
            return results

        # Try multiple card selectors for robustness
        selectors = ["div.locationCard", "div.cardlocationcard"]
        cards = []
        for sel in selectors:
            try:
                await page.wait_for_selector(sel, timeout=7000)
                cards = await page.query_selector_all(sel)
                if cards:
                    break
            except PlaywrightTimeoutError:
                continue

        if not cards:
            await browser.close()
            return results

        for card in cards:
            # Header variations
            header_el = (
                await card.query_selector(".AppointcardHeader")
                or await card.query_selector(".appointmentcardheader")
                or await card.query_selector("span.appointmentcardheader")
            )
            if not header_el:
                continue
            raw_header = (await header_el.inner_text()).strip()
            location_name = raw_header.split("\n")[0].strip()

            if target_set and all(t not in location_name.lower() for t in target_set):
                continue

            # Footer containing next availability
            footer_el = await card.query_selector(
                "#cardFooter"
            ) or await card.query_selector("div.cardfooter")
            if not footer_el:
                continue

            footer_text = await footer_el.inner_text()
            if "Next Available:" not in footer_text:
                continue

            try:
                date_fragment = (
                    footer_text.split("Next Available:", 1)[1]
                    .strip()
                    .split("\n")[0]
                    .strip()
                )
            except Exception:
                continue

            parsed_dt = _parse_date(date_fragment)
            if not parsed_dt:
                continue

            # Map link (if present)
            map_el = await card.query_selector("a[href*='google.com/maps']")
            map_url = await map_el.get_attribute("href") if map_el else "N/A"

            results.append(
                {
                    "Location": location_name,
                    "Next Available": _fmt_date(parsed_dt),
                    "Map Link": map_url,
                }
            )

        await browser.close()

    return results


# --------------------------------------------------------------------------------------
# Standalone Execution
# --------------------------------------------------------------------------------------
if __name__ == "__main__":
    import json

    rows = asyncio.run(fetch_appointments())
    print(json.dumps(rows, indent=2))
