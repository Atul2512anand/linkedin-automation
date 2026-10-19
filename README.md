# LinkedIn Automation (local, human-in-the-loop)

A small Python + Playwright tool for:

1. **Job tracker** - collect listings from a LinkedIn jobs search URL into a local SQLite database, update statuses, export CSV/JSON.
2. **Application workflow** - generate a per-job prep pack (cover-letter draft, posting keywords, screening answers), then open shortlisted jobs in tabs with an autofill panel for manual submission.
3. **Assisted outreach** - discover contacts from LinkedIn people search or import a CSV, preview personalized notes, open them in browser tabs for manual Connect clicks, or send at a deliberately slow rate with hard caps and an explicit `--confirm`.

Everything runs locally. Your LinkedIn password is never seen or stored; the browser session lives in a local Chrome profile directory.

---

## Read this first

- LinkedIn has **no public API for personal profiles**, so this uses browser automation with your logged-in session.
- LinkedIn's User Agreement **prohibits bots, scraping, and automated messaging**. Account restrictions are a real risk. Use this on your own account, at low volume, at your own risk.
- The defaults are intentionally conservative: **sending is disabled**, `dry_run` is on, caps are 10/day and 50/week, delays are 45-150 seconds, and the browser is visible.
- The tool **stops automatically** when it sees a login wall, checkpoint, or security verification page.
- Do not run this on a shared or work-managed machine, and do not commit `config.yaml` or the browser profile (both are gitignored).

---

## Setup

Requires Python 3.10+ and Google Chrome (or Edge).

```powershell
cd C:\Users\HP\OneDrive\Documents\research\linkedin-automation
.\run.cmd
```

The first run:

- creates `.venv`
- installs `playwright` and `pyyaml`
- copies `config.example.yaml` to `config.yaml`

Playwright uses the system Chrome through `browser.channel: chrome`, so no Chromium download is needed. If Chrome is not found, set `channel: msedge`, or install the bundled browser:

```powershell
.venv\Scripts\python -m playwright install chromium
```

## Sign in

```powershell
.\run.cmd login
```

A visible Chrome window opens at LinkedIn. Sign in manually, then press Enter in the terminal. The session is stored in:

```
%LOCALAPPDATA%\linkedin-automation\browser-profile
```

Check everything is wired up:

```powershell
.\run.cmd doctor
```

---

## Job tracker

Collect from any LinkedIn jobs search URL:

```powershell
.\run.cmd jobs collect --url "https://www.linkedin.com/jobs/search/?keywords=Data%20Scientist&location=Bengaluru"
```

Review, update, and export:

```powershell
.\run.cmd jobs list
.\run.cmd jobs list --status new --limit 50
.\run.cmd jobs status 4123456789 applied
.\run.cmd jobs export --format csv
.\run.cmd jobs export --format json --out data\exports\my_jobs.json
.\run.cmd jobs open 4123456789
```

Statuses: `new`, `shortlisted`, `applied`, `interviewing`, `offer`, `rejected`, `archived`.

Collecting twice is safe: jobs are deduplicated by LinkedIn job id. `jobs.scrolls` in `config.yaml` controls how far down the result list it scrolls.

---

## Job applications

The tool never clicks Apply or submits a form. It prepares the application, opens the tabs, and gives you copy-paste values; you stay in control of the submit button.

### 1. Fill in your profile

Edit the `profile:` block in `config.yaml`:

```yaml
profile:
  full_name: "Your Name"
  email: "you@example.com"
  phone: "+91 ..."
  location: "City, Country"
  linkedin: "https://www.linkedin.com/in/your-profile"
  github: "https://github.com/your-handle"
  portfolio: "https://..."
  headline: "Software developer (TypeScript / Python)"
  summary: "Two or three lines about what you do."
  notice_period: "30 days"
  expected_salary: "..."
  work_authorization: "..."
  relocation: "..."
```

These values feed both the autofill panel and the prep packs. Blank fields show as `not set`.

### 2. Shortlist jobs

```powershell
.\run.cmd jobs list --status new
.\run.cmd jobs status 4123456789 shortlisted
```

