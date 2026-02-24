"""
Test Indeed UK connector parsing.
Run from project root with: python -m tests.testindeed
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from nhsjobsearch.indeedconnector import IndeedConnector
from nhsjobsearch.indeedconnector import _sanitise


# Sample HTML modeled on the actual fetched page structure from
# uk.indeed.com/jobs?q=assistant+psychologist
SAMPLE_SEARCH_HTML = """
<html>
<body>
<div id="mosaic-provider-jobcards">
  <ul>
    <li>
      <table>
        <tr>
          <td>
            <a href="/rc/clk?jk=7ac65534a3596357&bb=abc123&fccid=459d89aa">
              Assistant Psychologist
            </a>
            <span class="companyName">Llamau Limited</span>
            <div class="companyLocation">Cardiff CF11 9HA</div>
            <div class="salary-snippet">£28,000 a year</div>
            <span class="date">3 days ago</span>
            <div class="job-snippet">
              We benchmark psychologist salaries against NHS rates.
            </div>
          </td>
        </tr>
      </table>
    </li>
    <li>
      <table>
        <tr>
          <td>
            <a href="/rc/clk?jk=643486a2bf384b8a&bb=xyz789&fccid=7691ebb7">
              Assistant Psychologist - CAMHS
            </a>
            <span class="companyName">Pennine Care NHS Foundation Trust</span>
            <div class="companyLocation">Bury BL9 7TD</div>
            <span class="date">1 day ago</span>
            <div class="job-snippet">
              You will support the psychological therapies lead.
            </div>
          </td>
        </tr>
      </table>
    </li>
    <li>
      <table>
        <tr>
          <td>
            <a href="/viewjob?jk=a1b2c3d4e5f67890">
              Clinical Psychologist
            </a>
            <span class="companyName">Harley Therapy</span>
            <div class="companyLocation">London</div>
            <div class="salary-snippet">£45,000 - £55,000 a year</div>
          </td>
        </tr>
      </table>
    </li>
  </ul>
</div>
<div class="jobsearch-JobCountAndSortPane-jobCount">
  <span>342 jobs</span>
