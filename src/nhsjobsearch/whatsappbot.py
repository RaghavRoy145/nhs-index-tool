#!/usr/bin/env python3
"""
WhatsApp notification bot for NHS/DWP/Indeed job search.

Lightweight daemon that:
  1. Reindexes all sources at regular intervals (default: every 6 hours)
  2. Sends a morning digest at the first slot (always, even if no new jobs)
  3. Sends interval alerts at subsequent slots (only if new jobs found)
  4. Splits long messages across multiple WhatsApp messages
  5. Uses Twilio WhatsApp API for outbound messages — no Flask/ngrok needed

Default schedule (interval_hours=6, morning_time=08:00):
  08:00 → reindex → 08:05  morning digest (always sent)
  14:00 → reindex → 14:05  interval alert (only if new jobs)
  20:00 → reindex → 20:05  interval alert (only if new jobs)
  02:00 → reindex → 02:05  interval alert (only if new jobs)

Config in ~/.config/nhs-job-search/config.ini:

    [WHATSAPP]
    twilio_account_sid = ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    twilio_auth_token  = xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    twilio_from        = whatsapp:+14155238886
    notify_to          = whatsapp:+447xxxxxxxxx
    interval_hours     = 6
    morning_time       = 08:00
    notify_delay_minutes = 5
    enabled            = true
"""

import logging
import os
import sys
import json
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path

# Ensure the package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from . import config, database
from .nhsconnector import NHSJobsConnector
from .dwpconnector import DWPJobsConnector
from .indeedconnector import IndeedConnector
from .cronreindex import write_notifications

logger = logging.getLogger('nhsjobsearch.whatsapp')

CONNECTOR_MAP = {
    'nhs': NHSJobsConnector,
    'dwp': DWPJobsConnector,
    'indeed': IndeedConnector,
}

# ─── Twilio sender (uses requests directly — no SDK dependency) ───

def send_whatsapp(body, to=None):
    """Send a WhatsApp message via Twilio REST API.
    Uses requests directly to avoid requiring the twilio SDK."""
    import requests

    wa_cfg = config.CONFIG['WHATSAPP']
    account_sid = wa_cfg.get('twilio_account_sid', '')
    auth_token = wa_cfg.get('twilio_auth_token', '')
    from_number = wa_cfg.get('twilio_from', '')
    to_number = to or wa_cfg.get('notify_to', '')

    if not all([account_sid, auth_token, from_number, to_number]):
        logger.error("Twilio credentials not configured. Check [WHATSAPP] in config.")
        return None

    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"

    data = {
        'To': to_number,
        'From': from_number,
        'Body': body,
    }

    try:
        resp = requests.post(url, data=data, auth=(account_sid, auth_token), timeout=30)
        result = resp.json()

        if resp.status_code in (200, 201):
            logger.info(f"WhatsApp sent: SID={result.get('sid')}, status={result.get('status')}")
            return result
        else:
            logger.error(f"Twilio error {resp.status_code}: {result.get('message', result)}")
            return None
    except Exception as e:
        logger.error(f"Failed to send WhatsApp: {e}")
        return None


def send_whatsapp_multi(messages, to=None):
    """Send a list of WhatsApp messages in sequence.
    Returns True if all messages sent successfully."""
    import time as _time
    success = True
    for i, msg in enumerate(messages):
        result = send_whatsapp(msg, to=to)
        if not result:
            success = False
        # Brief pause between messages to maintain ordering
        if i < len(messages) - 1:
            _time.sleep(1)
    return success


# ─── State tracking ───

class BotState:
    """Track reindex timestamps and new jobs for notification logic."""

    def __init__(self, state_file):
        self.state_file = Path(state_file)
        self.state = self._load()

    def _load(self):
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text())
            except (json.JSONDecodeError, IOError):
                pass
        return {
            'last_morning_notify': None,
            'last_afternoon_notify': None,
            'last_reindex': None,
            'morning_job_urls': [],  # URLs seen at morning notify time
        }

    def save(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self.state, indent=2))

    def set(self, key, value):
        self.state[key] = value
        self.save()

    def get(self, key, default=None):
        return self.state.get(key, default)


