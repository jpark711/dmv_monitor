"""
fetch_appointments.py

Asynchronous scraper for the NJ MVC “License / Non‑Driver ID Renewal” appointment
listing page.

Key Features
------------
1. **Lazy Playwright Browser Install**: On first run (in a fresh container) it installs
   the Chromium browser. Subsequent runs reuse a marker file `.playwright_installed`
   to skip installation.
2. **Async Scraping with Playwright**: Collects all location cards and extracts:
      - Location name (city / site – first line of the header block)
      - Next available appointment (converted to uniform format "%Y-%m-%d %I:%M %p")
      - Google Maps link (if present in the card)
3. **Filtering**: Optional list of `target_locations` (case‑insensitive). When provided,
   only cards whose *location name* contains (substring match) any of those target
   strings are returned.
4. **Graceful Error Handling**: Skips cards with unexpected structure and logs parse
   errors without aborting the entire run.
5. **Configurability**: `headless`, `timeout_ms`, and `nav_timeout_ms` parameters.

Return Value
------------
A list of dictionaries (one per location) with keys:
    {
        "Location": <str>,
        "Next Available": <formatted date str OR "Unknown">,
        "Map Link": <str or "">
    }

The “Next Available” is formatted as: YYYY-MM-DD HH:MM AM/PM (12‑hour), or "Unknown"
if the text cannot be parsed.

Usage Example
-------------
    import asyncio
    from fetch_appointments import fetch_appointments

    rows = asyncio.run(fetch_appointments())
    for r in rows:
        print(r)

Integration Notes
-----------------
- Designed to be called from Streamlit or a headless scheduler script.
- Safe to import repeatedly; installation runs only once per environment.
- If running on Streamlit Community Cloud, include this file in the repo root
  (under `src/`) and ensure `playwright` is in `requirements.txt`.

"""

from __future__ import annotations

import asyncio
import re
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

# ------------------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------------------
APPOINTMENT_URL = "https://telegov.njportal.com/njmvc/AppointmentWizard/11"
DATE_PARSE_INPUT = "%m/%d/%Y %I:%M %p"
DATE_OUTPUT_FORMAT = "%Y-%m-%d %I:%M %p"

# CSS selectors (tuned to current site structure; adjust if site changes)
CARD_SELECTOR = "div.locationCard"
HEADER_SELECTOR = ".AppointcardHeader"
FOOTER_POSSIBLE = [
    "#cardFooter",          # (Observed id reused inside cards)
    ".cardFooter",
    ".footer",
]
# Pattern to detect the “Next Available:” text line
NEXT_AVAILABLE_PATTERN = re.compile(r"Next\s+Available:\s*(.+)", re.IGNORECASE)

# Lazy install marker
_PLAYWRIGHT_MARKER = Path(".playwright_installed")
_INSTALL_LOCK = threading.Lock()


