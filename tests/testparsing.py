"""
Test the connector parsing logic with sample HTML.
Run from project root with: python -m tests.testparsing
"""
import sys
import os

# Add the src directory to path so 'import nhsjobsearch' works
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from nhsjobsearch.nhsconnector import NHSJobsConnector
from nhsjobsearch.dwpconnector import DWPJobsConnector


# === Sample HTML snippets from actual pages ===

SAMPLE_NHS_SEARCH_HTML = """
<ul>
<li>
  <h2><a href="/candidate/jobadvert/C9246-25-1420?language=">Central CAIST Assistant Practitioner</a></h2>
  <h3>Norfolk &amp; Suffolk Foundation NHS Trust Norwich NR1 3RE</h3>
  <ul>
    <li>Salary: <strong>£27,485 to £30,162 a year</strong></li>
    <li>Date posted: <strong>15 December 2025</strong></li>
    <li>Closing date: <strong>5 January 2026</strong></li>
    <li>Contract type: <strong>Permanent</strong></li>
    <li>Working pattern: <strong>Flexible working, Full time</strong></li>
  </ul>
</li>
<li>
  <h2><a href="/candidate/jobadvert/U0017-25-0040?language=">Senior Staff Nurse</a></h2>
  <h3>Caretech Community Services Ltd Ditchingham, Suffolk NR35 2QL</h3>
  <ul>
    <li>Salary: <strong>£48,859.20 to £48,859.20 a year</strong></li>
    <li>Date posted: <strong>15 December 2025</strong></li>
    <li>Closing date: <strong>14 January 2026</strong></li>
    <li>Contract type: <strong>Permanent</strong></li>
    <li>Working pattern: <strong>Full time</strong></li>
  </ul>
</li>
</ul>
"""

SAMPLE_DWP_SEARCH_HTML = """
<div id="search_results">
  <h3><a href="/details/17924892">Healthcare Assistant</a></h3>
  <ul>
    <li>22 February 2026</li>
    <li><strong>Action Staffing LTD</strong> - Hove, East Sussex</li>
    <li>On-site only</li>
    <li>Permanent</li>
    <li>Full time</li>
  </ul>
  <p>Action Staffing is recruiting for Female Healthcare Assistants for immediate starts.</p>

  <h3><a href="/details/17924856">Night Senior Care Assistant</a></h3>
  <ul>
    <li>22 February 2026</li>
    <li><strong>Agincare Group</strong> - Chatham, ME5 7JZ</li>
    <li><strong>£12.75 per hour</strong></li>
    <li>Permanent</li>
    <li>Full time</li>
  </ul>
  <p>Are you an experienced care professional looking for a new challenge?</p>
</div>
"""

SAMPLE_DWP_DETAIL_HTML = """
<main id="main">
  <h1>Healthcare Assistant</h1>
  <table>
    <tr><td>Posting date:</td><td>22 February 2026</td></tr>
    <tr><td>Hours:</td><td>Full time</td></tr>
    <tr><td>Closing date:</td><td>24 March 2026</td></tr>
    <tr><td>Location:</td><td>Hove, East Sussex</td></tr>
    <tr><td>Company:</td><td>Action Staffing LTD</td></tr>
    <tr><td>Job type:</td><td>Permanent</td></tr>
  </table>
  <h2>Summary</h2>
  <p>Action Staffing is recruiting for Female Healthcare Assistants for immediate starts.</p>
  <p>Shift Patterns Available: Long Days, Short Days, Nights.</p>
  <h2>Related jobs</h2>
</main>
"""


def test_nhs_parsing():
    print("=== Testing NHS Jobs Parsing ===")
    connector = NHSJobsConnector()
    jobs = connector._parse_search_page(SAMPLE_NHS_SEARCH_HTML)

    assert len(jobs) == 2, f"Expected 2 jobs, got {len(jobs)}"

    job1 = jobs[0]
    assert job1.title == "Central CAIST Assistant Practitioner"
    assert "C9246-25-1420" in job1.url
    assert job1.source == 'nhs'
    assert '27,485' in job1.salary
    assert job1.contract_type == 'Permanent'
    print(f"  Job 1: {job1.title}")
    print(f"    Employer: {job1.employer}")
    print(f"    Salary: {job1.salary}")
    print(f"    Contract: {job1.contract_type}")
    print(f"    URL: {job1.url}")

    job2 = jobs[1]
    assert job2.title == "Senior Staff Nurse"
    assert '48,859' in job2.salary
    print(f"  Job 2: {job2.title}")
    print(f"    Employer: {job2.employer}")
    print(f"    Salary: {job2.salary}")

    print("  ✓ NHS parsing OK\n")


def test_dwp_parsing():
    print("=== Testing DWP Find a Job Parsing ===")
    connector = DWPJobsConnector()
    jobs = connector._parse_search_page(SAMPLE_DWP_SEARCH_HTML)

    assert len(jobs) == 2, f"Expected 2 jobs, got {len(jobs)}"

    job1 = jobs[0]
    assert job1.title == "Healthcare Assistant"
    assert "17924892" in job1.url
    assert job1.employer == "Action Staffing LTD"
    assert job1.location == "Hove, East Sussex"
    assert job1.source == 'dwp'
    assert job1.contract_type == "Permanent"
    assert job1.working_pattern == "Full time"
    print(f"  Job 1: {job1.title}")
    print(f"    Employer: {job1.employer}")
    print(f"    Location: {job1.location}")
    print(f"    Contract: {job1.contract_type}")
    print(f"    Pattern: {job1.working_pattern}")
    print(f"    Date: {job1.date_posted}")

    job2 = jobs[1]
    assert job2.title == "Night Senior Care Assistant"
    assert job2.employer == "Agincare Group"
    assert '12.75' in job2.salary
    print(f"  Job 2: {job2.title}")
    print(f"    Employer: {job2.employer}")
    print(f"    Salary: {job2.salary}")

    print("  ✓ DWP parsing OK\n")


