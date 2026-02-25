import requests
from bs4 import BeautifulSoup
from .jobitem import JobItem
from . import config
import logging
import time
import re
import json

logger = logging.getLogger(__name__)


def _sanitise(text):
    """Strip newlines, tabs, and control characters from scraped text."""
    if not text:
        return ''
    return re.sub(r'\s+', ' ', text).strip()


class IndeedConnector:
    """
    Connector for uk.indeed.com.

    Indeed embeds job card data as JSON inside a script variable:
        window.mosaic.providerData["mosaic-provider-jobcards"] = {...};

    We extract that JSON first; if unavailable, we fall back to HTML parsing.
    """

    connector_type = 'indeed'

    BASE_URL = 'https://uk.indeed.com'
    SEARCH_URL = 'https://uk.indeed.com/jobs'
    RESULTS_PER_PAGE = 15
    VIEW_URL = 'https://uk.indeed.com/viewjob'

    # Mobile endpoint is less aggressive with bot detection
    MOBILE_SEARCH_URL = 'https://uk.indeed.com/m/jobs'

    def __init__(self, name="Indeed UK"):
        self.name = name
        self.session = requests.Session()
        self._setup_session()
        self._cookies_primed = False

    def _setup_session(self):
        """Configure session with realistic browser headers."""
        self.session.headers.update({
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/131.0.0.0 Safari/537.36'
            ),
            'Accept': (
                'text/html,application/xhtml+xml,application/xml;'
                'q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8'
            ),
            'Accept-Language': 'en-GB,en-US;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Cache-Control': 'max-age=0',
            'Connection': 'keep-alive',
            'DNT': '1',
            'Sec-CH-UA': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            'Sec-CH-UA-Mobile': '?0',
            'Sec-CH-UA-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1',
        })

    def _prime_cookies(self):
        """Hit the homepage to pick up session cookies before searching.
        Indeed uses cookies for bot detection; without them requests get 403."""
        if self._cookies_primed:
            return
        try:
            resp = self.session.get(self.BASE_URL, timeout=15)
            logger.debug(f"Cookie prime: {resp.status_code}, "
                         f"cookies: {len(self.session.cookies)}")
            self._cookies_primed = True
            time.sleep(0.5)
        except requests.RequestException as e:
            logger.debug(f"Cookie prime failed: {e}")

    def _fetch_search_page(self, params):
        """Fetch a search page with fallback to mobile endpoint.

        Tries the desktop endpoint first. On 403, retries once via the
        mobile endpoint which tends to have lighter bot detection.
        """
        self._prime_cookies()

        # Update referer for subsequent searches
        self.session.headers['Referer'] = self.BASE_URL + '/'
        self.session.headers['Sec-Fetch-Site'] = 'same-origin'

        # Attempt 1: desktop
        try:
            response = self.session.get(
                self.SEARCH_URL, params=params, timeout=30)
            if response.status_code == 200:
                return response
            logger.debug(f"Desktop search returned {response.status_code}")
        except requests.RequestException as e:
            logger.debug(f"Desktop search failed: {e}")

        # Attempt 2: mobile endpoint (lighter bot detection)
        time.sleep(1)
        try:
            mobile_params = dict(params)
            response = self.session.get(
                self.MOBILE_SEARCH_URL, params=mobile_params, timeout=30)
            if response.status_code == 200:
                logger.info("Fell back to mobile endpoint successfully.")
                return response
            logger.debug(f"Mobile search returned {response.status_code}")
        except requests.RequestException as e:
            logger.debug(f"Mobile search failed: {e}")

        # Attempt 3: fresh session with mobile UA
        time.sleep(1)
        try:
            mobile_session = requests.Session()
            mobile_session.headers.update({
                'User-Agent': (
                    'Mozilla/5.0 (Linux; Android 14; Pixel 8) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/131.0.0.0 Mobile Safari/537.36'
                ),
                'Accept': 'text/html,application/xhtml+xml',
                'Accept-Language': 'en-GB,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
            })
            # Prime mobile session
            mobile_session.get(self.BASE_URL, timeout=15)
            time.sleep(0.5)

            response = mobile_session.get(
                self.MOBILE_SEARCH_URL, params=params, timeout=30)
            if response.status_code == 200:
                logger.info("Fell back to fresh mobile session successfully.")
                return response

            # If all attempts fail, raise with the last status
            response.raise_for_status()
        except requests.RequestException as e:
            raise requests.RequestException(
                f"All Indeed endpoints returned errors. "
                f"Last: {e}") from e

        return None

    def __str__(self):
        return self.name

    # ─── Config + URL building ───

    def _build_search_params(self, start=0, keyword_override=None):
        """Build query parameters from [SEARCH_INDEED] config."""
        search_cfg = (config.CONFIG['SEARCH_INDEED']
                      if 'SEARCH_INDEED' in config.CONFIG else {})

        params = {}

        keyword = (keyword_override if keyword_override is not None
                   else search_cfg.get('keyword', ''))
        if keyword:
            params['q'] = keyword

        location = search_cfg.get('location', '')
        if location:
            params['l'] = location

        radius = search_cfg.get('radius', '')
        if radius:
            params['radius'] = radius

        job_type = search_cfg.get('job_type', '')
        if job_type:
            params['jt'] = job_type

        fromage = search_cfg.get('max_days_old', '')
        if fromage:
            params['fromage'] = fromage

        sort = search_cfg.get('sort_by', 'date')
        if sort:
            params['sort'] = sort

        params['filter'] = '0'

        if start > 0:
            params['start'] = str(start)

        return params

    # ─── Pagination ───

    def _parse_total_results(self, html):
        """Extract total result count from the page."""
        # Try JSON metadata
        json_data = self._extract_json_data(html)
        if json_data:
            try:
                tiers = (json_data.get('metaData', {})
                         .get('mosaicProviderJobCardsModel', {})
                         .get('tierSummaries', []))
                if tiers:
                    return sum(t.get('jobCount', 0) for t in tiers)
            except (AttributeError, TypeError):
                pass

        # Fallback: HTML text
        soup = BeautifulSoup(html, 'html.parser')

        count_div = soup.find('div', class_=re.compile(r'jobCount', re.I))
        if count_div:
            match = re.search(r'([\d,]+)\s+jobs?', count_div.get_text())
            if match:
                return int(match.group(1).replace(',', ''))

        text = soup.get_text()
        match = re.search(r'of\s+([\d,]+)\s+jobs?', text, re.IGNORECASE)
        if match:
            return int(match.group(1).replace(',', ''))

        match = re.search(r'"searchCount"\s*:\s*(\d+)', html)
        if match:
            return int(match.group(1))

        return 0

    def _calc_total_pages(self, total_results):
        """Convert total results to page count (Indeed caps at ~1000)."""
        if total_results <= 0:
            return 1
        capped = min(total_results, 1000)
        return max(1, (capped + self.RESULTS_PER_PAGE - 1) // self.RESULTS_PER_PAGE)

    # ─── JSON extraction (preferred path) ───

    def _extract_json_data(self, html):
        """Extract embedded JSON from window.mosaic.providerData."""
        patterns = [
            r'window\.mosaic\.providerData\["mosaic-provider-jobcards"\]\s*=\s*(\{.+?\})\s*;',
            r"window\.mosaic\.providerData\['mosaic-provider-jobcards'\]\s*=\s*(\{.+?\})\s*;",
        ]
        for pat in patterns:
            match = re.search(pat, html, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    continue
        return None

    def _parse_jobs_from_json(self, json_data):
        """Parse job listings from Indeed's embedded JSON."""
        jobs = []
        try:
            results = (json_data['metaData']
                       ['mosaicProviderJobCardsModel']['results'])
        except (KeyError, TypeError):
            return jobs

        for r in results:
            job_key = r.get('jobkey', '')
            if not job_key:
                continue

            url = f"{self.VIEW_URL}?jk={job_key}"
            title = _sanitise(r.get('title', '') or r.get('displayTitle', ''))
            company = _sanitise(r.get('company', ''))
            location = _sanitise(
                r.get('formattedLocation', '') or r.get('jobLocationCity', ''))

            # Salary
            salary = ''
            sal_snippet = r.get('salarySnippet', {}) or {}
            if sal_snippet.get('text'):
                salary = _sanitise(sal_snippet['text'])
            elif r.get('extractedSalary'):
                es = r['extractedSalary']
                s_min, s_max = es.get('min'), es.get('max')
                s_type = es.get('type', '')
                if s_min and s_max:
                    if isinstance(s_min, (int, float)):
                        salary = f"\u00a3{s_min:,.0f} - \u00a3{s_max:,.0f}"
                    else:
                        salary = f"{s_min} - {s_max}"
                    if s_type:
                        salary += f" {s_type}"
                elif s_min:
                    salary = (f"\u00a3{s_min:,.0f}"
                              if isinstance(s_min, (int, float)) else str(s_min))

            date_posted = _sanitise(r.get('formattedRelativeDate', ''))

            job_types = r.get('jobTypes', [])
            contract_type = (', '.join(_sanitise(jt) for jt in job_types)
                             if job_types else '')

            snippet = ''
            if r.get('snippet'):
                snippet = _sanitise(
                    BeautifulSoup(r['snippet'], 'html.parser').get_text())

            job = JobItem(url=url)
            job.title = title
            job.employer = company
            job.location = location
            job.salary = salary
            job.date_posted = date_posted
            job.contract_type = contract_type
            job.description = snippet
            job.source = 'indeed'
            job.job_reference = job_key

            jobs.append(job)

        return jobs

    # ─── HTML fallback parsing ───

    def _parse_jobs_from_html(self, html):
        """Fallback: parse job cards from HTML.

        Job links contain a jk= parameter (the unique job key).
        We walk up the DOM from each link to find the containing card,
        then extract company, location, salary from siblings.
        """
        soup = BeautifulSoup(html, 'html.parser')
        jobs = []
        seen_keys = set()

        # Find all links containing jk= parameter
        links = soup.find_all('a', href=re.compile(r'[?&]jk='))

        for link in links:
            href = link.get('href', '')
            jk_match = re.search(r'[?&]jk=([a-zA-Z0-9]+)', href)
            if not jk_match:
                continue

            job_key = jk_match.group(1)
            if job_key in seen_keys:
                continue
            seen_keys.add(job_key)

            title = _sanitise(link.get_text())
            if not title or len(title) < 3:
                continue

            # Skip non-job links (salary search, view all, FAQ links)
            lower_title = title.lower()
            if any(skip in lower_title for skip in (
                    'salary search', 'view all', 'see popular', 'salaries in')):
                continue

            url = f"{self.VIEW_URL}?jk={job_key}"

            # Walk up to the containing card element (td, li, or .result div)
            card = link
            for _ in range(10):
                card = card.parent
                if card is None:
                    break
                tag = card.name or ''
                classes = ' '.join(card.get('class', []))
                if tag in ('td', 'li') or 'result' in classes:
                    break

            company = ''
            location = ''
            salary = ''
            snippet = ''
            date_posted = ''

            if card and card.name:
                # Company
                co_el = card.find(class_=re.compile(r'companyName|company', re.I))
                if co_el:
                    company = _sanitise(co_el.get_text())

                # Location
                loc_el = card.find(class_=re.compile(
                    r'companyLocation|location', re.I))
                if loc_el:
                    location = _sanitise(loc_el.get_text())

                # Salary
                sal_el = card.find(class_=re.compile(
                    r'salary-snippet|salaryText|salary', re.I))
                if sal_el:
                    salary = _sanitise(sal_el.get_text())

                # Snippet
                snip_el = card.find(class_=re.compile(r'job-snippet', re.I))
                if snip_el:
                    snippet = _sanitise(snip_el.get_text())

                # Date
                date_el = card.find('span', class_=re.compile(r'date', re.I))
                if date_el:
                    date_posted = _sanitise(date_el.get_text())

            job = JobItem(url=url)
            job.title = title
            job.employer = company
            job.location = location
            job.salary = salary
            job.date_posted = date_posted
            job.description = snippet
            job.source = 'indeed'
            job.job_reference = job_key

            jobs.append(job)

        return jobs

    # ─── Combined parser ───

    def _parse_search_page(self, html):
        """Parse a search results page — JSON first, then HTML fallback."""
        json_data = self._extract_json_data(html)
        if json_data:
            jobs = self._parse_jobs_from_json(json_data)
            if jobs:
                return jobs

        return self._parse_jobs_from_html(html)

    # ─── Fetching ───

    def get_all_items(self, keyword_override=None, max_pages=None):
        """Fetch job listings from Indeed UK search.

        Args:
            keyword_override: Use this keyword instead of config.
            max_pages: Override config pages_to_fetch. 0 = auto-detect all.
        """
        if max_pages is None:
            max_pages = int(config.CONFIG.get(
                'SEARCH_INDEED', 'pages_to_fetch', fallback='5'))

        auto_pages = (max_pages == 0)

        all_jobs = []
        seen_keys = set()
        keyword_label = (keyword_override or
                         config.CONFIG.get('SEARCH_INDEED', 'keyword',
                                           fallback='(all)'))
        print(f"Fetching Indeed UK listings for '{keyword_label}'...")

        page_num = 0
        pages_limit = max_pages if not auto_pages else 999

        while page_num < pages_limit:
            start_offset = page_num * self.RESULTS_PER_PAGE
            params = self._build_search_params(
                start=start_offset, keyword_override=keyword_override)

            try:
                response = self._fetch_search_page(params)
                if response is None:
                    print(f"  No response for page {page_num + 1}.")
                    break
            except requests.RequestException as e:
                logger.warning(f"Failed to fetch page {page_num + 1}: {e}")
                print(f"  Failed page {page_num + 1}: {e}")
                break

            if page_num == 0 and auto_pages:
                total_results = self._parse_total_results(response.text)
                total_pages = self._calc_total_pages(total_results)
                pages_limit = total_pages
                print(f"  Detected ~{total_results} results "
                      f"({total_pages} page(s)).")

            jobs = self._parse_search_page(response.text)
            if not jobs:
                print(f"  No more results at page {page_num + 1}.")
                break

            new_on_page = 0
            for job in jobs:
                key = job.job_reference or job.url
                if key not in seen_keys:
                    seen_keys.add(key)
                    all_jobs.append(job)
                    new_on_page += 1

            page_num += 1
            print(f"  Page {page_num}: {new_on_page} jobs "
                  f"(total: {len(all_jobs)})")

            # Indeed rate-limits aggressively
            if page_num < pages_limit:
                time.sleep(1.0)

        print(f"Fetched {len(all_jobs)} jobs from Indeed UK.")
        return all_jobs

    def get_all_items_multi(self, max_pages=None):
        """Fetch jobs for all configured keywords (comma-separated).

        Reads from [SEARCH_INDEED] keyword config.
        Returns deduplicated list of JobItems.
        """
        raw = config.CONFIG.get('SEARCH_INDEED', 'keyword', fallback='')
        keywords = [k.strip() for k in raw.split(',') if k.strip()]

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

        print(f"Total unique Indeed jobs across {len(keywords)} "
              f"keywords: {len(all_jobs)}")
        return all_jobs

    # ─── Detail page (for prompt generator) ───

    def fetch_job_detail(self, url):
        """Fetch full job description from a /viewjob page."""
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch job detail: {e}")
            return ''

        soup = BeautifulSoup(response.text, 'html.parser')

        # Primary: id="jobDescriptionText"
        jd_div = soup.find('div', id='jobDescriptionText')
        if jd_div:
            return _sanitise(jd_div.get_text(separator='\n'))

        # Fallback selectors
        for selector in [
            'div.jobsearch-jobDescriptionText',
            'div[class*="jobDescription"]',
        ]:
            el = soup.select_one(selector)
            if el:
                return _sanitise(el.get_text(separator='\n'))

        # JSON-LD
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                ld = json.loads(script.string)
                if isinstance(ld, dict) and ld.get('description'):
                    return _sanitise(
                        BeautifulSoup(
                            ld['description'], 'html.parser').get_text())
            except (json.JSONDecodeError, TypeError):
                pass

        return ''