#!/usr/bin/env python3
"""
WhatsApp notification bot for NHS/DWP job search.

Lightweight daemon that:
  1. Reindexes all sources on schedule (default: 08:00 and 16:00)
  2. Sends a morning digest at 09:00 (always, even if no new jobs)
  3. Sends an afternoon alert at 16:05 (only if new jobs since morning)
  4. Uses Twilio WhatsApp API for outbound messages — no Flask/ngrok needed

Run as:
    python -m nhsjobsearch.whatsappbot

Or install as a system service.

Config in ~/.config/nhs-job-search/config.ini:

    [WHATSAPP]
    twilio_account_sid = ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    twilio_auth_token  = xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    twilio_from        = whatsapp:+14155238886
    notify_to          = whatsapp:+447xxxxxxxxx
    reindex_times      = 08:00, 16:00
    notify_morning     = 09:00
    notify_afternoon_delay_minutes = 5
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
from .cronreindex import write_notifications

logger = logging.getLogger('nhsjobsearch.whatsapp')

CONNECTOR_MAP = {
    'nhs': NHSJobsConnector,
    'dwp': DWPJobsConnector,
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

def format_morning_digest(new_jobs, total_in_db):
    """Format the 9am morning digest message."""
    now = datetime.now()
    date_str = now.strftime('%A %d %B %Y')

    if not new_jobs:
        return (
            f"🏥 *NHS Job Search — Morning Update*\n"
            f"📅 {date_str}\n\n"
            f"No new roles matching your search since yesterday.\n\n"
            f"📊 {total_in_db} jobs in your index.\n"
            f"Your search terms and settings are unchanged."
        )

    # Group by source
    nhs_jobs = [j for j in new_jobs if j.source == 'nhs']
    dwp_jobs = [j for j in new_jobs if j.source == 'dwp']

    msg = (
        f"🏥 *NHS Job Search — Morning Update*\n"
        f"📅 {date_str}\n\n"
        f"✨ *{len(new_jobs)} new role{'s' if len(new_jobs) != 1 else ''}* since yesterday:\n\n"
    )

    for i, job in enumerate(new_jobs[:15], 1):
        salary_part = f" | {job.salary}" if job.salary else ""
        msg += f"{i}. *{job.title}*\n"
        msg += f"   {job.employer}{salary_part}\n"
        if job.url:
            msg += f"   {job.url}\n"
        msg += "\n"

    if len(new_jobs) > 15:
        msg += f"... and {len(new_jobs) - 15} more.\n\n"

    msg += f"📊 {total_in_db} total jobs in your index."
    return msg


def format_afternoon_alert(new_jobs):
    """Format the mid-day alert (only sent if there are new jobs)."""
    msg = (
        f"🔔 *New roles just posted*\n"
        f"📅 {datetime.now().strftime('%H:%M %d %b')}\n\n"
        f"{len(new_jobs)} new role{'s' if len(new_jobs) != 1 else ''} "
        f"since this morning:\n\n"
    )

    for i, job in enumerate(new_jobs[:10], 1):
        salary_part = f" | {job.salary}" if job.salary else ""
        msg += f"{i}. *{job.title}*\n"
        msg += f"   {job.employer}{salary_part}\n"
        if job.url:
            msg += f"   {job.url}\n"
        msg += "\n"

    if len(new_jobs) > 10:
        msg += f"... and {len(new_jobs) - 10} more.\n"

    return msg


# ─── Scheduler actions ───

def action_reindex(db_path, bot_state):
    """Scheduled reindex action."""
    logger.info("Starting scheduled reindex...")
    new_jobs, total = run_reindex(db_path)
    bot_state.set('last_reindex', datetime.now().isoformat())
    logger.info(f"Reindex complete: {len(new_jobs)} new, {total} total.")
    return new_jobs


def action_morning_notify(db_path, bot_state):
    """9am morning digest — always sends, even if no new jobs."""
    logger.info("Preparing morning digest...")

    # Get all jobs currently in DB
    all_jobs = database.get_all_jobs(db_path)
    total_count = len(all_jobs)

    # Find jobs that are new since last morning notify
    last_morning = bot_state.get('last_morning_notify')
    morning_urls = set(bot_state.get('morning_job_urls', []))

    if morning_urls:
        # New = jobs whose URLs weren't in the DB at last morning notify
        current_urls = {j.url for j in all_jobs}
        new_urls = current_urls - morning_urls
        new_jobs = [j for j in all_jobs if j.url in new_urls]
    else:
        # First run — treat recent jobs (last 24h) as "new"
        new_jobs = _jobs_posted_since(all_jobs, hours=24)

    # Send the digest
    msg = format_morning_digest(new_jobs, total_count)
    result = send_whatsapp(msg)

    if result:
        # Record what we've notified about
        bot_state.set('last_morning_notify', datetime.now().isoformat())
        bot_state.set('morning_job_urls', [j.url for j in all_jobs])
        logger.info(f"Morning digest sent: {len(new_jobs)} new jobs.")
    else:
        logger.error("Failed to send morning digest.")


def action_afternoon_notify(db_path, bot_state):
    """Afternoon alert — only sends if there are new jobs since morning."""
    logger.info("Checking for afternoon alert...")

    all_jobs = database.get_all_jobs(db_path)
    morning_urls = set(bot_state.get('morning_job_urls', []))

    if not morning_urls:
        logger.info("No morning baseline — skipping afternoon alert.")
        return

    current_urls = {j.url for j in all_jobs}
    new_urls = current_urls - morning_urls
    new_jobs = [j for j in all_jobs if j.url in new_urls]

    if not new_jobs:
        logger.info("No new jobs since morning — skipping afternoon alert.")
        return

    msg = format_afternoon_alert(new_jobs)
    result = send_whatsapp(msg)

    if result:
        bot_state.set('last_afternoon_notify', datetime.now().isoformat())
        # Update baseline so next afternoon doesn't re-notify
        bot_state.set('morning_job_urls', [j.url for j in all_jobs])
        logger.info(f"Afternoon alert sent: {len(new_jobs)} new jobs.")
    else:
        logger.error("Failed to send afternoon alert.")


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

def run_bot(config_path=None):
    """Main entry point for the WhatsApp notification bot."""
    import schedule

    # Init config
    if config_path is None:
        config_path = "~/.config/nhs-job-search/config.ini"
    config.init_config(config_path)

    # Ensure WHATSAPP section exists with defaults
    _ensure_whatsapp_config()

    wa_cfg = config.CONFIG['WHATSAPP']
    if not wa_cfg.getboolean('enabled', fallback=False):
        print("WhatsApp bot is disabled. Set enabled = true in [WHATSAPP] config.")
        return

    # Setup logging
    _setup_logging()

    db_path = config.db_path()
    cache_dir = os.path.expanduser(config.CONFIG['CACHE']['path'])
    bot_state = BotState(os.path.join(cache_dir, 'whatsapp_state.json'))

    logger.info("WhatsApp notification bot starting...")
    logger.info(f"  DB: {db_path}")
    logger.info(f"  To: {wa_cfg.get('notify_to', '(not set)')}")

    # Parse schedule times
    reindex_times = [t.strip() for t in wa_cfg.get('reindex_times', '08:00, 16:00').split(',')]
    morning_notify = wa_cfg.get('notify_morning', '09:00')
    afternoon_delay = int(wa_cfg.get('notify_afternoon_delay_minutes', '5'))

    # Schedule reindexes
    for reindex_time in reindex_times:
        schedule.every().day.at(reindex_time).do(
            action_reindex, db_path=db_path, bot_state=bot_state)
        logger.info(f"  Reindex scheduled at {reindex_time}")

    # Schedule morning digest
    schedule.every().day.at(morning_notify).do(
        action_morning_notify, db_path=db_path, bot_state=bot_state)
    logger.info(f"  Morning digest at {morning_notify}")

    # Schedule afternoon alerts (after each non-morning reindex)
    for reindex_time in reindex_times:
        # Parse the reindex time and add delay
        try:
            h, m = reindex_time.split(':')
            afternoon_time = datetime(2000, 1, 1, int(h), int(m)) + timedelta(minutes=afternoon_delay)
            alert_time = afternoon_time.strftime('%H:%M')

            # Only schedule afternoon alerts for reindexes after morning notify
            if reindex_time > morning_notify:
                schedule.every().day.at(alert_time).do(
                    action_afternoon_notify, db_path=db_path, bot_state=bot_state)
                logger.info(f"  Afternoon alert at {alert_time}")
        except ValueError:
            logger.warning(f"  Invalid reindex time: {reindex_time}")

    # If no index exists, do initial reindex
    if not os.path.exists(db_path):
        logger.info("No index found. Running initial reindex...")
        action_reindex(db_path, bot_state)

    # Run the scheduler loop
    logger.info("Bot running. Press Ctrl+C to stop.")
    print(f"WhatsApp bot running. Notifications → {wa_cfg.get('notify_to', '(not set)')}")
    print(f"  Reindex: {', '.join(reindex_times)}")
    print(f"  Morning digest: {morning_notify}")
    print(f"  Press Ctrl+C to stop.\n")

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)  # Check every 30 seconds
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
        'reindex_times': '08:00, 16:00',
        'notify_morning': '09:00',
        'notify_afternoon_delay_minutes': '5',
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