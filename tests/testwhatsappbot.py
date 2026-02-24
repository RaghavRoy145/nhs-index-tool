"""
Test WhatsApp bot message formatting and state logic.
Run from project root with: python -m tests.testwhatsappbot
"""
import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from nhsjobsearch import config
from nhsjobsearch.jobitem import JobItem
from nhsjobsearch.whatsappbot import (
    format_morning_digest,
    format_afternoon_alert,
    BotState,
)


def test_morning_digest_with_jobs():
    print("=== Testing Morning Digest (with jobs) ===")

    jobs = [
        JobItem(url="https://example.com/1", title="Staff Nurse - Cardiology",
                employer="Norfolk NHS Trust", salary="£30,000", source="nhs"),
        JobItem(url="https://example.com/2", title="Healthcare Assistant",
                employer="Care Home Ltd", salary="£12/hr", source="dwp"),
        JobItem(url="https://example.com/3", title="Pharmacist",
                employer="London NHS Trust", salary="£45,000", source="nhs"),
    ]

    msg = format_morning_digest(jobs, total_in_db=150)

    assert 'Morning Update' in msg
    assert '3 new roles' in msg
    assert 'Staff Nurse - Cardiology' in msg
    assert 'Healthcare Assistant' in msg
    assert 'Pharmacist' in msg
    assert '150' in msg
    assert 'Norfolk NHS Trust' in msg
    print(f"  Message length: {len(msg)} chars")
    print(f"  Preview:\n{msg[:300]}...\n")

    print("  ✓ Morning digest with jobs OK\n")


def test_morning_digest_no_jobs():
    print("=== Testing Morning Digest (no jobs) ===")

    msg = format_morning_digest([], total_in_db=200)

    assert 'Morning Update' in msg
    assert 'No new roles' in msg
    assert '200' in msg
    print(f"  Message: {msg[:200]}...")

    print("  ✓ Morning digest no jobs OK\n")


def test_afternoon_alert():
    print("=== Testing Afternoon Alert ===")

    jobs = [
        JobItem(url="https://example.com/10", title="Occupational Therapist",
                employer="Sussex NHS Trust", salary="£35,000", source="nhs"),
    ]

    msg = format_afternoon_alert(jobs)

    assert 'New roles just posted' in msg
    assert '1 new role' in msg  # singular
    assert 'Occupational Therapist' in msg
    assert 'this morning' in msg
    print(f"  Message: {msg[:200]}...")

    print("  ✓ Afternoon alert OK\n")


def test_morning_digest_many_jobs():
    print("=== Testing Morning Digest (>15 jobs, truncated) ===")

    jobs = [
        JobItem(url=f"https://example.com/{i}", title=f"Job {i}",
                employer=f"Trust {i}", source="nhs")
        for i in range(20)
    ]

    msg = format_morning_digest(jobs, total_in_db=500)

    assert '20 new roles' in msg
    assert 'Job 0' in msg    # First job shown
    assert 'Job 14' in msg   # 15th job shown
    assert '... and 5 more' in msg  # Truncation notice
    print(f"  Truncation notice present: ✓")

    print("  ✓ Truncated digest OK\n")


def test_bot_state():
    print("=== Testing BotState ===")

    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        state_file = f.name

    try:
        # Fresh state
        state = BotState(state_file)
        assert state.get('last_morning_notify') is None
        assert state.get('morning_job_urls') == []
        print("  Fresh state: ✓")

        # Set values
        state.set('last_morning_notify', '2026-02-24T09:00:00')
        state.set('morning_job_urls', ['url1', 'url2', 'url3'])

        # Reload from disk
        state2 = BotState(state_file)
        assert state2.get('last_morning_notify') == '2026-02-24T09:00:00'
        assert len(state2.get('morning_job_urls')) == 3
        print("  Persist and reload: ✓")

        # Update
        state2.set('morning_job_urls', ['url1', 'url2', 'url3', 'url4'])
        state3 = BotState(state_file)
        assert len(state3.get('morning_job_urls')) == 4
        print("  Update: ✓")

    finally:
        os.unlink(state_file)

    print("  ✓ BotState OK\n")


def test_config_defaults():
    print("=== Testing WhatsApp Config Defaults ===")

    config.init_config('/tmp/test_whatsapp_config.ini')

    from nhsjobsearch.whatsappbot import _ensure_whatsapp_config
    _ensure_whatsapp_config()

    assert 'WHATSAPP' in config.CONFIG
    assert config.CONFIG['WHATSAPP']['enabled'] == 'false'
    assert config.CONFIG['WHATSAPP']['reindex_times'] == '08:00, 16:00'
    assert config.CONFIG['WHATSAPP']['notify_morning'] == '09:00'
    assert config.CONFIG['WHATSAPP']['notify_afternoon_delay_minutes'] == '5'
    print("  Default config values: ✓")

    # Clean up
    os.unlink('/tmp/test_whatsapp_config.ini')

    print("  ✓ Config defaults OK\n")


if __name__ == '__main__':
    test_morning_digest_with_jobs()
    test_morning_digest_no_jobs()
    test_afternoon_alert()
    test_morning_digest_many_jobs()
    test_bot_state()
    test_config_defaults()
    print("All WhatsApp bot tests passed! ✓")