# ─── Reindex logic ───

def run_reindex(db_path):
    """Reindex all configured sources. Returns (new_jobs, total_indexed)."""
    all_new = []
    total = 0

    source_sections = [s for s in config.CONFIG.sections() if s.startswith('SOURCE')]

    for section in source_sections:
        source_type = config.CONFIG.get(section, 'type', fallback='').lower()
        connector_cls = CONNECTOR_MAP.get(source_type)
        if not connector_cls:
            continue

        connector_name = config.CONFIG.get(section, 'name', fallback=source_type.upper())
        connector = connector_cls(name=connector_name)

        try:
            items = connector.get_all_items_multi(max_pages=0)
            new_jobs, _, indexed = database.index_jobs_with_diff(items, db_path)
            all_new.extend(new_jobs)
            total += indexed
            logger.info(f"  {connector_name}: {indexed} indexed, {len(new_jobs)} new")
        except Exception as e:
            logger.error(f"  {connector_name} failed: {e}", exc_info=True)

    return all_new, total


# ─── Message formatting ───

# Twilio WhatsApp sandbox limit
WHATSAPP_CHAR_LIMIT = 1500  # leave 100 chars headroom for encoding


def _split_messages(header, job_entries, footer=''):
    """Split job entries across multiple messages, each under the char limit.

    Returns a list of message strings. The header is on the first message,
    the footer on the last.
    """
    messages = []
    current_lines = []
    # Reserve space for header on first message, footer on last
    current_len = len(header)

    for entry in job_entries:
        # Would adding this entry exceed the limit?
        # Account for footer on every message in case it's the last
        if current_len + len(entry) + len(footer) > WHATSAPP_CHAR_LIMIT and current_lines:
            # Flush current message
            prefix = header if not messages else ''
            messages.append(prefix + ''.join(current_lines))
            current_lines = []
            current_len = 0

        current_lines.append(entry)
        current_len += len(entry)

    # Flush remaining
    if current_lines or not messages:
        prefix = header if not messages else ''
        messages.append(prefix + ''.join(current_lines) + footer)
    elif messages:
        # Append footer to last message
        messages[-1] += footer

    # Add part numbering if multiple messages
    if len(messages) > 1:
        for i in range(len(messages)):
            messages[i] = f"[{i+1}/{len(messages)}]\n" + messages[i]

    return messages


def _format_job_entry(i, job):
    """Format a single job entry with title, employer, salary, and URL."""
    title = job.title[:60] + '…' if len(job.title) > 60 else job.title
    employer = job.employer[:40] + '…' if len(job.employer) > 40 else job.employer
    salary_part = f" | {job.salary}" if job.salary else ""

    entry = f"{i}. *{title}*\n   {employer}{salary_part}\n"
    if job.url:
        entry += f"   {job.url}\n"
    entry += "\n"
    return entry


def format_morning_digest(new_jobs, total_in_db):
    """Format the 9am morning digest. Returns list of message strings."""
    now = datetime.now()
    date_str = now.strftime('%A %d %B %Y')

    if not new_jobs:
        return [(
            f"🏥 *NHS Job Search — Morning Update*\n"
            f"📅 {date_str}\n\n"
            f"No new roles matching your search since yesterday.\n\n"
            f"📊 {total_in_db} jobs in your index."
        )]

    header = (
        f"🏥 *NHS Job Search — Morning Update*\n"
        f"📅 {date_str}\n\n"
        f"✨ *{len(new_jobs)} new role{'s' if len(new_jobs) != 1 else ''}* "
        f"since yesterday:\n\n"
    )

    footer = f"\n📊 {total_in_db} total jobs in your index."

    entries = [_format_job_entry(i, job) for i, job in enumerate(new_jobs, 1)]
    return _split_messages(header, entries, footer)


