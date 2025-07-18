"""
send_email.py
=============

Minimal email notification utilities plus duplicate notification suppression.

Capabilities
------------
- Send plain‑text email alerts via SMTP (implicit TLS or STARTTLS).
- Track previously notified earliest appointment per location in a JSON state file.
- Prevent redundant notifications unless a *new earlier* time appears.

State File
----------
state/notification_state.json stores:
    {
      "Location Name": "YYYY-MM-DD HH:MM AM/PM",
      ...
    }
Delete this file to reset duplicate suppression.

Security
--------
- SMTP password is NEVER read from YAML; only from environment (EMAIL_PASS).
- No passwords are logged.
- If you accidentally committed a .env file, revoke the app password and create a new one.

Quick Usage (Programmatic)
--------------------------
    import asyncio
    from send_email import send_email

    async def demo():
        await send_email("Test Subject", "This is only a test.")

    asyncio.run(demo())

Command Line Test
-----------------
From the project root (after activating your virtual environment and setting EMAIL_* env vars):

    python src/send_email.py --subject "DMV Monitor Test" --body "If you received this, email works."

Add --dry-run to preview without sending:

    python src/send_email.py --subject "Preview" --body "No send" --dry-run
"""

from __future__ import annotations

import json
import argparse
from email.message import EmailMessage
from datetime import datetime
from typing import Dict, List
import aiosmtplib

from config import EMAIL_CONFIG, NOTIFICATION_STATE_FILE


# --------------------------------------------------------------------------------------
# State Management
# --------------------------------------------------------------------------------------
def load_state() -> Dict[str, str]:
    """
    Load previously recorded earliest appointment times per location.

    Returns:
        Dict mapping location -> earliest notified timestamp (string).
    """
    if NOTIFICATION_STATE_FILE.exists():
        try:
            return json.loads(NOTIFICATION_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state: Dict[str, str]) -> None:
    """
    Persist notification state to disk (best effort).

    Args:
        state: Updated mapping.
    """
    try:
        NOTIFICATION_STATE_FILE.write_text(
            json.dumps(state, indent=2), encoding="utf-8"
        )
    except Exception:
        pass  # Ignore write errors silently.


# --------------------------------------------------------------------------------------
# Email Sending
# --------------------------------------------------------------------------------------
async def send_email(subject: str, body: str) -> None:
    """
    Send a plain‑text email.

    Args:
        subject: Subject (prefix applied automatically).
        body: Plain text content.

    Behavior:
        - Skips silently if credentials or recipients are missing.
        - Uses implicit TLS (port 465) if EMAIL_USE_TLS=1 and STARTTLS disabled.
    """
    cfg = EMAIL_CONFIG
    if not cfg.user or not cfg.password:
        print("[EMAIL] Missing credentials; skipping.")
        return
    recipients = cfg.recipients()
    if not recipients:
        print("[EMAIL] No recipients resolved; skipping.")
        return

    msg = EmailMessage()
    msg["From"] = cfg.from_addr
    msg["To"] = ", ".join(recipients)
    full_subject = f"{cfg.subject_prefix} {subject}".strip()
    msg["Subject"] = full_subject
    msg.set_content(body)

    if cfg.use_tls and not cfg.use_starttls:
        # Implicit TLS (e.g. port 465)
        await aiosmtplib.send(
            msg,
            hostname=cfg.host,
            port=cfg.port,
            username=cfg.user,
            password=cfg.password,
            use_tls=True,
        )
    else:
        # Plain or STARTTLS
        client = aiosmtplib.SMTP(hostname=cfg.host, port=cfg.port, use_tls=False)
        await client.connect()
        if cfg.use_starttls:
            await client.starttls()
        await client.login(cfg.user, cfg.password)
        await client.send_message(msg)
        await client.quit()

    print(f"[EMAIL] Sent: {full_subject}")


# --------------------------------------------------------------------------------------
# Notification Content & Filtering
# --------------------------------------------------------------------------------------
def prepare_notification_body(rows: List[dict], cutoff_date, booking_url: str) -> str:
    """
    Build email body listing early appointments.

    Args:
        rows: Appointment dicts (Location, Next Available, Map Link).
        cutoff_date: Date threshold used.
        booking_url: Official booking portal URL.

    Returns:
        Formatted multi-line string.
    """
    lines = [f"Early NJ MVC Appointments before {cutoff_date}:", ""]
    for r in rows:
        lines.append(f"- {r['Location']}: {r['Next Available']} | Map: {r['Map Link']}")
    lines += ["", f"Book here: {booking_url}", "Automated notice."]
    return "\n".join(lines)


def filter_new_earliest(early_rows: List[dict], state: Dict[str, str]) -> List[dict]:
    """
    Return rows that are new earlier appointments (per location).

    Args:
        early_rows: Candidate early appointment rows.
        state: Mapping of previously notified earliest times.

    Returns:
        Subset of early_rows that represent a strictly earlier time or a new location.
    """
    new_rows: List[dict] = []
    for row in early_rows:
        loc = row["Location"]
        current_str = row["Next Available"]
        prev_str = state.get(loc)
        try:
            current_dt = datetime.strptime(current_str, "%Y-%m-%d %I:%M %p")
            prev_dt = (
                datetime.strptime(prev_str, "%Y-%m-%d %I:%M %p") if prev_str else None
            )
            if prev_dt is None or current_dt < prev_dt:
                new_rows.append(row)
        except Exception:
            # Treat unparsable as new (safe fallback).
            new_rows.append(row)
    return new_rows


# --------------------------------------------------------------------------------------
# CLI Test Harness
# --------------------------------------------------------------------------------------
def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Send or preview a test email using current EMAIL_* configuration."
    )
    parser.add_argument(
        "--subject",
        default="DMV Monitor Test",
        help="Subject line (default: %(default)s)",
    )
    parser.add_argument(
        "--body",
        default="This is a test email from the DMV monitor.",
        help="Plaintext body (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the would-be email instead of sending.",
    )
    return parser


def main():
    """
    Command-line entry point for ad-hoc testing.

    Validates config, performs optional dry-run, or sends a message.
    """
    parser = _build_arg_parser()
    args = parser.parse_args()

    cfg = EMAIL_CONFIG
    if not cfg.user:
        print("[ERROR] EMAIL_USER not set.")
        return
    if not cfg.password:
        print("[ERROR] EMAIL_PASS not set (no email will be sent).")
        return

    recipients = cfg.recipients()
    if not recipients:
        print("[ERROR] No recipients resolved (check EMAIL_TO / EMAIL_FROM).")
        return

    full_subject = f"{cfg.subject_prefix} {args.subject}".strip()

    if args.dry_run:
        print("---- DRY RUN (no email sent) ----")
        print("From:     ", cfg.from_addr)
        print("To:       ", ", ".join(recipients))
        print("Subject:  ", full_subject)
        print("Body:\n", args.body)
        print("---- END DRY RUN ----")
        return

    import asyncio

    asyncio.run(send_email(args.subject, args.body))


if __name__ == "__main__":
    main()
