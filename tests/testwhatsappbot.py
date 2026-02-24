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
    format_interval_alert,
    _split_messages,
    _format_job_entry,
    WHATSAPP_CHAR_LIMIT,
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

    messages = format_morning_digest(jobs, total_in_db=150)

    assert isinstance(messages, list), "Should return a list"
    assert len(messages) == 1, f"3 small jobs should fit in 1 message, got {len(messages)}"

    msg = messages[0]
    assert 'Morning Update' in msg
    assert '3 new roles' in msg
    assert 'Staff Nurse - Cardiology' in msg
    assert 'Healthcare Assistant' in msg
    assert 'Pharmacist' in msg
    assert '150' in msg
    assert 'Norfolk NHS Trust' in msg
    # URLs should be present
    assert 'https://example.com/1' in msg
    assert 'https://example.com/2' in msg
    print(f"  Message length: {len(msg)} chars")
    print(f"  URLs present: ✓")

    print("  ✓ Morning digest with jobs OK\n")


def test_morning_digest_no_jobs():
    print("=== Testing Morning Digest (no jobs) ===")

    messages = format_morning_digest([], total_in_db=200)

    assert isinstance(messages, list)
    assert len(messages) == 1
    msg = messages[0]
    assert 'Morning Update' in msg
    assert 'No new roles' in msg
    assert '200' in msg
    print(f"  Message: {msg[:200]}...")

    print("  ✓ Morning digest no jobs OK\n")


def test_interval_alert():
    print("=== Testing Interval Alert ===")

    jobs = [
        JobItem(url="https://example.com/10", title="Occupational Therapist",
                employer="Sussex NHS Trust", salary="£35,000", source="nhs"),
    ]

    messages = format_interval_alert(jobs)

    assert isinstance(messages, list)
    assert len(messages) == 1
    msg = messages[0]
    assert 'New roles just posted' in msg
    assert '1 new role' in msg  # singular
    assert 'Occupational Therapist' in msg
    assert 'since last check' in msg
    assert 'https://example.com/10' in msg
    print(f"  Message: {msg[:200]}...")

    print("  ✓ Interval alert OK\n")


def test_job_entry_format():
    print("=== Testing Job Entry Format ===")

    job = JobItem(url="https://www.jobs.nhs.uk/job/ABC123",
                  title="Band 6 Occupational Therapist",
                  employer="Royal Free London NHS Trust",
                  salary="£37,338 - £44,962", source="nhs")

    entry = _format_job_entry(1, job)

    assert '*Band 6 Occupational Therapist*' in entry
    assert 'Royal Free London NHS Trust' in entry
    assert '£37,338 - £44,962' in entry
    assert 'https://www.jobs.nhs.uk/job/ABC123' in entry
    print(f"  Entry:\n{entry}")

    # Long title gets truncated
    long_job = JobItem(url="https://example.com/x",
                       title="A" * 80, employer="Trust", source="nhs")
    long_entry = _format_job_entry(1, long_job)
    assert '…' in long_entry
    print("  Long title truncated: ✓")

    print("  ✓ Job entry format OK\n")


def test_multi_message_split():
    print("=== Testing Multi-Message Splitting ===")

    # Create 50 jobs with long titles + URLs that won't fit in one message
    jobs = [
        JobItem(
            url=f"https://www.jobs.nhs.uk/candidate/jobadvert/LONG-{i:04d}",
            title=f"Senior Advanced Clinical Specialist Practitioner Band 7 - Department {i}",
            employer="University Hospitals of North Midlands NHS Foundation Trust",
            salary="£43,742 to £50,056 a year",
            source="nhs")
        for i in range(50)
    ]

    messages = format_morning_digest(jobs, total_in_db=800)

    assert isinstance(messages, list)
    assert len(messages) > 1, f"50 long jobs with URLs should need >1 message, got {len(messages)}"
    print(f"  Split into {len(messages)} messages")

    # Every message must be under the Twilio limit (with part numbering overhead)
    for i, msg in enumerate(messages):
        assert len(msg) <= 1600, f"Message {i+1} too long: {len(msg)} chars"
        print(f"  Message {i+1}: {len(msg)} chars")

    # First message should have header and part numbering
    assert '[1/' in messages[0]
    assert 'Morning Update' in messages[0]
    assert '50 new roles' in messages[0]

    # Last message should have footer
    assert '800 total jobs' in messages[-1]

    # All jobs should appear across all messages combined
    combined = '\n'.join(messages)

    # URLs should be present for all 50 jobs
    assert 'LONG-0000' in combined
    assert 'LONG-0049' in combined

    # Numbering should cover 1..50
    assert '1. *Senior' in combined
    assert '50. *Senior' in combined
    print("  All 50 jobs present across messages: ✓")
    print("  URLs present: ✓")

    print("  ✓ Multi-message split OK\n")


