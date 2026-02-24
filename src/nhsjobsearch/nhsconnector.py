import requests
from bs4 import BeautifulSoup
from .jobitem import JobItem
from . import config
import logging
import time
import re

logger = logging.getLogger(__name__)


def _sanitise(text):
    """Strip newlines, tabs, and control characters from scraped text.
    Collapses whitespace to single spaces."""
    if not text:
        return ''
    # Replace any whitespace sequence (including \n \r \t) with a single space
    return re.sub(r'\s+', ' ', text).strip()


class NHSJobsConnector:
    """
    Connector for jobs.nhs.uk.
    Scrapes the HTML search results pages.
    """

    connector_type = 'nhs'

    BASE_URL = 'https://www.jobs.nhs.uk'
    SEARCH_URL = 'https://www.jobs.nhs.uk/candidate/search/results'
    JOB_DETAIL_URL = 'https://www.jobs.nhs.uk/candidate/jobadvert'

    def __init__(self, name="NHS Jobs"):
        self.name = name
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'NHSJobSearch/1.0',
            'Accept': 'text/html,application/xhtml+xml',
        })

    def __str__(self):
        return self.name

    def _build_search_params(self, page=1, keyword_override=None):
        """Build query parameters from config.
        If keyword_override is provided, it replaces the config keyword."""
        search_cfg = config.CONFIG['SEARCH'] if 'SEARCH' in config.CONFIG else {}

        params = {'page': str(page)}

        keyword = keyword_override if keyword_override is not None else search_cfg.get('keyword', '')
        if keyword:
            params['keyword'] = keyword

        location = search_cfg.get('location', '')
        if location:
            params['location'] = location

        distance = search_cfg.get('distance', '')
        if distance:
            params['distance'] = distance

        # Contract type
        contract_type = search_cfg.get('contract_type', '')
        if contract_type:
            for ct in contract_type.split(','):
                ct = ct.strip()
                if ct:
                    params.setdefault('contractType', []).append(ct) if isinstance(params.get('contractType'), list) else params.update({'contractType': ct})

        # Working pattern
        working_pattern = search_cfg.get('working_pattern', '')
        if working_pattern:
            for wp in working_pattern.split(','):
                wp = wp.strip()
                if wp:
                    params.setdefault('workingPattern', []).append(wp) if isinstance(params.get('workingPattern'), list) else params.update({'workingPattern': wp})

        # Staff group
        staff_group = search_cfg.get('staff_group', '')
        if staff_group:
            params['staffGroup'] = staff_group

        return params

    def _parse_total_pages(self, html):
        """Extract the total number of result pages from the search page HTML.

        NHS Jobs typically has pagination with links like:
            <nav><ul><li><a href="...?page=N">N</a></li>...</ul></nav>
        or a results count like "Showing 1 to 20 of 347"
        """
        soup = BeautifulSoup(html, 'html.parser')

        # Strategy 1: Look for pagination links — highest page number
        max_page = 1
        for a in soup.select('nav a, .pagination a, a[href*="page="]'):
            href = a.get('href', '')
            match = re.search(r'[?&]page=(\d+)', href)
            if match:
                max_page = max(max_page, int(match.group(1)))
            # Also check the link text itself (might just be a number)
            text = a.get_text(strip=True)
            if text.isdigit():
                max_page = max(max_page, int(text))

        # Strategy 2: Look for "X of Y" or "Page X of Y" text
        text = soup.get_text()
        for match in re.finditer(r'(?:of|\/)\s*(\d+)\s*(?:pages?|results?)?', text, re.IGNORECASE):
            try:
                n = int(match.group(1))
                # Reasonable page count (not a salary or other number)
                if 2 <= n <= 500:
                    max_page = max(max_page, n)
            except ValueError:
                pass

        return max_page

    def get_all_items(self, keyword_override=None, max_pages=None):
        """Fetch job listings from NHS Jobs search results pages.

        Args:
            keyword_override: If set, use this keyword instead of config.
            max_pages: If set, override config pages_to_fetch.
                       0 means auto-detect all pages.
        """
        if max_pages is None:
            max_pages = int(config.CONFIG.get('SEARCH', 'pages_to_fetch', fallback='5'))

        auto_pages = (max_pages == 0)

        all_jobs = []
        keyword_label = keyword_override or config.CONFIG.get('SEARCH', 'keyword', fallback='(all)')
        print(f"Fetching NHS Jobs listings for '{keyword_label}'...")

        page_num = 0
        pages_limit = max_pages if not auto_pages else 999

        while page_num < pages_limit:
            page_num += 1
            params = self._build_search_params(page=page_num, keyword_override=keyword_override)

            try:
                response = self.session.get(self.SEARCH_URL, params=params, timeout=30)
                response.raise_for_status()
            except requests.RequestException as e:
                logger.warning(f"Failed to fetch page {page_num}: {e}")
                print(f"  Failed page {page_num}: {e}")
                break

            # Auto-detect total pages from first response
            if page_num == 1 and auto_pages:
                total_pages = self._parse_total_pages(response.text)
                pages_limit = total_pages
                print(f"  Detected {total_pages} page(s) of results.")

            jobs = self._parse_search_page(response.text)
            if not jobs:
                print(f"  No more results at page {page_num}.")
                break

            all_jobs.extend(jobs)
            print(f"  Page {page_num}: {len(jobs)} jobs (total: {len(all_jobs)})")

            # Be polite
            if page_num < pages_limit:
                time.sleep(0.5)

        print(f"Fetched {len(all_jobs)} jobs from NHS Jobs.")
        return all_jobs

    def get_all_items_multi(self, max_pages=None):
        """Fetch jobs for all configured keywords (comma-separated).

        Returns deduplicated list of JobItems.
        """
        raw_keywords = config.CONFIG.get('SEARCH', 'keyword', fallback='')
        keywords = [k.strip() for k in raw_keywords.split(',') if k.strip()]

        if len(keywords) <= 1:
            # Single keyword or empty — use normal path
            return self.get_all_items(max_pages=max_pages)

        all_jobs = []
        seen_urls = set()

        for kw in keywords:
            jobs = self.get_all_items(keyword_override=kw, max_pages=max_pages)
            for job in jobs:
                if job.url not in seen_urls:
                    seen_urls.add(job.url)
                    all_jobs.append(job)

        print(f"Total unique NHS jobs across {len(keywords)} keywords: {len(all_jobs)}")
        return all_jobs

    def _parse_search_page(self, html):
        """Parse a single search results page into JobItem objects."""
        soup = BeautifulSoup(html, 'html.parser')
        jobs = []

        listings = soup.select('li')

        for li in listings:
            title_link = li.select_one('h2 > a')
            if not title_link:
                continue

            href = title_link.get('href', '')
            if '/candidate/jobadvert/' not in href:
                continue

            title = _sanitise(title_link.get_text(strip=True))
            url = self.BASE_URL + href if href.startswith('/') else href

            # Parse the employer and location from h3
            employer_location = li.select_one('h3')
            employer = ''
            location = ''

            # Parse metadata from the structured list items
            salary = ''
            date_posted = ''
            closing_date = ''
            contract_type = ''
            working_pattern = ''

            meta_items = li.select('li')
            for meta in meta_items:
                text = _sanitise(meta.get_text(strip=True))
                if text.startswith('Salary:'):
                    salary = text.replace('Salary:', '').strip()
                elif text.startswith('Date posted:'):
                    date_posted = text.replace('Date posted:', '').strip()
                elif text.startswith('Closing date:'):
                    closing_date = text.replace('Closing date:', '').strip()
                elif text.startswith('Contract type:'):
                    contract_type = text.replace('Contract type:', '').strip()
                elif text.startswith('Working pattern:'):
                    working_pattern = text.replace('Working pattern:', '').strip()

            # Extract the employer and location more carefully
            if employer_location:
                full_text = _sanitise(employer_location.get_text(' ', strip=True))
                postcode_match = re.search(r'([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\s*$', full_text)
                if postcode_match:
                    location = postcode_match.group(0).strip()
                    employer = full_text[:postcode_match.start()].strip()
                else:
                    employer = full_text

            # Extract job reference from URL
            job_ref = href.split('/')[-1].split('?')[0] if href else ''

            job = JobItem(
                url=url,
                title=title,
                employer=employer,
                location=location,
                salary=salary,
                date_posted=date_posted,
                closing_date=closing_date,
                contract_type=contract_type,
                working_pattern=working_pattern,
                job_reference=job_ref,
                source='nhs',
            )
            jobs.append(job)

        return jobs

    def get_job_detail(self, url):
        """Fetch the full job advert page and extract the description."""
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch job detail: {e}")
            return None

        return self._parse_job_detail(response.text, url)

    def _parse_job_detail(self, html, url):
        """Parse the job advert detail page."""
        soup = BeautifulSoup(html, 'html.parser')

        title_el = soup.select_one('h1')
        title = _sanitise(title_el.get_text(strip=True)) if title_el else ''

        # Main description
        description_parts = []

        for selector in ['#job_overview', '.job-overview', '.vacancy-details',
                         '#job_description', '.description', 'main']:
            container = soup.select_one(selector)
            if container:
                description_parts.append(container.get_text('\n', strip=True))
                break

        if not description_parts:
            main = soup.select_one('main') or soup.select_one('body')
            if main:
                description_parts.append(main.get_text('\n', strip=True))

        description = '\n'.join(description_parts)

        return {
            'title': title,
            'url': url,
            'description': description,
            'html': html,
        }