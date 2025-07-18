"""
app.py

NJ DMV Appointment Monitor (simplified UI)

What it does:
- Shows all current “License / Non‑Driver ID Renewal” appointment dates.
- Highlights any appointment earlier than the cutoff date you choose.
- Can email you ONLY when a *new earlier* slot appears at locations you care about
  (if email alerts are enabled in config and via the sidebar toggle).
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime

import nest_asyncio
import pandas as pd
import streamlit as st

from config import APP_CONFIG, EMAIL_CONFIG
from fetch_appointments import fetch_appointments
from send_email import (
    filter_new_earliest,
    load_state,
    prepare_notification_body,
    save_state,
    send_email,
)

# Windows event loop setup
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
nest_asyncio.apply()

# Constants
APPOINTMENT_PAGE_URL = "https://telegov.njportal.com/njmvc/AppointmentWizard/11"
REFRESH_MINUTES = APP_CONFIG.refresh_minutes
REFRESH_SECS = REFRESH_MINUTES * 60
REFRESH_MS = REFRESH_SECS * 1000
DATE_FORMAT = "%Y-%m-%d %I:%M %p"

HIGHLIGHT_ROW_STYLE = (
    "background-color:#1b5e20;"
    "color:#ffffff;"
    "font-weight:600;"
    "border-left:6px solid #00e676;"
)


# ---------------------------------------------------------------------------
# Cached scrape
# ---------------------------------------------------------------------------
@st.cache_data(ttl=REFRESH_SECS)
def load_appointments_cached():
    """
    Scrape and cache appointment data for REFRESH_MINUTES.
    """
    return asyncio.run(
        fetch_appointments(
            target_locations=None,
            headless=APP_CONFIG.headless,
            timeout_ms=APP_CONFIG.scrape_timeout_ms,
        )
    )


# ---------------------------------------------------------------------------
# Table styling
# ---------------------------------------------------------------------------
def build_highlight_styler(df: pd.DataFrame, early_mask: pd.Series):
    """
    Highlight rows where early_mask == True.
    """
    def style_row(row):
        return [HIGHLIGHT_ROW_STYLE] * len(row) if early_mask.loc[row.name] else [""] * len(row)

    styler = df.style.apply(style_row, axis=1).set_table_styles(
        [
            {
                "selector": "table",
                "props": [
                    ("border-collapse", "collapse"),
                    ("width", "100%"),
                    ("font-size", "0.90rem"),
                ],
            }
        ]
    )
    try:
        styler = styler.hide(axis="index")
    except Exception:
        pass
    return styler


# ---------------------------------------------------------------------------
# Email notification
# ---------------------------------------------------------------------------
def maybe_send_notifications(
    df: pd.DataFrame,
    cutoff_date: date,
    alert_locations: list[str],
    send_enabled: bool,
):
    """
    Send one email if any chosen DMV gets a NEW earlier slot (strictly earlier than previous).
    """
    if not send_enabled:
        return
    if not APP_CONFIG.enable_email:
        return
    if not EMAIL_CONFIG.user or not EMAIL_CONFIG.password:
        return
    if not alert_locations:
        return
    if df.empty:
        return

    targets = {x.strip().lower() for x in alert_locations if x.strip()}
    parsed = df["ParsedDateTime"]
    match_mask = df["Location"].astype(str).str.strip().str.lower().isin(targets)
    early_mask = match_mask & parsed.notna() & (parsed.dt.date < cutoff_date)
    early_rows = df.loc[early_mask, ["Location", "Next Available", "Map Link"]].to_dict("records")

    if not early_rows:
        return

    state = load_state()
    new_rows = filter_new_earliest(early_rows, state)
    if not new_rows:
        return

    body = prepare_notification_body(new_rows, cutoff_date, APPOINTMENT_PAGE_URL)
    try:
        asyncio.run(send_email("Earlier Appointment Found", body))
        for r in new_rows:
            state[r["Location"]] = r["Next Available"]
        save_state(state)
        st.success(f"📧 Sent email for {len(new_rows)} new earlier appointment(s).")
    except Exception as e:
        st.error(f"Email failed: {e}")


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------
def main():
    st.set_page_config(page_title="NJ DMV Appointment Monitor", layout="wide")

    # Auto refresh
    try:
        from streamlit_autorefresh import st_autorefresh
        refresh_count = st_autorefresh(interval=REFRESH_MS, key="auto_refresh")
    except Exception:
        refresh_count = None
        st.markdown(
            f"<meta http-equiv='refresh' content='{REFRESH_SECS}'>",
            unsafe_allow_html=True,
        )

    st.title("🚗 NJ DMV Appointment Monitor")

    st.caption(
        f"Refreshes every {REFRESH_MINUTES} min • Loaded at {datetime.now():%Y-%m-%d %H:%M:%S}"
        + (f" • Refresh #{refresh_count}" if refresh_count is not None else "")
    )

    # Persistent email toggle state
    if "send_email_enabled" not in st.session_state:
        st.session_state.send_email_enabled = True

    # Get (cached) data early for sidebar population
    rows = load_appointments_cached()
    if not rows:
        st.warning("No appointments found right now.")
        return

    temp_df = pd.DataFrame(rows)
    all_locations = sorted(temp_df["Location"].unique()) if not temp_df.empty else []

    # Sidebar
    with st.sidebar:
        st.header("E-mail Alerts")

        cutoff = st.date_input(
            "Cutoff date:",
            APP_CONFIG.default_cutoff_date,
            help="Highlight & watch for appointments strictly *before* this date.",
        )

        if APP_CONFIG.enable_email:
            default_alert_selection = (
                sorted(APP_CONFIG.target_dmvs) if APP_CONFIG.target_dmvs else all_locations
            )
            alert_locations = st.multiselect(
                "E-mail me for these DMVs:",
                options=all_locations,
                default=default_alert_selection,
                help="Only these locations can trigger emails.",
            )

            st.session_state.send_email_enabled = st.checkbox(
                "Send e-mail notification",
                value=st.session_state.send_email_enabled,
                help="Turn automatic alert emails on or off.",
            )

            with st.expander("How e-mail alerts work"):
                st.markdown(
                    """