# ------------------------------------------------------------------------------
# Playwright Lazy Installation
# ------------------------------------------------------------------------------
def ensure_playwright_installed() -> None:
    """
    Idempotently install the Chromium browser needed by Playwright.

    - Checks for a marker file `.playwright_installed`.
    - If absent, executes: `python -m playwright install chromium`.
    - Thread‑safe: a lock prevents duplicate concurrent installs.

    Raises:
        RuntimeError: If installation fails (non‑zero exit code).
    """
    if _PLAYWRIGHT_MARKER.exists():
        return

    with _INSTALL_LOCK:
        if _PLAYWRIGHT_MARKER.exists():
            return

        cmd = [
            sys.executable,
            "-m",
            "playwright",
            "install",
            "chromium",
            "--no-shell",
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                print("Playwright install failed output:\n", result.stdout, result.stderr)
                raise RuntimeError("Playwright browser installation failed.")
            _PLAYWRIGHT_MARKER.touch()
        except Exception as e:
            raise RuntimeError(f"Failed to install Playwright Chromium: {e}") from e


# ------------------------------------------------------------------------------
# Utility Functions
# ------------------------------------------------------------------------------
def _matches_target(location_name: str, target_locations: Optional[Sequence[str]]) -> bool:
    """
    Case-insensitive substring match for any target token in location_name.

    Args:
        location_name: The card's extracted location name (e.g., "Bayonne").
        target_locations: Optional list of substrings to filter by.

    Returns:
        True if no targets provided (include all), or one of the targets
        is a substring of the location name (case-insensitive).
    """
    if not target_locations:
        return True
    low = location_name.lower()
    return any(t.lower() in low for t in target_locations if t.strip())


def _extract_next_available(text_block: str) -> Optional[datetime]:
    """
    Extract the next available datetime from a text block.

    Args:
        text_block: Footer or full card text containing 'Next Available:' line.

    Returns:
        Parsed datetime object or None if parsing fails.

    Side note:
        We split after 'Next Available:' and take the first line segment.
    """
    match = NEXT_AVAILABLE_PATTERN.search(text_block)
    if not match:
        return None
    raw = match.group(1).strip().splitlines()[0].strip()
    try:
        return datetime.strptime(raw, DATE_PARSE_INPUT)
    except Exception:
        return None


async def _extract_card_data(card) -> dict:
    """
    Extract structured data from a single card element.

    Args:
        card: Playwright element handle for a location card.

    Returns:
        dict with keys: Location, Next Available (formatted or 'Unknown'), Map Link (string).
    """
    # Header / Location name
    location_name = "Unknown"
    try:
        header_el = await card.query_selector(HEADER_SELECTOR)
        if header_el:
            header_text = (await header_el.inner_text()).strip()
            # Card header often has multiple lines; location name usually first line
            location_name = header_text.splitlines()[0].strip()
    except Exception:
        pass

    # Footer text (for Next Available)
    footer_text = ""
    for sel in FOOTER_POSSIBLE:
        try:
            el = await card.query_selector(sel)
            if el:
                footer_text = (await el.inner_text()).strip()
                if footer_text:
                    break
        except Exception:
            continue

    # Parse date
    appt_dt = _extract_next_available(footer_text)
    if appt_dt:
        appt_str = appt_dt.strftime(DATE_OUTPUT_FORMAT)
    else:
        appt_str = "Unknown"

    # Map Link detection
    map_link = ""
    try:
        link_el = await card.query_selector('a[href*="maps.google"]')
        if link_el:
            href = await link_el.get_attribute("href")
            if href:
                map_link = href
    except Exception:
        pass

    return {
        "Location": location_name,
        "Next Available": appt_str,
        "Map Link": map_link,
    }


# ------------------------------------------------------------------------------
# Public Scrape Function
# ------------------------------------------------------------------------------
async def fetch_appointments(
    target_locations: Optional[Sequence[str]] = None,
    headless: bool = True,
    timeout_ms: int = 25_000,
    nav_timeout_ms: int = 25_000,
) -> List[dict]:
    """
    Scrape the NJ MVC appointment wizard page and collect appointment data.

    Args:
        target_locations:
            Optional list of substrings. If provided, only location cards whose
            *location name* contains any of these substrings (case-insensitive)
            are included in the result.
        headless:
            Whether to run the Chromium browser in headless mode (recommended True
            for server / CI usage).
        timeout_ms:
            Timeout (milliseconds) for waiting on the card selector to appear.
        nav_timeout_ms:
            Navigation timeout for page.goto (milliseconds).

    Returns:
        A list of dictionaries with keys:
            - "Location"
            - "Next Available" (formatted string YYYY-MM-DD HH:MM AM/PM or "Unknown")
            - "Map Link" (Google Maps URL or "")

    Raises:
        RuntimeError: If Playwright installation fails.
    """
    ensure_playwright_installed()

    # Windows event loop policy (useful when called outside Streamlit; safe no-op elsewhere)
    if sys.platform.startswith("win"):
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass

    results: List[dict] = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            context = await browser.new_context()
            page = await context.new_page()
            page.set_default_navigation_timeout(nav_timeout_ms)
            page.set_default_timeout(timeout_ms)

            await page.goto(APPOINTMENT_URL)

            # Wait for location cards
            try:
                await page.wait_for_selector(CARD_SELECTOR, timeout=timeout_ms)
            except PlaywrightTimeoutError:
                await browser.close()
                return results  # return empty list if structure not found

            cards = await page.query_selector_all(CARD_SELECTOR)

            for card in cards:
                try:
                    info = await _extract_card_data(card)
                    if _matches_target(info["Location"], target_locations):
                        results.append(info)
                except Exception:
                    # Skip problematic card but continue
                    continue

            await browser.close()

    except Exception as e:
        # Log & bubble up partial/no results if needed
        print(f"[fetch_appointments] Error: {e}")

    # Deduplicate by Location keeping earliest date (if duplicates appear)
    dedup: dict[str, dict] = {}
    for r in results:
        key = r["Location"]
        existing = dedup.get(key)
        if existing is None:
            dedup[key] = r
        else:
            # Compare dates if both parseable
            def parse_out(s: str):
                try:
                    return datetime.strptime(s, DATE_OUTPUT_FORMAT)
                except Exception:
                    return None

            new_dt = parse_out(r["Next Available"])
            old_dt = parse_out(existing["Next Available"])
            if new_dt and (old_dt is None or new_dt < old_dt):
                dedup[key] = r

    # Return in sorted order by date if possible
    def sort_key(item):
        dt_str = item.get("Next Available", "")
        try:
            return datetime.strptime(dt_str, DATE_OUTPUT_FORMAT)
        except Exception:
            # Unknown dates go last
            return datetime.max

    sorted_results = sorted(dedup.values(), key=sort_key)
    return sorted_results


# ------------------------------------------------------------------------------
# Stand-alone test runner
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    print("🚀 Running standalone fetch test...")
    rows = asyncio.run(fetch_appointments())
    if not rows:
        print("No data scraped (check selectors or connectivity).")
    else:
        from pprint import pprint

        pprint(rows)
        print(f"\nTotal locations: {len(rows)}")