def test_dwp_detail_parsing():
    print("=== Testing DWP Detail Page Parsing ===")
    connector = DWPJobsConnector()
    detail = connector._parse_job_detail(SAMPLE_DWP_DETAIL_HTML, "https://findajob.dwp.gov.uk/details/17924892")

    assert detail['title'] == "Healthcare Assistant"
    assert "immediate starts" in detail['description']
    assert detail['closing_date'] == '24 March 2026'
    assert detail['metadata']['Company'] == 'Action Staffing LTD'
    print(f"  Title: {detail['title']}")
    print(f"  Closing: {detail['closing_date']}")
    print(f"  Description: {detail['description'][:80]}...")

    print("  ✓ DWP detail parsing OK\n")


def test_database():
    print("=== Testing Database ===")
    from nhsjobsearch import config, database
    from nhsjobsearch.jobitem import JobItem

    # Use temp DB
    test_db = '/tmp/test_jobs.db'
    if os.path.exists(test_db):
        os.unlink(test_db)

    config.init_config('/tmp/test_nhs_config.ini')

    jobs = [
        JobItem(url="https://example.com/1", title="Staff Nurse",
                employer="NHS Trust A", location="London",
                salary="£30,000", date_posted="2025-12-15",
                contract_type="Permanent", source="nhs"),
        JobItem(url="https://example.com/2", title="Care Assistant",
                employer="Care Home B", location="Manchester",
                salary="£12/hr", date_posted="2025-12-14",
                contract_type="Temporary", source="dwp"),
        JobItem(url="https://example.com/3", title="Nurse Practitioner",
                employer="GP Surgery C", location="London",
                salary="£45,000", date_posted="2025-12-13",
                source="nhs"),
    ]

    database.index_jobs(jobs, test_db)

    # Test get all
    all_jobs = database.get_all_jobs(test_db)
    assert len(all_jobs) == 3, f"Expected 3, got {len(all_jobs)}"
    print(f"  All jobs: {len(all_jobs)}")

    # Test filter by source
    nhs_jobs = database.get_all_jobs(test_db, source='nhs')
    assert len(nhs_jobs) == 2
    print(f"  NHS jobs: {len(nhs_jobs)}")

    # Test search
    results = database.search_jobs(test_db, keyword='Nurse')
    assert len(results) == 2  # Staff Nurse + Nurse Practitioner
    print(f"  Search 'Nurse': {len(results)} results")

    # Test location search
    results = database.search_jobs(test_db, location='London')
    assert len(results) == 2
    print(f"  Location 'London': {len(results)} results")

    # Test count
    count = database.get_job_count(test_db)
    assert count == 3
    print(f"  Total count: {count}")

    # Cleanup
    os.unlink(test_db)
    print("  ✓ Database OK\n")


def test_jobitem():
    print("=== Testing JobItem ===")
    from nhsjobsearch.jobitem import JobItem, format_age

    job = JobItem(
        url="https://example.com/job1",
        title="Test Nurse",
        employer="Test Trust",
        date_posted="2025-12-10",
    )
    assert bool(job) is True
    assert job.name == "Test Nurse"
    assert 'ago' in job.age or job.age == 'N/A'
    print(f"  Job: {job.name}, age: {job.age}")

    empty = JobItem(url="")
    assert bool(empty) is False
    print(f"  Empty job: bool={bool(empty)}")

    # Test format_age with various formats
    assert format_age(None) == 'N/A'
    assert format_age('') == 'N/A'
    print(f"  format_age(None) = {format_age(None)}")

    print("  ✓ JobItem OK\n")


def test_nhs_salary_newlines():
    """Test that salary fields with embedded newlines are sanitised."""
    print("=== Testing NHS Salary Sanitisation ===")

    # Real HTML from NHS Jobs where salary contains newlines:
    # "£12.62\nan hour" renders as "£12.62" then newline breaks the row
    html_with_newline_salary = """
    <ul>
    <li>
      <h2><a href="/candidate/jobadvert/TEST-001?language=">Administrator - Wokingham Division</a></h2>
      <h3>Modality Partnership Wokingham RG40 1XS</h3>
      <ul>
        <li>Salary: <strong>£12.62
an hour</strong></li>
        <li>Date posted: <strong>20 February 2026</strong></li>
        <li>Closing date: <strong>5 March 2026</strong></li>
        <li>Contract type: <strong>Permanent</strong></li>
        <li>Working pattern: <strong>Part time</strong></li>
      </ul>
    </li>
    </ul>
    """
    connector = NHSJobsConnector()
    jobs = connector._parse_search_page(html_with_newline_salary)

    assert len(jobs) == 1, f"Expected 1 job, got {len(jobs)}"
    job = jobs[0]

    # The salary should be sanitised — no newlines
    assert '\n' not in job.salary, f"Salary contains newline: {repr(job.salary)}"
    assert '\r' not in job.salary, f"Salary contains carriage return: {repr(job.salary)}"
    assert '12.62' in job.salary
    assert 'an hour' in job.salary
    print(f"  Salary: {repr(job.salary)}")

    # Also check employer is clean
    assert '\n' not in job.employer
    print(f"  Employer: {repr(job.employer)}")

    print("  ✓ Salary sanitisation OK\n")


if __name__ == '__main__':
    test_jobitem()
    test_nhs_parsing()
    test_nhs_salary_newlines()
    test_dwp_parsing()
    test_dwp_detail_parsing()
    test_database()
    print("All tests passed! ✓")