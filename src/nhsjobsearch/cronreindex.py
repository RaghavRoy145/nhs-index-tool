#!/usr/bin/env python3
"""
Cron-friendly reindex script.

Designed to be called by cron every few hours. It:
  1. Reindexes all configured sources
  2. Purges expired listings
  3. Detects NEW jobs (not previously in the DB)
  4. Writes new jobs to a JSON notifications file for downstream consumers
     (e.g. the WhatsApp bot can read this file to send push alerts)
  5. Logs everything to a rotating log file

Usage (direct):
    python -m nhsjobsearch.cron_reindex

Install crontab:
    python -m nhsjobsearch.cron_reindex --install [--interval 6]

Uninstall crontab:
    python -m nhsjobsearch.cron_reindex --uninstall

Show pending notifications:
    python -m nhsjobsearch.cron_reindex --pending
"""

import argparse
import json
import logging
import os
import sys
import subprocess
from datetime import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler

from . import config, database
from .nhsconnector import NHSJobsConnector
from .dwpconnector import DWPJobsConnector
from .indeedconnector import IndeedConnector

CONNECTOR_MAP = {
    'nhs': NHSJobsConnector,
    'dwp': DWPJobsConnector,
    'indeed': IndeedConnector,
}

# --- File paths derived from config cache dir ---

def _cache_dir():
    return Path(os.path.expanduser(config.CONFIG['CACHE']['path']))

def _notifications_path():
    return _cache_dir() / 'new_jobs.json'

def _log_path():
    return _cache_dir() / 'cron_reindex.log'

def _lock_path():
    return _cache_dir() / 'reindex.lock'


def setup_logging():
    """Configure logging to both file and stderr."""
    log_file = _log_path()
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger('nhsjobsearch.cron')
    logger.setLevel(logging.INFO)

    # Rotating file: 5 MB max, keep 3 backups
    fh = RotatingFileHandler(str(log_file), maxBytes=5*1024*1024, backupCount=3)
    fh.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
    logger.addHandler(fh)

    # Also log to stderr so cron can capture output
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
    logger.addHandler(sh)

    return logger


def acquire_lock(logger):
    """Simple file-based lock to prevent overlapping runs."""
    lock = _lock_path()
    if lock.exists():
        # Check if the lock is stale (older than 1 hour)
        age = datetime.now().timestamp() - lock.stat().st_mtime
        if age > 3600:
            logger.warning(f"Stale lock found ({age:.0f}s old), removing.")
            lock.unlink()
        else:
            logger.warning("Another reindex is running (lock exists). Exiting.")
            return False

    lock.write_text(str(os.getpid()))
    return True


def release_lock():
    lock = _lock_path()
    if lock.exists():
        lock.unlink()


def reindex_all_sources(db_path, logger):
    """
    Reindex every configured source. Returns list of all new JobItem objects.
    """
    all_new_jobs = []

    source_sections = [s for s in config.CONFIG.sections() if s.startswith('SOURCE')]
    if not source_sections:
        logger.warning("No sources configured.")
        return all_new_jobs

    for section in source_sections:
        source_type = config.CONFIG.get(section, 'type', fallback='').lower()
        connector_cls = CONNECTOR_MAP.get(source_type)
        if not connector_cls:
            logger.warning(f"Unknown source type '{source_type}' in {section}. Skipping.")
            continue

        connector_name = config.CONFIG.get(section, 'name', fallback=source_type.upper())
        connector = connector_cls(name=connector_name)

        logger.info(f"Fetching from {connector_name}...")
        try:
            # Cron uses all pages (0 = auto-detect) and multi-keyword
            items = connector.get_all_items_multi(max_pages=0)
            new_jobs, _, total = database.index_jobs_with_diff(items, db_path)
            logger.info(f"  {connector_name}: {total} indexed, {len(new_jobs)} new")
            all_new_jobs.extend(new_jobs)
        except Exception as e:
            logger.error(f"  {connector_name} failed: {e}", exc_info=True)

    return all_new_jobs


def write_notifications(new_jobs, logger):
    """
    Append new jobs to the notifications JSON file.

    The file holds an array of notification objects. Downstream consumers
    (e.g. the WhatsApp bot) read and truncate this file after processing.

    Each entry:
    {
        "timestamp": "2026-02-23T14:30:00",
        "title": "Staff Nurse",
        "employer": "NHS Trust",
        "location": "London",
        "salary": "£30,000",
        "url": "https://...",
        "source": "nhs"
    }
    """
    path = _notifications_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing notifications
    existing = []
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except (json.JSONDecodeError, ValueError):
            existing = []

    timestamp = datetime.now().isoformat(timespec='seconds')

    for job in new_jobs:
        existing.append({
            'timestamp': timestamp,
            'title': job.title,
            'employer': job.employer,
            'location': job.location,
            'salary': job.salary,
            'contract_type': job.contract_type,
            'working_pattern': job.working_pattern,
            'url': job.url,
            'source': job.source,
        })

    path.write_text(json.dumps(existing, indent=2))
    logger.info(f"Wrote {len(new_jobs)} new notifications ({len(existing)} total pending)")


def read_pending_notifications():
    """Read and return pending notifications without clearing them."""
    path = _notifications_path()
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, ValueError):
        return []