### 3. Generate application packs

```powershell
.\run.cmd jobs prep --status shortlisted --limit 5 --fetch
```

For one job:

```powershell
.\run.cmd jobs prep --id 4123456789 --fetch
```

`--fetch` opens each posting to pull its description and derive keywords. Without it, packs are generated from the stored title/company only.

Each pack lands in `data\exports\prep\<job_id>_<company>-<title>.md` and contains:

- job summary and link
- top keywords from the posting
- a cover-letter draft from `templates.cover_letter`
- answers to prepare (notice period, salary, authorization, relocation)
- a pre-submit checklist

### 4. Batch tabs for manual apply

```powershell
.\run.cmd jobs batch --status shortlisted --limit 10
```

- Opens up to 10 shortlisted jobs in separate Chrome tabs.
- Each page gets an **Application details** panel: name, email, phone, location, LinkedIn, GitHub, portfolio. Click **Copy**, then paste into the form.
- The same panel is injected *inside* the application dialog, so clicking Copy doesn't close the modal.
- When you finish, press Enter and say which ones you applied to: `all`, `none`, or numbers like `1 3 5`.

Applied jobs move to status `applied` and are logged as `apply` actions. Manual applications count toward `jobs.apply_daily_cap` (10/day by default) once logged. Use `--keep-open` to leave the tabs open.

---

## Outreach

### 1. Fill the queue

**Option A - discover from a LinkedIn people search**

The simplest form builds the search for you:

```powershell
.\run.cmd contacts discover --query "technical recruiter" --location japan --limit 10
```