</div>
</body>
</html>
"""

# Sample JSON data matching Indeed's window.mosaic.providerData structure
SAMPLE_JSON_HTML = """
<html>
<head>
<script>
window.mosaic.providerData["mosaic-provider-jobcards"]={"metaData":{"mosaicProviderJobCardsModel":{"results":[
  {"jobkey":"aaa111bbb222","title":"Band 5 Staff Nurse","company":"Royal Free London NHS","formattedLocation":"London NW3","salarySnippet":{"text":"\\u00a331,469 - \\u00a338,308 a year"},"formattedRelativeDate":"2 days ago","jobTypes":["permanent"],"snippet":"<b>Nurse</b> needed for acute ward."},
  {"jobkey":"ccc333ddd444","displayTitle":"Healthcare Assistant","company":"Bupa","formattedLocation":"Manchester","extractedSalary":{"min":23000,"max":26000,"type":"yearly"},"formattedRelativeDate":"Just posted","jobTypes":["fulltime"],"snippet":"Support patients with daily activities."}
],"tierSummaries":[{"jobCount":128}]}}};
</script>
</head>
<body></body>
</html>
"""


def test_sanitise():
    print("=== Testing _sanitise ===")
    assert _sanitise("hello\nworld") == "hello world"
    assert _sanitise("  £28,000\n\n a year  ") == "£28,000 a year"
    assert _sanitise("") == ""
    assert _sanitise(None) == ""
    assert _sanitise("Band\t5\r\nNurse") == "Band 5 Nurse"
    print("  ✓ Sanitise OK\n")


def test_html_parsing():
    print("=== Testing HTML Parsing ===")
    connector = IndeedConnector()
    jobs = connector._parse_jobs_from_html(SAMPLE_SEARCH_HTML)

    assert len(jobs) == 3, f"Expected 3 jobs, got {len(jobs)}"
    print(f"  Parsed {len(jobs)} jobs")

    # Job 1
    j1 = jobs[0]
    assert j1.title == 'Assistant Psychologist'
    assert j1.employer == 'Llamau Limited'
    assert 'Cardiff' in j1.location
    assert '28,000' in j1.salary
    assert j1.source == 'indeed'
    assert j1.job_reference == '7ac65534a3596357'
    assert j1.url == 'https://uk.indeed.com/viewjob?jk=7ac65534a3596357'
    print(f"  Job 1: {j1.title} @ {j1.employer} — {j1.salary}")

    # Job 2
    j2 = jobs[1]
    assert 'CAMHS' in j2.title
    assert 'Pennine Care' in j2.employer
    assert j2.job_reference == '643486a2bf384b8a'
    print(f"  Job 2: {j2.title} @ {j2.employer}")

    # Job 3 (from /viewjob?jk= link)
    j3 = jobs[2]
    assert j3.title == 'Clinical Psychologist'
    assert j3.job_reference == 'a1b2c3d4e5f67890'
    print(f"  Job 3: {j3.title} @ {j3.employer}")

    print("  ✓ HTML parsing OK\n")


def test_json_parsing():
    print("=== Testing JSON Parsing ===")
    connector = IndeedConnector()

    # Extract JSON
    json_data = connector._extract_json_data(SAMPLE_JSON_HTML)
    assert json_data is not None, "Failed to extract JSON"
    print("  JSON extracted: ✓")

    # Parse jobs
    jobs = connector._parse_jobs_from_json(json_data)
    assert len(jobs) == 2, f"Expected 2 jobs, got {len(jobs)}"
    print(f"  Parsed {len(jobs)} jobs from JSON")

    # Job 1 (salarySnippet)
    j1 = jobs[0]
    assert j1.title == 'Band 5 Staff Nurse'
    assert j1.employer == 'Royal Free London NHS'
    assert 'London' in j1.location
    assert '31,469' in j1.salary
    assert j1.contract_type == 'permanent'
    assert j1.job_reference == 'aaa111bbb222'
    assert j1.date_posted == '2 days ago'
    assert 'Nurse' in j1.description  # snippet with HTML stripped
    print(f"  Job 1: {j1.title} — {j1.salary} — {j1.contract_type}")

    # Job 2 (extractedSalary)
    j2 = jobs[1]
    assert j2.title == 'Healthcare Assistant'
    assert j2.employer == 'Bupa'
    assert '23,000' in j2.salary
    assert '26,000' in j2.salary
    assert j2.date_posted == 'Just posted'
    print(f"  Job 2: {j2.title} — {j2.salary}")

    # Total results
    total = connector._parse_total_results(SAMPLE_JSON_HTML)
    assert total == 128
    print(f"  Total results from JSON metadata: {total}")

    print("  ✓ JSON parsing OK\n")


def test_combined_parser_prefers_json():
    print("=== Testing Combined Parser (JSON preferred) ===")
    connector = IndeedConnector()

    jobs = connector._parse_search_page(SAMPLE_JSON_HTML)
    assert len(jobs) == 2
    assert jobs[0].title == 'Band 5 Staff Nurse'  # From JSON
    print(f"  JSON path used: {len(jobs)} jobs")

    # HTML fallback
    jobs2 = connector._parse_search_page(SAMPLE_SEARCH_HTML)
    assert len(jobs2) == 3
    assert jobs2[0].title == 'Assistant Psychologist'  # From HTML
    print(f"  HTML fallback used: {len(jobs2)} jobs")

    print("  ✓ Combined parser OK\n")


def test_total_results_html():
    print("=== Testing Total Results (HTML) ===")
    connector = IndeedConnector()

    total = connector._parse_total_results(SAMPLE_SEARCH_HTML)
    assert total == 342, f"Expected 342, got {total}"
    print(f"  Total from HTML: {total}")

    pages = connector._calc_total_pages(total)
    assert pages == 23, f"Expected 23 pages, got {pages}"
    print(f"  Pages: {pages} (342 results / 15 per page)")

    # Cap at 1000
    pages_big = connector._calc_total_pages(5000)
    assert pages_big <= 67  # 1000 / 15 = 67
    print(f"  Capped pages: {pages_big} (5000 results capped to 1000)")

    print("  ✓ Total results OK\n")


def test_url_construction():
    print("=== Testing URL Construction ===")

    from nhsjobsearch import config
    config.CONFIG.clear()
    config.init_config('/tmp/test_indeed_config.ini')

    config.CONFIG['SEARCH_INDEED']['keyword'] = 'assistant psychologist'
    config.CONFIG['SEARCH_INDEED']['location'] = 'London'
    config.CONFIG['SEARCH_INDEED']['radius'] = '25'
    config.CONFIG['SEARCH_INDEED']['job_type'] = 'fulltime'
    config.CONFIG['SEARCH_INDEED']['max_days_old'] = '7'
    config.CONFIG['SEARCH_INDEED']['sort_by'] = 'date'

    connector = IndeedConnector()
    params = connector._build_search_params(start=0)

    assert params['q'] == 'assistant psychologist'
    assert params['l'] == 'London'
    assert params['radius'] == '25'
    assert params['jt'] == 'fulltime'
    assert params['fromage'] == '7'
    assert params['sort'] == 'date'
    assert params['filter'] == '0'
    assert 'start' not in params  # start=0 is omitted
    print(f"  Params: {params}")

    # With offset
    params2 = connector._build_search_params(start=30)
    assert params2['start'] == '30'
    print(f"  With offset: start={params2['start']}")

    # With keyword override
    params3 = connector._build_search_params(keyword_override='nurse')
    assert params3['q'] == 'nurse'
    print(f"  Override keyword: q={params3['q']}")

    os.unlink('/tmp/test_indeed_config.ini')
    print("  ✓ URL construction OK\n")


def test_skip_non_job_links():
    print("=== Testing Non-Job Link Filtering ===")
    connector = IndeedConnector()

    html_with_noise = """
    <ul>
      <li>
        <a href="/rc/clk?jk=real123abc456">Staff Nurse Band 5</a>
        <span class="companyName">NHS Trust</span>
      </li>
      <li>
        <a href="/career/nurse/salaries/London?jk=sal999aaa000">Salary Search: Staff Nurse salaries in London</a>
      </li>
      <li>
        <a href="/q-nhs-jobs.html?jk=fake999000">View all NHS jobs</a>
      </li>
      <li>
        <a href="/rc/clk?jk=real789def012">Healthcare Assistant</a>
        <span class="companyName">Bupa</span>
      </li>
    </ul>
    """

    jobs = connector._parse_jobs_from_html(html_with_noise)
    titles = [j.title for j in jobs]

    assert 'Staff Nurse Band 5' in titles
    assert 'Healthcare Assistant' in titles
    assert not any('Salary Search' in t for t in titles)
    assert not any('View all' in t for t in titles)
    print(f"  Parsed {len(jobs)} real jobs, filtered noise: {titles}")

    print("  ✓ Non-job link filtering OK\n")


def test_config_defaults():
    print("=== Testing Config Defaults ===")

    from nhsjobsearch import config
    config.CONFIG.clear()
    config.init_config('/tmp/test_indeed_config2.ini')

    assert 'SEARCH_INDEED' in config.CONFIG
    assert config.CONFIG['SEARCH_INDEED']['keyword'] == ''
    assert config.CONFIG['SEARCH_INDEED']['location'] == ''
    assert config.CONFIG['SEARCH_INDEED']['sort_by'] == 'date'
    assert config.CONFIG['SEARCH_INDEED']['pages_to_fetch'] == '5'
    print("  Default SEARCH_INDEED config: ✓")

    # Source should be registered
    sources = [s for s in config.CONFIG.sections() if 'Indeed' in s]
    assert len(sources) > 0, "No Indeed source section found"
    print(f"  Source section: {sources[0]} ✓")

    os.unlink('/tmp/test_indeed_config2.ini')
    print("  ✓ Config defaults OK\n")


if __name__ == '__main__':
    test_sanitise()
    test_html_parsing()
    test_json_parsing()
    test_combined_parser_prefers_json()
    test_total_results_html()
    test_url_construction()
    test_skip_non_job_links()
    test_config_defaults()
    print("All Indeed connector tests passed! ✓")