- Rows earlier than the cutoff date are highlighted.
- Emails are only sent for DMVs you select.
- You get an email only when a **new earlier** time appears (per DMV).
- Turn the toggle off to pause emails any time.
                    """
                )
        else:
            alert_locations = []
            st.info("Email alerts are disabled in configuration (ENABLE_EMAIL=0).")

    # Build final DataFrame for display
    df = pd.DataFrame(rows)
    parsed = pd.to_datetime(df["Next Available"], format=DATE_FORMAT, errors="coerce")
    df = (
        df.assign(ParsedDateTime=parsed)
        .sort_values("ParsedDateTime", kind="stable")
        .reset_index(drop=True)
    )

    # Highlight mask
    early_mask_display = df["ParsedDateTime"].notna() & (df["ParsedDateTime"].dt.date < cutoff)
    display_df = df[["Location", "Next Available", "Map Link"]].copy()

    # Make Map Link clickable
    def to_anchor(val: str) -> str:
        if isinstance(val, str) and val.startswith("http"):
            return f'<a href="{val}" target="_blank">Map</a>'
        return val

    display_df["Map Link"] = display_df["Map Link"].map(to_anchor)
    display_df.columns = ['Location', 'Next Available', 'Directions']

    st.success(f"Showing {len(display_df)} DMV locations.")

    # Render highlighted table (escape=False so links work)
    styler = build_highlight_styler(display_df, early_mask_display)
    st.markdown("### 📅 Appointments")
    st.markdown(styler.to_html(escape=False), unsafe_allow_html=True)

    # Email notifications (only if config + toggle + selection)
    maybe_send_notifications(
        df=df,
        cutoff_date=cutoff,
        alert_locations=alert_locations,
        send_enabled=st.session_state.send_email_enabled,
    )

    # Footer link
    st.markdown(
        f"""
        <div style="margin:2rem 0;text-align:left;">
          <a href="{APPOINTMENT_PAGE_URL}" target="_blank"
             style="background:linear-gradient(90deg,#b5bcc2,#8e959b);color:#fff;
             padding:8px 16px;border-radius:6px;text-decoration:none;font-weight:500;">
             📄 Open NJ MVC Appointment Page
          </a>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"<small>Next refresh in about {REFRESH_MINUTES} minute(s). Adjust the cutoff date or alert DMVs any time.</small>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
