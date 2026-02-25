# NHS Job Search Tool

A terminal-based job search aggregator that indexes listings from NHS Jobs, DWP Find a Job, and Indeed UK into a local SQLite database. Browse results in an interactive TUI, automate reindexing with cron, get WhatsApp notifications for new postings, and generate tailored application prompts.

## Quick Start

```bash
# Install dependencies
pip install requests beautifulsoup4 schedule

# Optional (better fuzzy search)
pip install rapidfuzz

# Run — first launch creates config and indexes all sources
nhsjobsearch
```

On first run the tool creates `~/.config/nhs-job-search/config.ini` with sensible defaults and indexes all configured sources. The interactive TUI opens automatically.

## Features at a Glance

| Feature | Description |
|---|---|
| Multi-source indexing | NHS Jobs, DWP Find a Job, Indeed UK |
| Interactive TUI | Curses-based browser with search, filtering, detail view |
| Multi-keyword search | Comma-separated keywords per backend, deduplicated |
| Cron automation | Scheduled reindexing with desktop notifications |
| WhatsApp bot | Twilio-powered notifications at configurable intervals |
| Prompt generator | STAR-E framework prompts for job applications |
| CV checklist | Extracts person spec criteria and matches against NHS terms |
| Cross-platform | macOS, Linux, WSL (with browser-open fallback) |

## Interactive TUI

Launch with `nhsjobsearch` (no flags). The TUI displays all indexed jobs in a scrollable table.

### Keybindings

| Key | Action |
|---|---|
| `↑` `↓` | Navigate rows |
| `PgUp` `PgDn` | Scroll by page |
| `/` | Regex search (filters list, highlights matches in yellow) |
| `f` | Fuzzy search (tolerates typos, ranks by similarity) |
| `Enter` or `w` | Open job URL in browser |
| `i` | Show full job details in a popup |
| `p` | Launch prompt generator for the selected job |
| `?` | Show help overlay |
| `Esc` | Clear search / return to full list |
| `q` | Quit |

Search highlighting persists after pressing Enter — matching terms stay yellow/bold while navigating.

**WSL users:** The browser-open command falls back to `wslview` or `cmd.exe /c start` when `webbrowser.open` is unavailable.

## CLI Commands

### Indexing

```bash
nhsjobsearch --reindex           # Re-index all sources (drops old DB)
nhsjobsearch --reindex-nhs       # Re-index NHS Jobs only
nhsjobsearch --reindex-dwp       # Re-index DWP Find a Job only
nhsjobsearch --reindex-indeed    # Re-index Indeed UK only
nhsjobsearch --stats             # Show index statistics
nhsjobsearch --purge             # Remove expired listings
```

### Quick Search (no TUI)

```bash
nhsjobsearch -s "occupational therapist"          # Search by keyword
nhsjobsearch -s "nurse" -l "London" -n 20         # Filter by location, 20 results
```

### Cron Automation

```bash
nhsjobsearch --cron-install                # Install cron job (every 6h)
nhsjobsearch --cron-install --cron-interval 4   # Every 4 hours
nhsjobsearch --cron-uninstall              # Remove cron job
nhsjobsearch --pending                     # Show pending new-job notifications
```

When running via cron, the tool auto-detects total page count (`max_pages=0`) and fetches all available pages. Desktop notifications are sent for new postings (via `notify-send` on Linux or `osascript` on macOS).

### Application Support Tools

```bash
nhsjobsearch --prompt            # Launch prompt generator standalone
```

Or press `p` on any job in the TUI to launch the prompt generator with that job's description pre-loaded.

**Prompt Generator** — builds a structured LLM prompt using the STAR-E framework (Situation, Task, Action, Result, Evaluate). Paste the generated prompt into your LLM of choice alongside your CV. The prompt instructs the LLM to cross-reference the job description against your experience, align responses with NHS values, use band-appropriate tone, and avoid fabrication.

**CV Checklist** — parses the person specification from a job description and extracts Essential/Desirable criteria. Matches against ~120 NHS domain terms (registrations, qualifications, competencies, frameworks) to flag what your CV should mention.

## WhatsApp Notification Bot

Sends job alerts to your phone via Twilio's WhatsApp API. No Flask or ngrok needed — outbound only.

### Setup