def consume_notifications():
    """
    Read and clear all pending notifications.
    Called by the WhatsApp bot after it has sent alerts.
    Returns the list of notification dicts.
    """
    path = _notifications_path()
    if not path.exists():
        return []

    try:
        notifications = json.loads(path.read_text())
    except (json.JSONDecodeError, ValueError):
        notifications = []

    # Clear the file
    path.write_text('[]')
    return notifications


def do_reindex(config_path):
    """Main reindex routine. Returns (new_count, total_count)."""
    config.init_config(config_path)
    logger = setup_logging()

    logger.info("=" * 50)
    logger.info("Cron reindex started")

    if not acquire_lock(logger):
        return 0, 0

    try:
        db_path = config.db_path()

        # Purge expired listings first
        expired = database.purge_expired(db_path)
        if expired:
            logger.info(f"Purged {expired} expired listings")

        # Reindex all sources
        new_jobs = reindex_all_sources(db_path, logger)

        # Write notifications for new jobs
        if new_jobs:
            write_notifications(new_jobs, logger)
            logger.info(f"New jobs found: {len(new_jobs)}")
            for job in new_jobs[:10]:  # Log first 10
                logger.info(f"  NEW: {job.title} @ {job.employer} [{job.source}]")
            if len(new_jobs) > 10:
                logger.info(f"  ... and {len(new_jobs) - 10} more")
        else:
            logger.info("No new jobs found this cycle.")

        total = database.get_job_count(db_path)
        logger.info(f"Index total: {total} jobs")
        logger.info("Cron reindex finished")
        return len(new_jobs), total

    except Exception as e:
        logger.error(f"Reindex failed: {e}", exc_info=True)
        return 0, 0
    finally:
        release_lock()


# --- Cron installation helpers ---

def _get_cron_command(config_path):
    """Build the cron command string."""
    python = sys.executable
    module_path = Path(__file__).resolve()
    return f'{python} {module_path} --config "{config_path}"'


def install_cron(config_path, interval_hours=6):
    """Install a crontab entry for periodic reindexing."""
    cmd = _get_cron_command(config_path)
    cron_schedule = f'0 */{interval_hours} * * *'
    cron_line = f'{cron_schedule} {cmd}'
    marker = '# nhsjobsearch-cron'

    # Read existing crontab
    try:
        result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
        existing = result.stdout if result.returncode == 0 else ''
    except FileNotFoundError:
        print("Error: crontab command not found.")
        return False

    # Remove any existing nhsjobsearch entries
    lines = [l for l in existing.splitlines() if marker not in l]
    lines.append(f'{cron_line}  {marker}')

    # Write back
    new_crontab = '\n'.join(lines) + '\n'
    proc = subprocess.run(['crontab', '-'], input=new_crontab, text=True, capture_output=True)

    if proc.returncode == 0:
        print(f"Cron job installed: every {interval_hours} hours")
        print(f"  Schedule: {cron_schedule}")
        print(f"  Command:  {cmd}")
        print(f"\nView with: crontab -l")
        print(f"Logs at:   {_log_path()}")
        return True
    else:
        print(f"Failed to install cron: {proc.stderr}")
        return False


def uninstall_cron():
    """Remove the nhsjobsearch crontab entry."""
    marker = '# nhsjobsearch-cron'

    try:
        result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
        if result.returncode != 0:
            print("No crontab found.")
            return
    except FileNotFoundError:
        print("Error: crontab command not found.")
        return

    lines = [l for l in result.stdout.splitlines() if marker not in l]
    new_crontab = '\n'.join(lines) + '\n' if lines else ''

    subprocess.run(['crontab', '-'], input=new_crontab, text=True)
    print("Cron job removed.")


def show_pending():
    """Print pending notifications."""
    notifications = read_pending_notifications()
    if not notifications:
        print("No pending notifications.")
        return

    print(f"{len(notifications)} pending notifications:\n")
    for n in notifications:
        print(f"  [{n['source'].upper()}] {n['title']}")
        print(f"    {n['employer']} — {n['location']}")
        if n.get('salary'):
            print(f"    {n['salary']}")
        print(f"    {n['url']}")
        print()


def main():
    parser = argparse.ArgumentParser(description='NHS Job Search cron reindexer')
    parser.add_argument('--config', default='~/.config/nhs-job-search/config.ini',
                        help='Path to config file')
    parser.add_argument('--install', action='store_true',
                        help='Install crontab entry')
    parser.add_argument('--uninstall', action='store_true',
                        help='Remove crontab entry')
    parser.add_argument('--interval', type=int, default=6,
                        help='Reindex interval in hours (default: 6)')
    parser.add_argument('--pending', action='store_true',
                        help='Show pending new-job notifications')
    parser.add_argument('--clear', action='store_true',
                        help='Clear pending notifications')

    args = parser.parse_args()
    config_path = os.path.expanduser(args.config)

    if args.install:
        config.init_config(config_path)
        install_cron(config_path, args.interval)
    elif args.uninstall:
        uninstall_cron()
    elif args.pending:
        config.init_config(config_path)
        show_pending()
    elif args.clear:
        config.init_config(config_path)
        cleared = consume_notifications()
        print(f"Cleared {len(cleared)} notifications.")
    else:
        do_reindex(config_path)


if __name__ == '__main__':
    main()