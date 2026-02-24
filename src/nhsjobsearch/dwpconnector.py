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
    return re.sub(r'\s+', ' ', text).strip()


class DWPJobsConnector:
    """
    Connector for findajob.dwp.gov.uk.
    Scrapes the HTML search results pages.
    """

    connector_type = 'dwp'

    BASE_URL = 'https://findajob.dwp.gov.uk'
    SEARCH_URL = 'https://findajob.dwp.gov.uk/search'

    def __init__(self, name="Find a Job"):
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
        search_cfg = config.CONFIG['SEARCH_DWP'] if 'SEARCH_DWP' in config.CONFIG else {}

        params = {}

        keyword = keyword_override if keyword_override is not None else search_cfg.get('keyword', '')
        if keyword:
            params['q'] = keyword

        location = search_cfg.get('location', '')
        if location:
            params['w'] = location

        category = search_cfg.get('category', '12')
        if category:
            params['cat'] = category

        loc_code = search_cfg.get('loc_code', '86383')
        if loc_code:
            params['loc'] = loc_code

        contract_type = search_cfg.get('contract_type', '')
        if contract_type:
            params['cty'] = contract_type

        hours = search_cfg.get('hours', '')
        if hours:
            params['cti'] = hours

        posting_days = search_cfg.get('posting_days', '')
        if posting_days:
            params['f'] = posting_days

        remote = search_cfg.get('remote', '')
        if remote:
            params['remote'] = remote

        # Sort mapping
        sort_map = {
            'Most recent': '',
            'Most relevant': 'relevance',
            'Highest salary': 'salary_desc',
            'Lowest salary': 'salary_asc',
        }
        sort_by = search_cfg.get('sort_by', 'Most recent')
        sort_val = sort_map.get(sort_by, '')
        if sort_val:
            params['sb'] = sort_val

        if page > 1:
            params['p'] = str(page)

        return params

    def _parse_total_pages(self, html):
        """Extract total page count from DWP search results HTML.

        DWP uses pagination links like ?p=N or shows "Page X of Y".
        """
        soup = BeautifulSoup(html, 'html.parser')

        max_page = 1
        for a in soup.select('nav a, .pagination a, a[href*="p="]'):
            href = a.get('href', '')
            match = re.search(r'[?&]p=(\d+)', href)
            if match:
                max_page = max(max_page, int(match.group(1)))
            text = a.get_text(strip=True)
            if text.isdigit():
                max_page = max(max_page, int(text))

        # Fallback: "of N" text
        text = soup.get_text()
        for match in re.finditer(r'(?:of|\/)\s*(\d+)\s*(?:pages?)?', text, re.IGNORECASE):
            try:
                n = int(match.group(1))
                if 2 <= n <= 500:
                    max_page = max(max_page, n)
            except ValueError:
                pass

        return max_page

    def get_all_items(self, keyword_override=None, max_pages=None):
        """Fetch job listings from DWP Find a Job search results pages.

        Args:
            keyword_override: If set, use this keyword instead of config.
            max_pages: If set, override config pages_to_fetch.
                       0 means auto-detect all pages.
        """
        if max_pages is None:
            max_pages = int(config.CONFIG.get('SEARCH_DWP', 'pages_to_fetch', fallback='5'))

        auto_pages = (max_pages == 0)

        all_jobs = []
        keyword_label = keyword_override or config.CONFIG.get('SEARCH_DWP', 'keyword', fallback='(all)')
        print(f"Fetching DWP Find a Job listings for '{keyword_label}'...")

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

            if page_num < pages_limit:
                time.sleep(0.5)

        print(f"Fetched {len(all_jobs)} jobs from DWP Find a Job.")
        return all_jobs

    def get_all_items_multi(self, max_pages=None):
        """Fetch jobs for all configured keywords (comma-separated).

        Returns deduplicated list of JobItems.
        """
        raw_keywords = config.CONFIG.get('SEARCH_DWP', 'keyword', fallback='')
        keywords = [k.strip() for k in raw_keywords.split(',') if k.strip()]

        if len(keywords) <= 1:
            return self.get_all_items(max_pages=max_pages)

        all_jobs = []
        seen_urls = set()

        for kw in keywords:
            jobs = self.get_all_items(keyword_override=kw, max_pages=max_pages)
            for job in jobs:
                if job.url not in seen_urls:
                    seen_urls.add(job.url)
                    all_jobs.append(job)

        print(f"Total unique DWP jobs across {len(keywords)} keywords: {len(all_jobs)}")
        return all_jobs

    def _parse_search_page(self, html):
        """Parse a single DWP search results page into JobItem objects."""
        soup = BeautifulSoup(html, 'html.parser')
        jobs = []

        for h3 in soup.select('h3'):
            link = h3.select_one('a')
            if not link:
                continue

            href = link.get('href', '')
            if '/details/' not in href:
                continue

            title = _sanitise(link.get_text(strip=True))
            url = self.BASE_URL + href if href.startswith('/') else href

            # Get the sibling <ul> which has the metadata
            ul = h3.find_next_sibling('ul')
            if not ul:
                continue

            li_items = ul.select('li')

            date_posted = ''
            employer = ''
            location = ''
            salary = ''
            contract_type = ''
            working_pattern = ''
            remote_status = ''

            for li in li_items:
                text = _sanitise(li.get_text(strip=True))

                # Date is usually first and looks like "22 February 2026"
                if re.match(r'\d{1,2}\s+\w+\s+\d{4}', text):
                    date_posted = text
                    continue

                # Employer + location: "<strong>Company</strong> - Location, Postcode"
                strong = li.select_one('strong')
                if strong:
                    strong_text = _sanitise(strong.get_text(strip=True))

                    # Check if this is a salary line
                    if '£' in strong_text or 'Negotiable' in strong_text or 'Competitive' in strong_text:
                        salary = strong_text
                        continue

                    # Check if this is employer - location
                    remainder = text.replace(strong_text, '', 1).strip()
                    if remainder.startswith('- ') or remainder.startswith('– '):
                        employer = strong_text
                        location = remainder.lstrip('-–— ').strip()
                        continue
                    elif not employer:
                        employer = strong_text
                        continue

                # Contract type
                if text.lower() in ('permanent', 'contract', 'temporary', 'apprenticeship'):
                    contract_type = text
                    continue

                # Hours
                if text.lower() in ('full time', 'part time'):
                    working_pattern = text
                    continue

                # Remote status
                if text.lower() in ('on-site only', 'hybrid remote', 'fully remote'):
                    remote_status = text
                    continue

                # Salary without strong tag
                if '£' in text and not salary:
                    salary = _sanitise(text)
                    continue

            # Description snippet
            desc_p = ul.find_next_sibling('p') if ul else None
            description = _sanitise(desc_p.get_text(strip=True)) if desc_p else ''

            # Extract job ID from URL
            job_ref = href.split('/')[-1] if href else ''

            job = JobItem(
                url=url,
                title=title,
                employer=employer,
                location=location,
                salary=salary,
                date_posted=date_posted,
                closing_date='',
                contract_type=contract_type,
                working_pattern=working_pattern,
                description=description,
                job_reference=job_ref,
                source='dwp',
            )
            jobs.append(job)

        return jobs

    def get_job_detail(self, job_url):
        """Fetch the full job detail page and extract the complete description."""
        try:
            response = self.session.get(job_url, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch job detail: {e}")
            return None

        return self._parse_job_detail(response.text, job_url)

    def _parse_job_detail(self, html, url):
        """Parse a full DWP job detail page."""
        soup = BeautifulSoup(html, 'html.parser')

        title_el = soup.select_one('h1')
        title = _sanitise(title_el.get_text(strip=True)) if title_el else ''

        # Metadata table
        metadata = {}
        table = soup.select_one('table')
        if table:
            for row in table.select('tr'):
                cells = row.select('td')
                if len(cells) == 2:
                    key = _sanitise(cells[0].get_text(strip=True)).rstrip(':')
                    value = _sanitise(cells[1].get_text(strip=True))
                    metadata[key] = value

        # Summary/description section
        summary = ''
        summary_header = soup.find('h2', string=re.compile(r'Summary', re.IGNORECASE))
        if summary_header:
            parts = []
            for sibling in summary_header.find_next_siblings():
                if sibling.name == 'h2':
                    break
                parts.append(sibling.get_text('\n', strip=True))
            summary = '\n'.join(parts)

        if not summary:
            main = soup.select_one('main, #main')
            if main:
                summary = main.get_text('\n', strip=True)

        closing_date = metadata.get('Closing date', '')

        return {
            'title': title,
            'description': summary,
            'metadata': metadata,
            'closing_date': closing_date,
            'url': url,
            'full_html': html,
        }