`--location` accepts country names (japan, india, united states, united kingdom, singapore, australia, canada, germany). For anything else, pass a LinkedIn geo ID with `--geo`, or paste a full search URL with `--url` (build it in LinkedIn's UI first). Discovery keeps only profiles that show a **Connect** button, stores up to 10 unique profiles, and splits headlines like `Recruiter at Acme` into role and company. It does not click Connect. Keep discovery volume low.

**Option B - import a CSV**

`contacts.csv`:

```csv
profile_url,name,company,role,note
https://www.linkedin.com/in/example-jane-doe,Jane Doe,Acme,Data Scientist,
https://www.linkedin.com/in/example-john-smith,John Smith,Globex,ML Engineer,"Hi John, I'm applying to the ML Engineer role and would value your perspective."
```

The URLs above are placeholders. Replace them with real profile URLs before importing.

- `profile_url` is required and must contain `/in/`.
- `note` is optional. If blank, the template in `config.yaml` is used.
- Keep notes under ~200 characters; LinkedIn limits connection notes (typically 300 for free accounts).

```powershell
.\run.cmd contacts import contacts.csv
.\run.cmd contacts list
.\run.cmd outreach preview
```

### 2. Inspect profiles without clicking anything

```powershell
.\run.cmd outreach inspect --limit 3
```

This opens each profile and reports whether it sees `connect`, `pending`, `message` (already connected), or `unknown`. It does not click Connect.

Add `--apply` to reconcile statuses from what LinkedIn actually shows:

```powershell
.\run.cmd outreach inspect --limit 10 --apply
```

- `pending` -> contact marked `sent` and logged as a connect action
- `message` -> marked `connected`
- `connect` / `unknown` -> left `queued`

Use this after a manual batch if you closed the terminal before its review step.

### 3. Manual tab batch (recommended)

This is the workflow you asked for: the tool opens 10 profiles in tabs, you click Connect yourself.

```powershell
.\run.cmd outreach batch --limit 10
```

What happens:

1. Ten (or fewer) queued profiles open in separate Chrome tabs.
2. Each tab has a floating panel with the person's name and personalized note, plus a **Copy note** button.
3. In each tab: **Connect -> Add a note -> Fill note** (button inside the dialog) **-> review -> Send**. The panel remains as a copy/paste fallback.
4. When finished, press Enter in the terminal.
5. The tool checks every tab:
   - `Pending` -> contact marked `sent`
   - `Message` -> marked `connected`
   - still `Connect` -> left `queued`
6. Manual sends are written to the action log, so they count toward the daily/weekly caps.

A batch sheet is saved to `data\exports\outreach_batch_<timestamp>.md`. Use `--keep-open` to leave the tabs open after review.

If you close the console before pressing Enter, the review never runs — use `outreach inspect --apply` (section 2) to sync the statuses afterward.

This mode does **not** require `outreach.enabled` or `dry_run: false` because it never clicks Connect or Send.

### 4. Automated sending (optional, higher risk)

Edit `config.yaml`:

```yaml
outreach:
  enabled: true
  dry_run: false
```

Then send a small batch:

```powershell
.\run.cmd outreach send --limit 5 --confirm
```

Safety gates, all of which must pass:

- `outreach.enabled: true`
- `outreach.dry_run: false`
- `--confirm` on the command line
- inside `working_hours` (local time)
- under both `daily_cap` and `weekly_cap`
- LinkedIn session still valid

Between profiles it waits a random 45-150 seconds. On any security checkpoint it stops and saves a screenshot to `data\screenshots\`.

### 5. Follow-ups

Mark a contact as connected/accepted, then message:

```powershell
.\run.cmd outreach mark 1 accepted
.\run.cmd outreach message --limit 3 --confirm
```

Follow-ups use the `follow_up` template. Message sending has the same preflight gates and caps.

### 6. Track results

```powershell
.\run.cmd contacts list
.\run.cmd stats
```

Contact statuses: `queued`, `sent`, `pending`, `connected`, `accepted`, `replied`, `messaged`, `skipped`, `failed`.

If a send fails, the screenshot path and error are printed and stored in `contacts.last_error`. Fix the cause, then reset it:

```powershell
.\run.cmd outreach mark 1 queued
```

---

## Configuration highlights

`config.yaml` (created from `config.example.yaml`):

| Setting | Default | Meaning |
|---|---|---|
| `browser.channel` | `chrome` | `chrome`, `msedge`, or `""` for bundled Chromium |
| `browser.headless` | `false` | keep visible; headless increases challenge risk |
| `outreach.enabled` | `false` | master send switch |
| `outreach.dry_run` | `true` | second send switch |
| `outreach.daily_cap` | `10` | connection requests per day |
| `outreach.weekly_cap` | `50` | connection requests per week |
| `outreach.min/max_delay_seconds` | `45/150` | pause between profiles |
| `outreach.working_hours` | `[10, 19]` | local time; `[0, 24]` disables the window |
| `outreach.send_connection_note` | `true` | attach the note |
| `jobs.scrolls` | `6` | job-list scroll passes per collection |
| `jobs.apply_daily_cap` | `10` | manual applications logged per day |
| `profile.*` | `-` | autofill panel values and prep-pack personalization |

The action log in SQLite is what enforces caps, so restarting the app does not reset your daily count.

---

## Troubleshooting

**"LinkedIn served the logged-out auth wall"** - run `.\run.cmd login` again; cookies expire.

**"Connect/Message button not found"** - the profile may use Follow only, be a company page, or LinkedIn changed its DOM. Run `outreach inspect` and check the screenshot in `data\screenshots\`.

**No jobs collected** - open the search URL manually while signed in. LinkedIn sometimes redirects logged-out or rate-limited sessions. Increase `jobs.scrolls` for longer lists.

**Chrome won't launch / profile locked** - close other Chrome windows using that automation profile, or change `browser.profile_dir`. Do not point it at your everyday Chrome profile.

**Security checkpoint** - stop immediately. Do not retry in a loop. Open LinkedIn manually, complete the check, and wait at least a day before running outreach again.

---

## Project layout

```
linkedin-automation/
  run.cmd                  # setup + CLI entry point
  config.example.yaml      # safe defaults
  config.yaml              # local settings (gitignored)
  requirements.txt
  la/
    cli.py                 # command line interface
    browser.py             # Playwright session + safety checks
    jobs.py                # job collection/export
    outreach.py            # contacts, notes, send logic, caps
    db.py                  # SQLite schema and helpers
    config.py, util.py
  data/
    automation.db          # jobs, contacts, action log
    exports/
    screenshots/
```
