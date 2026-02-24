"""
Test the cron reindex and diff detection logic.
Run from project root with: python -m tests.testcron
"""
import sys
import os
import json
from pathlib import Path

# Add the src directory to path so 'import nhsjobsearch' works
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from src.nhsjobsearch import config, database
from src.nhsjobsearch.jobitem import JobItem
from src.nhsjobsearch.cronreindex import (
    write_notifications, read_pending_notifications,
    consume_notifications, acquire_lock, release_lock,
)

TEST_DB = '/tmp/test_cron_jobs.db'
TEST_CONFIG = '/tmp/test_cron_config.ini'


def cleanup():
    """Remove temp files. Safe if they don't exist."""
    for f in [TEST_DB, TEST_CONFIG]:
        if os.path.exists(f):
            os.unlink(f)

    # Clean up notification and lock files from the cache dir
    cache_dir = Path(os.path.expanduser(config.CONFIG['CACHE']['path']))
    for name in ['new_jobs.json', 'reindex.lock']:
        p = cache_dir / name
        if p.exists():
            p.unlink()


def test_index_with_diff():
    print("=== Testing index_jobs_with_diff ===")
    config.init_config(TEST_CONFIG)

    if os.path.exists(TEST_DB):
        os.unlink(TEST_DB)

    # First batch: 3 jobs
    batch1 = [
        JobItem(url="https://example.com/1", title="Staff Nurse",
                employer="Trust A", source="nhs"),
        JobItem(url="https://example.com/2", title="Care Assistant",
                employer="Trust B", source="dwp"),
        JobItem(url="https://example.com/3", title="Pharmacist",
                employer="Trust C", source="nhs"),
    ]
    new, updated, total = database.index_jobs_with_diff(batch1, TEST_DB)
    assert len(new) == 3, f"Expected 3 new, got {len(new)}"
    assert len(updated) == 0, f"Expected 0 updated, got {len(updated)}"
    assert total == 3
    print(f"  Batch 1: {len(new)} new, {len(updated)} updated, {total} total ✓")

    # Second batch: 2 existing + 2 new
    batch2 = [
        JobItem(url="https://example.com/1", title="Staff Nurse",
                employer="Trust A", source="nhs"),
        JobItem(url="https://example.com/2", title="Care Assistant",
                employer="Trust B", source="dwp"),
        JobItem(url="https://example.com/4", title="Radiographer",
                employer="Trust D", source="nhs"),
        JobItem(url="https://example.com/5", title="Midwife",
                employer="Trust E", source="nhs"),
    ]
    new, updated, total = database.index_jobs_with_diff(batch2, TEST_DB)
    assert len(new) == 2, f"Expected 2 new, got {len(new)}"
    assert len(updated) == 2, f"Expected 2 updated, got {len(updated)}"
    assert total == 4
    new_titles = {j.title for j in new}
    assert 'Radiographer' in new_titles
    assert 'Midwife' in new_titles
    print(f"  Batch 2: {len(new)} new ({new_titles}), {len(updated)} updated ✓")

    # Verify total count in DB
    count = database.get_job_count(TEST_DB)
    assert count == 5, f"Expected 5 in DB, got {count}"
    print(f"  DB total: {count} ✓")

    print("  ✓ Diff detection OK\n")


def test_notifications():
    print("=== Testing Notifications ===")
    # Config MUST be initialized before any notification functions,
    # because they read config.CONFIG['CACHE']['path'] for file paths.
    config.init_config(TEST_CONFIG)

    # Clear any existing
    consume_notifications()

    import logging
    logger = logging.getLogger('test')
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())

    new_jobs = [
        JobItem(url="https://example.com/10", title="Senior Nurse",
                employer="Trust X", location="London", salary="£40,000",
                source="nhs"),
        JobItem(url="https://example.com/11", title="HCA",
                employer="Care Co", location="Manchester", salary="£12/hr",
                source="dwp"),
    ]
    write_notifications(new_jobs, logger)

    # Read them back
    pending = read_pending_notifications()
    assert len(pending) == 2, f"Expected 2 pending, got {len(pending)}"
    assert pending[0]['title'] == 'Senior Nurse'
    assert pending[1]['source'] == 'dwp'
    print(f"  Written and read: {len(pending)} notifications ✓")

    # Write more — should append
    write_notifications([
        JobItem(url="https://example.com/12", title="Physio",
                employer="Trust Y", source="nhs"),
    ], logger)
    pending = read_pending_notifications()
    assert len(pending) == 3, f"Expected 3 pending, got {len(pending)}"
    print(f"  After append: {len(pending)} notifications ✓")

    # Consume (read + clear)
    consumed = consume_notifications()
    assert len(consumed) == 3
    remaining = read_pending_notifications()
    assert len(remaining) == 0
    print(f"  Consumed {len(consumed)}, remaining: {len(remaining)} ✓")

    print("  ✓ Notifications OK\n")


def test_lock():
    print("=== Testing File Lock ===")
    config.init_config(TEST_CONFIG)

    import logging
    logger = logging.getLogger('test')
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())

    # Should acquire
    assert acquire_lock(logger) is True
    print("  Acquired lock ✓")

    # Should fail (already held)
    assert acquire_lock(logger) is False
    print("  Second acquire blocked ✓")

    # Release
    release_lock()
    print("  Released ✓")

    # Should acquire again
    assert acquire_lock(logger) is True
    release_lock()
    print("  Re-acquired after release ✓")

    print("  ✓ Lock OK\n")


if __name__ == '__main__':
    test_index_with_diff()
    test_notifications()
    test_lock()
    cleanup()
    print("All cron tests passed! ✓")