def format_interval_alert(new_jobs):
    """Format an interval alert (only sent if new jobs exist).
    Returns list of message strings."""
    header = (
        f"🔔 *New roles just posted*\n"
        f"📅 {datetime.now().strftime('%H:%M %d %b')}\n\n"
        f"{len(new_jobs)} new role{'s' if len(new_jobs) != 1 else ''} "
        f"since last check:\n\n"
    )

    entries = [_format_job_entry(i, job) for i, job in enumerate(new_jobs, 1)]
    return _split_messages(header, entries)


# ─── Scheduler actions ───

def action_reindex(db_path, bot_state):
    """Scheduled reindex action."""
    logger.info("Starting scheduled reindex...")
    new_jobs, total = run_reindex(db_path)
    bot_state.set('last_reindex', datetime.now().isoformat())
    bot_state.set('last_reindex_new_count', len(new_jobs))
    logger.info(f"Reindex complete: {len(new_jobs)} new, {total} total.")
    return new_jobs


def action_morning_notify(db_path, bot_state):
    """Morning digest — always sends, even if no new jobs."""
    logger.info("Preparing morning digest...")

    all_jobs = database.get_all_jobs(db_path)
    total_count = len(all_jobs)

    # Find jobs new since last morning notify
    morning_urls = set(bot_state.get('morning_job_urls', []))

    if morning_urls:
        current_urls = {j.url for j in all_jobs}
        new_urls = current_urls - morning_urls
        new_jobs = [j for j in all_jobs if j.url in new_urls]
    else:
        # First run — treat recent jobs (last 24h) as "new"
        new_jobs = _jobs_posted_since(all_jobs, hours=24)

    messages = format_morning_digest(new_jobs, total_count)
    success = send_whatsapp_multi(messages)

    if success:
        bot_state.set('last_morning_notify', datetime.now().isoformat())
        bot_state.set('morning_job_urls', [j.url for j in all_jobs])
        # Reset baseline for interval checks
        bot_state.set('last_notify_urls', [j.url for j in all_jobs])
        logger.info(f"Morning digest sent: {len(new_jobs)} new jobs, "
                     f"{len(messages)} message(s).")
    else:
        logger.error("Failed to send morning digest.")


def action_interval_notify(db_path, bot_state):
    """Interval alert — only sends if there are new jobs since last notify."""
    logger.info("Checking for interval alert...")

    all_jobs = database.get_all_jobs(db_path)
    baseline_urls = set(bot_state.get('last_notify_urls', []))

    if not baseline_urls:
        logger.info("No baseline — skipping interval alert.")
        return

    current_urls = {j.url for j in all_jobs}
    new_urls = current_urls - baseline_urls
    new_jobs = [j for j in all_jobs if j.url in new_urls]

    if not new_jobs:
        logger.info("No new jobs since last notify — skipping interval alert.")
        return

    messages = format_interval_alert(new_jobs)
    success = send_whatsapp_multi(messages)

    if success:
        bot_state.set('last_interval_notify', datetime.now().isoformat())
        # Update baseline so next interval doesn't re-notify
        bot_state.set('last_notify_urls', [j.url for j in all_jobs])
        logger.info(f"Interval alert sent: {len(new_jobs)} new jobs, "
                     f"{len(messages)} message(s).")
    else:
        logger.error("Failed to send interval alert.")


def _jobs_posted_since(jobs, hours=24):
    """Filter jobs to those posted within the last N hours."""
    import datetime as dt
    cutoff = dt.datetime.now() - timedelta(hours=hours)
    recent = []
    for job in jobs:
        if not job.date_posted:
            continue
        try:
            # Try ISO format first, then common NHS date formats
            date_str = job.date_posted
            parsed = None
            try:
                parsed = dt.datetime.fromisoformat(date_str)
            except ValueError:
                for fmt in ('%d %B %Y', '%Y-%m-%d', '%d/%m/%Y', '%d %b %Y'):
                    try:
                        parsed = dt.datetime.strptime(date_str, fmt)
                        break
                    except ValueError:
                        continue
            if parsed and parsed >= cutoff:
                recent.append(job)
        except Exception:
            pass
    return recent


# ─── Main scheduler loop ───

