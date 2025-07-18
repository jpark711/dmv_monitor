# NJ MVC Appointment Monitor

A lightweight Python + Streamlit application that **scrapes New Jersey MVC “License / Non‑Driver ID Renewal” appointment availability**, displays results in an interactive dashboard, and **emails you only when *new earlier* slots appear** at selected DMV locations.

---

## ✨ Features

| Category | Capability |
|----------|------------|
| Scraping | Headless Playwright browser fetches current appointment cards. |
| Dashboard | Streamlit UI with auto‑refresh and location filtering. |
| Highlighting | Rows earlier than your selected cutoff date are visually emphasized. |
| Smart Email Alerts | Sends **one consolidated message** only when a *strictly earlier* slot appears (per location). |
| Duplicate Suppression | Maintains a JSON state file so you don’t get spammed. |
| Secure Config | SMTP password is **never** stored in YAML or committed to version control. |
| Simple Deploy | Single `requirements.txt`—no complex packaging or frameworks. |

---

## 🗂 Project Layout

```

dmv\_monitor/
├─ .env.example
├─ requirements.txt
├─ config/
│  └─ settings.yaml
├─ state/
│  └─ (notification\_state.json created at runtime)
└─ src/
├─ app.py
├─ config.py
├─ fetch\_appointments.py
└─ send\_email.py

````

---

## 🚀 Quick Start

```bash
git clone <your-repo-url>
cd dmv_monitor

python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate

pip install -r requirements.txt
playwright install          # downloads Chromium

cp .env.example .env        # edit .env and insert your EMAIL_PASS
streamlit run src/app.py
````

Open the dashboard at: **[http://localhost:8501](http://localhost:8501)**

---

## ⚙️ Configuration

Configuration is merged from (highest first):

1. **Environment variables** (`.env` or deployment env)
2. `config/settings.yaml`
3. Internal defaults

### Core Environment Variables

| Variable               | Purpose                                             | Example              |
| ---------------------- | --------------------------------------------------- | -------------------- |
| `REFRESH_MINUTES`      | Auto‑refresh & cache interval (minutes)             | `10`                 |
| `DEFAULT_CUTOFF_DATE`  | Initial highlight threshold                         | `2025-08-15`         |
| `TARGET_DMVS`          | Comma list of DMV names to monitor for email alerts | `Bayonne,Newark,...` |
| `ENABLE_EMAIL`         | Master switch for notifications                     | `1` / `0`            |
| `HEADLESS`             | Headless browser mode                               | `1`                  |
| `SCRAPE_TIMEOUT_MS`    | Page load timeout                                   | `25000`              |
| `EMAIL_HOST`           | SMTP hostname                                       | `smtp.gmail.com`     |
| `EMAIL_PORT`           | SMTP port (465 TLS / 587 STARTTLS)                  | `465`                |
| `EMAIL_USER`           | SMTP user / login                                   | `contact@...`        |
| `EMAIL_PASS`           | **SMTP password / app password**                    | *(secret)*           |
| `EMAIL_FROM`           | From address (defaults to user)                     | `contact@...`        |
| `EMAIL_TO`             | Comma recipients (defaults to FROM)                 | `contact@...`        |
| `EMAIL_USE_TLS`        | Implicit TLS (port 465)                             | `1`                  |
| `EMAIL_USE_STARTTLS`   | STARTTLS upgrade (port 587)                         | `0`                  |
| `EMAIL_SUBJECT_PREFIX` | Prefix for all alert emails                         | `[NJ MVC]`           |

> **Password Handling:** Never put a real password in `settings.yaml`. Only set it in `.env` or an environment variable (`EMAIL_PASS`).

---

## 📬 How Email Alerts Work

1. Every refresh, all appointments are scraped & sorted.
2. A row is considered *early* if the date is **strictly before** the selected cutoff date.
3. Rows must also match one of the `TARGET_DMVS` (case-insensitive).
4. A state file `state/notification_state.json` stores the earliest date previously emailed per location.
5. If a location has a *new earlier* time than stored, it is included in the next email batch.
6. After sending, the stored earliest time for that location is updated.

**Resetting Alerts:** Delete `state/notification_state.json` to treat all currently early appointments as new.

---

## 🖥 Using the Dashboard

| UI Element                            | Function                                                 |
| ------------------------------------- | -------------------------------------------------------- |
| *Highlight Date Input*                | Adjust the early threshold interactively.                |
| *Location Multiselect*                | Focus on specific DMV branches.                          |
| *Send notifications this refresh*     | Toggle sending for a single cycle (useful when testing). |
| Green Highlight                       | Slot earlier than the cutoff date.                       |
| “Open NJ MVC Appointment Page” button | Opens the official booking portal.                       |

---

## 🔐 Security Practices

| Risk                         | Mitigation                                       |
| ---------------------------- | ------------------------------------------------ |
| Leaking credentials          | `.env` in `.gitignore`; password never in YAML.  |
| Email spam                   | Duplicate suppression by earliest-date tracking. |
| Over-scraping                | Default 10‑minute refresh; adjust responsibly.   |
| Accidental commit of secrets | Use environment variables; rotate if leaked.     |

**If you commit a secret:**

1. Revoke/regenerate it immediately.
2. Commit the fix (removal + new secret set via env).
3. Force-pushing history does not guarantee removal from remote caches.

---

## 🛠 Manual Test of Email (Optional)

```bash
python - <<'PY'
import asyncio
from send_email import send_email
asyncio.run(send_email("Test Alert", "This is a test email from the DMV monitor."))
PY
```

If it succeeds, you’ll see `[EMAIL] Sent:` in the console.

---

## 🧹 Maintenance Tips

| Task                | Action                                      |
| ------------------- | ------------------------------------------- |
| Update dependencies | `pip install -r requirements.txt --upgrade` |
| Reset notifications | Delete `state/notification_state.json`      |
| Debug scraping      | Set `HEADLESS=0` in `.env` and restart      |
| Reduce noise        | Increase `REFRESH_MINUTES` if not urgent    |

---

## ❓ Troubleshooting

| Symptom                       | Likely Cause                        | Fix                                       |
| ----------------------------- | ----------------------------------- | ----------------------------------------- |
| Empty table                   | Selector change or temporary outage | Inspect site; update selectors if needed. |
| Emails never arrive           | SMTP password wrong / blocked       | Verify app password.                      |
| “Missing credentials” message | No `EMAIL_PASS` provided            | Add to `.env` and restart.                |
| No highlighting               | Cutoff date after all slots         | Choose earlier cutoff.                    |
| Repeated alerts after reset   | State file deleted                  | Expected; suppression restarts.           |

---

## 🚧 Ethical & Legal Notice

Automated scraping must respect the site’s Terms of Service and not overload servers.
Use reasonable refresh intervals and avoid deploying multiple parallel scrapers.

---

## 🔮 Future Enhancements (Ideas)

* CSV export of filtered table
* Slack / Discord / webhook alerts
* Historical trend logging (SQLite)
* Containerization (Dockerfile)
* Unit tests & CI pipeline

(Ask if you’d like any of these added.)

---

## 📄 License

MIT (modify as desired).

---

## 🙌 Acknowledgements

Thanks to the open-source community behind Playwright, Streamlit, PyYAML, and aiosmtplib.

---

**Happy monitoring and faster scheduling! 🚗**