def test_single_message_no_part_numbers():
    print("=== Testing Single Message (no part numbers) ===")

    jobs = [
        JobItem(url="https://example.com/1", title="Nurse",
                employer="Trust", source="nhs"),
    ]

    messages = format_morning_digest(jobs, total_in_db=50)
    assert len(messages) == 1
    assert '[1/' not in messages[0]
    print("  No part numbering: ✓")

    print("  ✓ Single message OK\n")


def test_interval_alert_multi():
    print("=== Testing Interval Alert Multi-Message ===")

    jobs = [
        JobItem(
            url=f"https://uk.indeed.com/viewjob?jk=abc{i:04d}",
            title=f"Assistant Psychologist - Trust {i}",
            employer="Long NHS Foundation Trust Name Here",
            salary="£28,000 a year",
            source="indeed")
        for i in range(30)
    ]

    messages = format_interval_alert(jobs)

    assert isinstance(messages, list)
    for msg in messages:
        assert len(msg) <= 1600
    print(f"  Split into {len(messages)} messages, all under 1600 chars")

    combined = '\n'.join(messages)
    assert 'Trust 0' in combined
    assert 'Trust 29' in combined
    assert 'since last check' in combined

    print("  ✓ Interval alert multi OK\n")


def test_bot_state():
    print("=== Testing BotState ===")

    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        state_file = f.name

    try:
        state = BotState(state_file)
        assert state.get('last_morning_notify') is None
        assert state.get('morning_job_urls') == []
        print("  Fresh state: ✓")

        state.set('last_morning_notify', '2026-02-24T09:00:00')
        state.set('morning_job_urls', ['url1', 'url2', 'url3'])
        state.set('last_notify_urls', ['url1', 'url2'])

        state2 = BotState(state_file)
        assert state2.get('last_morning_notify') == '2026-02-24T09:00:00'
        assert len(state2.get('morning_job_urls')) == 3
        assert len(state2.get('last_notify_urls')) == 2
        print("  Persist and reload: ✓")

        state2.set('morning_job_urls', ['url1', 'url2', 'url3', 'url4'])
        state3 = BotState(state_file)
        assert len(state3.get('morning_job_urls')) == 4
        print("  Update: ✓")

    finally:
        os.unlink(state_file)

    print("  ✓ BotState OK\n")


def test_config_defaults():
    print("=== Testing WhatsApp Config Defaults ===")

    config.CONFIG.clear()
    config.init_config('/tmp/test_whatsapp_config.ini')

    from nhsjobsearch.whatsappbot import _ensure_whatsapp_config
    _ensure_whatsapp_config()

    assert 'WHATSAPP' in config.CONFIG
    assert config.CONFIG['WHATSAPP']['enabled'] == 'false'
    assert config.CONFIG['WHATSAPP']['interval_hours'] == '6'
    assert config.CONFIG['WHATSAPP']['morning_time'] == '08:00'
    assert config.CONFIG['WHATSAPP']['notify_delay_minutes'] == '5'
    print("  Default config values: ✓")

    os.unlink('/tmp/test_whatsapp_config.ini')

    print("  ✓ Config defaults OK\n")


if __name__ == '__main__':
    test_morning_digest_with_jobs()
    test_morning_digest_no_jobs()
    test_interval_alert()
    test_job_entry_format()
    test_multi_message_split()
    test_single_message_no_part_numbers()
    test_interval_alert_multi()
    test_bot_state()
    test_config_defaults()
    print("All WhatsApp bot tests passed! ✓")