def _reindex_and_maybe_notify(db_path, bot_state, is_morning=False):
    """Combined action: reindex then decide whether to notify.

    - Morning slot: always sends digest (even if 0 new jobs).
    - Other slots: only sends if reindex found new jobs.
    """
    action_reindex(db_path, bot_state)

    if is_morning:
        action_morning_notify(db_path, bot_state)
    else:
        action_interval_notify(db_path, bot_state)


def run_bot(config_path=None):
    """Main entry point for the WhatsApp notification bot.

    Schedule:
        Every interval_hours (default 6h), reindex all sources.
        The first run of the day (morning_time) always sends a digest.
        Subsequent interval runs only notify if new jobs were found.

    Config [WHATSAPP]:
        interval_hours            = 6
        morning_time              = 08:00
        notify_delay_minutes      = 5   (delay between reindex and notify)
    """
    import schedule

    if config_path is None:
        config_path = "~/.config/nhs-job-search/config.ini"
    config.init_config(config_path)

    _ensure_whatsapp_config()

    wa_cfg = config.CONFIG['WHATSAPP']
    if not wa_cfg.getboolean('enabled', fallback=False):
        print("WhatsApp bot is disabled. Set enabled = true in [WHATSAPP] config.")
        return

    _setup_logging()

    db_path = config.db_path()
    cache_dir = os.path.expanduser(config.CONFIG['CACHE']['path'])
    bot_state = BotState(os.path.join(cache_dir, 'whatsapp_state.json'))

    logger.info("WhatsApp notification bot starting...")
    logger.info(f"  DB: {db_path}")
    logger.info(f"  To: {wa_cfg.get('notify_to', '(not set)')}")

    # Parse schedule config
    interval_hours = int(wa_cfg.get('interval_hours', '6'))
    morning_time = wa_cfg.get('morning_time', '08:00')
    notify_delay = int(wa_cfg.get('notify_delay_minutes', '5'))

    # Build the schedule slots: morning + every N hours from morning
    # e.g. morning=08:00, interval=6 → 08:00, 14:00, 20:00, 02:00
    try:
        mh, mm = morning_time.split(':')
        morning_hour, morning_min = int(mh), int(mm)
    except ValueError:
        morning_hour, morning_min = 8, 0

    slots = []
    for i in range(24 // interval_hours):
        slot_hour = (morning_hour + i * interval_hours) % 24
        slot_time = f"{slot_hour:02d}:{morning_min:02d}"
        is_morning = (i == 0)
        slots.append((slot_time, is_morning))

    # Schedule reindex at each slot, with notify after a delay
    for slot_time, is_morning in slots:
        # Schedule reindex
        schedule.every().day.at(slot_time).do(
            action_reindex, db_path=db_path, bot_state=bot_state)

        # Schedule notify after delay
        try:
            notify_dt = datetime(2000, 1, 1, *map(int, slot_time.split(':'))) + \
                        timedelta(minutes=notify_delay)
            notify_time = notify_dt.strftime('%H:%M')
        except ValueError:
            notify_time = slot_time

        if is_morning:
            schedule.every().day.at(notify_time).do(
                action_morning_notify, db_path=db_path, bot_state=bot_state)
            logger.info(f"  Slot {slot_time}: reindex → "
                        f"{notify_time}: morning digest (always)")
        else:
            schedule.every().day.at(notify_time).do(
                action_interval_notify, db_path=db_path, bot_state=bot_state)
            logger.info(f"  Slot {slot_time}: reindex → "
                        f"{notify_time}: interval alert (if new jobs)")

    # If no index exists, do initial reindex
    if not os.path.exists(db_path):
        logger.info("No index found. Running initial reindex...")
        action_reindex(db_path, bot_state)

    # Run the scheduler loop
    slot_summary = ', '.join(t for t, _ in slots)
    logger.info("Bot running. Press Ctrl+C to stop.")
    print(f"WhatsApp bot running. Notifications → "
          f"{wa_cfg.get('notify_to', '(not set)')}")
    print(f"  Schedule: every {interval_hours}h at {slot_summary}")
    print(f"  Morning digest (always): {morning_time}")
    print(f"  Notify delay: {notify_delay} min after reindex")
    print(f"  Press Ctrl+C to stop.\n")

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
        print("\nBot stopped.")


def run_bot_background(config_path=None):
    """Run the bot in a background thread (e.g. alongside the TUI)."""
    t = threading.Thread(target=run_bot, args=(config_path,), daemon=True)
    t.start()
    return t


# ─── CLI commands ───

def send_test_message(config_path=None):
    """Send a test WhatsApp message to verify Twilio setup."""
    if config_path is None:
        config_path = "~/.config/nhs-job-search/config.ini"
    config.init_config(config_path)
    _ensure_whatsapp_config()

    msg = (
        f"🧪 *NHS Job Search — Test Message*\n\n"
        f"Your WhatsApp notifications are working!\n"
        f"Sent at {datetime.now().strftime('%H:%M on %d %B %Y')}"
    )

    result = send_whatsapp(msg)
    if result:
        print(f"✓ Test message sent! SID: {result.get('sid')}")
    else:
        print("✗ Failed to send test message. Check your Twilio credentials.")


def send_digest_now(config_path=None):
    """Force-send a morning digest right now (for testing)."""
    if config_path is None:
        config_path = "~/.config/nhs-job-search/config.ini"
    config.init_config(config_path)
    _ensure_whatsapp_config()

    db_path = config.db_path()
    cache_dir = os.path.expanduser(config.CONFIG['CACHE']['path'])
    bot_state = BotState(os.path.join(cache_dir, 'whatsapp_state.json'))

    if not os.path.exists(db_path):
        print("No index found. Run --reindex first.")
        return

    _setup_logging()
    action_morning_notify(db_path, bot_state)


# ─── Config helpers ───

def _ensure_whatsapp_config():
    """Ensure [WHATSAPP] section exists with defaults."""
    defaults = {
        'twilio_account_sid': '',
        'twilio_auth_token': '',
        'twilio_from': 'whatsapp:+14155238886',
        'notify_to': '',
        'interval_hours': '6',
        'morning_time': '08:00',
        'notify_delay_minutes': '5',
        'enabled': 'false',
    }
    for key, value in defaults.items():
        config.check_value('WHATSAPP', key, value)


def _setup_logging():
    """Configure logging for the bot."""
    if logger.handlers:
        return  # Already configured

    logger.setLevel(logging.INFO)

    # Console handler
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S'))
    logger.addHandler(ch)

    # File handler
    try:
        cache_dir = os.path.expanduser(config.CONFIG['CACHE']['path'])
        os.makedirs(cache_dir, exist_ok=True)
        fh = logging.FileHandler(os.path.join(cache_dir, 'whatsapp_bot.log'))
        fh.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
        logger.addHandler(fh)
    except Exception:
        pass


# ─── Entry point ───

def main():
    import argparse

    parser = argparse.ArgumentParser(description='NHS Job Search WhatsApp Bot')
    parser.add_argument('--config', default='~/.config/nhs-job-search/config.ini',
                        help='Path to config file')
    parser.add_argument('--test', action='store_true',
                        help='Send a test WhatsApp message')
    parser.add_argument('--digest-now', '--digest', action='store_true',
                        help='Force send morning digest now')
    parser.add_argument('--reindex-and-notify', action='store_true',
                        help='Reindex then send digest (useful for testing)')
    args = parser.parse_args()

    if args.test:
        send_test_message(args.config)
    elif args.digest_now:
        send_digest_now(args.config)
    elif args.reindex_and_notify:
        config.init_config(args.config)
        _ensure_whatsapp_config()
        _setup_logging()
        db_path = config.db_path()
        cache_dir = os.path.expanduser(config.CONFIG['CACHE']['path'])
        bot_state = BotState(os.path.join(cache_dir, 'whatsapp_state.json'))
        action_reindex(db_path, bot_state)
        action_morning_notify(db_path, bot_state)
    else:
        run_bot(args.config)


if __name__ == '__main__':
    main()