1. Create a free [Twilio account](https://www.twilio.com/try-twilio)
2. Activate the [WhatsApp Sandbox](https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn)
3. Add credentials to your config:

```ini
[WHATSAPP]
twilio_account_sid = ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
twilio_auth_token  = xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
twilio_from        = whatsapp:+14155238886
notify_to          = whatsapp:+447xxxxxxxxx
interval_hours     = 6
morning_time       = 08:00
notify_delay_minutes = 5
enabled            = true
```

### Running

```bash
nhsjobsearch --bot               # Start the notification daemon
nhsjobsearch --bot-test          # Send a test message
nhsjobsearch --bot-digest        # Force-send a morning digest now
```

### Schedule

The bot reindexes at regular intervals and sends notifications based on what it finds. With the default config (`interval_hours = 6`, `morning_time = 08:00`):

| Time | Action |
|---|---|
| 08:00 | Reindex all sources |
| 08:05 | **Morning digest** — always sent, even if no new jobs |
| 14:00 | Reindex all sources |
| 14:05 | Interval alert — only sent if new jobs since last notify |
| 20:00 | Reindex all sources |
| 20:05 | Interval alert — only sent if new jobs since last notify |
| 02:00 | Reindex all sources |
| 02:05 | Interval alert — only sent if new jobs since last notify |

The morning digest is mandatory (reports "no new roles" if empty). All other slots only send a message when genuinely new postings appear.

### Message Format

Each job entry includes the title, employer, salary, and a direct link:

```
🏥 *NHS Job Search — Morning Update*
📅 Wednesday 26 February 2026

✨ *3 new roles* since yesterday:

1. *Band 6 Occupational Therapist*
   Royal Free London NHS Trust | £37,338 - £44,962
   https://www.jobs.nhs.uk/candidate/jobadvert/A1234

2. *Assistant Psychologist*
   Llamau Limited | £28,000
   https://uk.indeed.com/viewjob?jk=7ac65534a3596357

📊 142 total jobs in your index.
```

If the job list exceeds WhatsApp's 1600-character limit, the bot automatically splits across multiple numbered messages (`[1/3]`, `[2/3]`, `[3/3]`).

## Configuration Reference

All configuration lives in `~/.config/nhs-job-search/config.ini`. The file is created with defaults on first run.

### `[SEARCH]` — NHS Jobs

```ini
[SEARCH]
keyword = assistant psychologist, occupational therapist
location = London
distance = 50
staff_group =
contract_type =
working_pattern =
pay_min =
pay_max =
pages_to_fetch = 5
sort_by = Date Posted (newest)
```

### `[SEARCH_DWP]` — DWP Find a Job

```ini
[SEARCH_DWP]
keyword = assistant psychologist, activities coordinator
location = London
category = 12
loc_code = 86383
contract_type =
hours =
posting_days =
remote =
pages_to_fetch = 5
sort_by = Most recent
```

`category = 12` is Healthcare & Nursing. `loc_code = 86383` is UK-wide.

### `[SEARCH_INDEED]` — Indeed UK

```ini
[SEARCH_INDEED]
keyword = assistant psychologist, activities coordinator
location = London
radius = 25
job_type = fulltime
max_days_old = 7
sort_by = date
pages_to_fetch = 5
```

| Parameter | Values |
|---|---|
| `job_type` | `fulltime`, `parttime`, `contract`, `temporary`, or blank for all |
| `max_days_old` | `1`, `3`, `7`, `14` — only show jobs posted within N days |
| `sort_by` | `date` (newest first) or `relevance` |
| `radius` | Distance from location in miles |

### `[WHATSAPP]` — Notification Bot

```ini
[WHATSAPP]
twilio_account_sid = ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
twilio_auth_token  = xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
twilio_from        = whatsapp:+14155238886
notify_to          = whatsapp:+447xxxxxxxxx
interval_hours     = 6
morning_time       = 08:00
notify_delay_minutes = 5
enabled            = true
```

### `[CACHE]` and `[DISPLAY]`

```ini
[CACHE]
path = ~/.cache/nhs-job-search/

[DISPLAY]
max_results_per_page = 50
```

### Source Sections

Each source backend has a `[SOURCE:Name]` section auto-generated on first run:

```ini
[SOURCE:NHSJobs]
type = nhs
url = https://www.jobs.nhs.uk/candidate/search/results
name = NHS Jobs

[SOURCE:DWPFindAJob]
type = dwp
url = https://findajob.dwp.gov.uk/search
name = Find a Job

[SOURCE:IndeedUK]
type = indeed
url = https://uk.indeed.com/jobs
name = Indeed UK
```

## Multi-Keyword Search

All three backends support comma-separated keywords in their config. Each keyword runs as a separate search and results are deduplicated by URL:

```ini
[SEARCH]
keyword = assistant psychologist, occupational therapist, band 5 nurse

[SEARCH_DWP]
keyword = psychologist, activities coordinator

[SEARCH_INDEED]
keyword = assistant psychologist, activities coordinator
```

This means a single `--reindex` pass searches for all keywords across all backends and merges everything into one index.

## Indeed UK — Bot Detection Notes

Indeed is aggressive about blocking automated requests. The connector handles this with:

1. **Cookie priming** — visits the Indeed homepage first to pick up session cookies before searching
2. **Full browser fingerprint** — sends the complete set of headers a real Chrome browser would (Sec-CH-UA, Sec-Fetch-*, DNT, etc.)
3. **Three-tier fallback** — tries the desktop endpoint, then the mobile endpoint (`/m/jobs`), then a fresh session with a mobile user-agent

If all three fail with 403, Indeed is likely serving a JS challenge or CAPTCHA. In that case you may need to install `cloudscraper` (`pip install cloudscraper`) and update the connector, or access Indeed manually.

## Project Structure

```
nhs-index-tool/
├── src/nhsjobsearch/
│   ├── main.py              # CLI entry point, option parsing, reindex orchestration
│   ├── config.py            # Config loading, defaults, source registry
│   ├── database.py          # SQLite storage, search, deduplication
│   ├── jobitem.py           # JobItem dataclass (title, employer, salary, url, etc.)
│   ├── display.py           # Curses TUI with search, highlighting, popups
│   ├── nhsconnector.py      # NHS Jobs scraper (www.jobs.nhs.uk)
│   ├── dwpconnector.py      # DWP Find a Job scraper (findajob.dwp.gov.uk)
│   ├── indeedconnector.py   # Indeed UK scraper (uk.indeed.com) — JSON + HTML parsing
│   ├── cronreindex.py       # Cron automation, desktop notifications
│   ├── whatsappbot.py       # Twilio WhatsApp bot daemon
│   ├── promptgen.py         # STAR-E application prompt generator
│   └── cvextract.py         # Person spec parser, CV keyword checklist
├── tests/
│   ├── testparsing.py       # NHS/DWP HTML parsing tests
│   ├── testcron.py          # Cron scheduling tests
│   ├── testpromptgen.py     # Prompt generator tests
│   ├── testcvextract.py     # CV checklist extraction tests
│   ├── testindeed.py        # Indeed connector tests (JSON + HTML + config)
│   └── testwhatsappbot.py   # WhatsApp bot message formatting + state tests
└── README.md
```

## Data Flow

```
  NHS Jobs ──────┐
                 │
  DWP Find a Job ┼──→ Connectors ──→ JobItems ──→ SQLite DB ──→ TUI / CLI
                 │         │                           │
  Indeed UK ─────┘         │                           ├──→ Cron + Desktop Notify
                           │                           └──→ WhatsApp Bot
                           │
                           └──→ Job Detail Fetch ──→ Prompt Generator
                                                  └──→ CV Checklist
```

## Dependencies

**Required:**

- Python 3.8+
- `requests` — HTTP client for all connectors
- `beautifulsoup4` — HTML parsing
- `schedule` — WhatsApp bot scheduler (only needed for `--bot`)

**Optional:**

- `rapidfuzz` — faster, better fuzzy search in the TUI (falls back to `difflib`)
- `cloudscraper` — may help if Indeed's bot detection blocks all fallback attempts

## Files and Paths

| Path | Purpose |
|---|---|
| `~/.config/nhs-job-search/config.ini` | Configuration file |
| `~/.cache/nhs-job-search/jobs.db` | SQLite job index |
| `~/.cache/nhs-job-search/whatsapp_state.json` | Bot state (last notify time, URL baselines) |
| `~/.cache/nhs-job-search/whatsapp_bot.log` | Bot log file |
| `~/.cache/nhs-job-search/new_jobs.json` | Pending notifications from cron |

## Running Tests

```bash
python -m tests.testparsing        # NHS/DWP parsing (6 tests)
python -m tests.testcron           # Cron scheduling (3 tests)
python -m tests.testpromptgen      # Prompt generator (6 tests)
python -m tests.testcvextract      # CV checklist (6 tests)
python -m tests.testindeed         # Indeed connector (8 tests)
python -m tests.testwhatsappbot    # WhatsApp bot (9 tests)
```

All tests run offline using sample HTML/JSON fixtures — no network access required.