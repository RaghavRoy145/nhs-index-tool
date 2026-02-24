from configparser import ConfigParser
import os
from os import path

# Default source configurations
SOURCES = {
    'NHSJobs': {
        'type': 'nhs',
        'url': 'https://www.jobs.nhs.uk/candidate/search/results',
        'name': 'NHS Jobs',
    },
    'DWPFindAJob': {
        'type': 'dwp',
        'url': 'https://findajob.dwp.gov.uk/search',
        'name': 'Find a Job',
    },
    'IndeedUK': {
        'type': 'indeed',
        'url': 'https://uk.indeed.com/jobs',
        'name': 'Indeed UK',
    },
}

CONFIG = ConfigParser()
CONFIG_PATH = None
VERBOSE = False


def check_value(section, key, value):
    """Check that a section and key exist, otherwise set defaults."""
    if section not in CONFIG:
        CONFIG.add_section(section)
    if key not in CONFIG[section]:
        CONFIG[section][key] = value


def verify_defaults():
    """Ensure minimal configuration exists."""
    check_value('CACHE', 'path', '~/.cache/nhs-job-search/')
    check_value('LOG', 'verbose', 'False')
    check_value('DISPLAY', 'max_results_per_page', '50')

    # Search defaults — these are the configurable query parameters
    check_value('SEARCH', 'keyword', '')
    check_value('SEARCH', 'location', '')
    check_value('SEARCH', 'distance', '')
    check_value('SEARCH', 'contract_type', '')
    check_value('SEARCH', 'working_pattern', '')
    check_value('SEARCH', 'staff_group', '')
    check_value('SEARCH', 'pay_min', '')
    check_value('SEARCH', 'pay_max', '')
    check_value('SEARCH', 'pages_to_fetch', '5')
    check_value('SEARCH', 'sort_by', 'Date Posted (newest)')

    # DWP-specific search defaults
    check_value('SEARCH_DWP', 'keyword', '')
    check_value('SEARCH_DWP', 'location', '')
    check_value('SEARCH_DWP', 'category', '12')   # 12 = Healthcare & Nursing
    check_value('SEARCH_DWP', 'loc_code', '86383')  # UK-wide
    check_value('SEARCH_DWP', 'contract_type', '')
    check_value('SEARCH_DWP', 'hours', '')
    check_value('SEARCH_DWP', 'posting_days', '')
    check_value('SEARCH_DWP', 'remote', '')
    check_value('SEARCH_DWP', 'pages_to_fetch', '5')
    check_value('SEARCH_DWP', 'sort_by', 'Most recent')

    # Indeed UK search defaults
    check_value('SEARCH_INDEED', 'keyword', '')
    check_value('SEARCH_INDEED', 'location', '')
    check_value('SEARCH_INDEED', 'radius', '')        # miles from location
    check_value('SEARCH_INDEED', 'job_type', '')       # fulltime / parttime / contract / temporary
    check_value('SEARCH_INDEED', 'max_days_old', '')   # 1, 3, 7, 14 — only show jobs posted within N days
    check_value('SEARCH_INDEED', 'sort_by', 'date')    # date / relevance
    check_value('SEARCH_INDEED', 'pages_to_fetch', '5')

    if not any(s for s in CONFIG.sections() if s.startswith('SOURCE')):
        for k, v in SOURCES.items():
            CONFIG['SOURCE:' + k] = v

    global VERBOSE
    VERBOSE = CONFIG.getboolean('LOG', 'verbose', fallback=False)


def init_config(in_path):
    """Initialize configuration from file, creating defaults if needed."""
    global CONFIG_PATH
    config_path = path.abspath(path.expanduser(in_path))
    CONFIG_PATH = config_path
    os.makedirs(path.dirname(config_path), exist_ok=True)
    CONFIG.read(config_path)
    verify_defaults()
    with open(config_path, 'w') as configfile:
        CONFIG.write(configfile)


def db_path():
    """Return the database file path."""
    cache_dir = path.expanduser(CONFIG["CACHE"]["path"])
    os.makedirs(cache_dir, exist_ok=True)
    return path.join(cache_dir, "jobs.db")