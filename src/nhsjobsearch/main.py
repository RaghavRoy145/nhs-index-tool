from .nhsconnector import NHSJobsConnector
from .dwpconnector import DWPJobsConnector
from optparse import OptionParser
from . import config, database, display
import os


CONNECTOR_MAP = {
    'nhs': NHSJobsConnector,
    'dwp': DWPJobsConnector,
}


def get_opts():
    parse = OptionParser(
        usage="usage: %prog [options]",
        description="NHS & DWP Job Search Tool"
    )
    parse.add_option("--config", help="Configuration file",
                     default="~/.config/nhs-job-search/config.ini")
    parse.add_option("--reindex", help="Force re-indexing from all sources",
                     action="store_true", default=False)
    parse.add_option("--reindex-nhs", help="Re-index NHS Jobs only",
                     action="store_true", default=False)
    parse.add_option("--reindex-dwp", help="Re-index DWP Find a Job only",
                     action="store_true", default=False)
    parse.add_option("--purge", help="Remove expired job listings",
                     action="store_true", default=False)
    parse.add_option("--stats", help="Show index statistics",
                     action="store_true", default=False)
    parse.add_option("--cron-install", help="Install cron job (default: every 6h)",
                     action="store_true", default=False)
    parse.add_option("--cron-uninstall", help="Remove cron job",
                     action="store_true", default=False)
    parse.add_option("--cron-interval", help="Cron interval in hours (default: 6)",
                     default=6, type='int')
    parse.add_option("--pending", help="Show pending new-job notifications",
                     action="store_true", default=False)
    parse.add_option("-v", help="Verbose output", default=False,
                     dest='verbose', action="store_true")

    # Quick search from CLI without opening TUI
    parse.add_option("-s", "--search", help="Quick search (prints results to stdout)",
                     dest='search_query', default=None)
    parse.add_option("-n", "--num-results", help="Number of results for quick search",
                     dest='num_results', default=10, type='int')
    parse.add_option("-l", "--location", help="Filter by location",
                     dest='location', default=None)
    parse.add_option("--prompt", help="Launch interactive prompt generator (no job pre-selected)",
                     action="store_true", default=False)

    # WhatsApp bot
    parse.add_option("--bot", help="Start WhatsApp notification bot",
                     action="store_true", default=False)
    parse.add_option("--bot-test", help="Send a test WhatsApp message",
                     action="store_true", default=False)
    parse.add_option("--bot-digest", help="Force send morning digest now",
                     action="store_true", default=False)

    return parse.parse_args()


def fetch_and_index(db_path, connector):
    """Fetch items from a connector and index them.
    Uses multi-keyword search if comma-separated keywords are configured."""
    print(f"Fetching items from {connector.name}...")
    items = connector.get_all_items_multi()
    database.index_jobs(items, db_path)


def reindex_source(db_path, source_type, source_config):
    """Index a single source."""
    connector_cls = CONNECTOR_MAP.get(source_type)
    if not connector_cls:
        print(f"Unknown source type '{source_type}'. Skipping.")
        return

    connector_name = source_config.get('name', source_type.upper())
    connector = connector_cls(name=connector_name)

    try:
        fetch_and_index(db_path, connector)
    except Exception as e:
        print(f"Failed to process {connector_name}: {e}")


def reindex_all(db_path):
    """Loop through all configured sources and index them."""
    source_sections = [s for s in config.CONFIG.sections() if s.startswith('SOURCE')]
    if not source_sections:
        print("No [SOURCE:...] sections found in config.")
        return

    for section in source_sections:
        source_type = config.CONFIG.get(section, 'type', fallback='').lower()
        source_url = config.CONFIG.get(section, 'url', fallback='')
        if not source_url:
            print(f"Skipping {section}: No URL defined.")
            continue

        print(f"\nProcessing {section} (Type: {source_type})...")
        reindex_source(db_path, source_type, dict(config.CONFIG[section]))

    print("\nIndexing complete.")


def quick_search(db_path, query, location=None, num_results=10):
    """CLI search that prints results to stdout."""
    jobs = database.search_jobs(db_path, keyword=query, location=location, limit=num_results)

    if not jobs:
        print(f"No jobs found matching '{query}'.")
        return

    print(f"\n{'#':<4} {'Source':<6} {'Posted':<10} {'Title':<40} {'Employer':<25} {'Location'}")
    print("─" * 110)

    for i, job in enumerate(jobs, 1):
        title = job.title[:38] + '..' if len(job.title) > 40 else job.title
        employer = job.employer[:23] + '..' if len(job.employer) > 25 else job.employer
        location = job.location[:20] if job.location else ''

        print(f"{i:<4} {job.source.upper():<6} {job.age:<10} {title:<40} {employer:<25} {location}")

    print(f"\n{len(jobs)} results. Use the TUI (run without -s) for interactive browsing.")


def show_stats(db_path):
    """Print index statistics."""
    total = database.get_job_count(db_path)
    nhs = database.get_job_count(db_path, source='nhs')
    dwp = database.get_job_count(db_path, source='dwp')

    print(f"Job Index Statistics:")
    print(f"  Total jobs:    {total}")
    print(f"  NHS Jobs:      {nhs}")
    print(f"  DWP Find a Job:{dwp}")


def run_tool():
    opts, args = get_opts()
    config_path = os.path.expanduser(opts.config)
    config.init_config(config_path)

    if opts.verbose:
        config.VERBOSE = True

    db_path = config.db_path()

    # Handle purge
    if opts.purge:
        database.purge_expired(db_path)
        return

    # Handle cron management
    if opts.cron_install:
        from .cron_reindex import install_cron
        install_cron(config_path, opts.cron_interval)
        return

    if opts.cron_uninstall:
        from .cron_reindex import uninstall_cron
        uninstall_cron()
        return

    if opts.pending:
        from .cron_reindex import show_pending
        show_pending()
        return

    # Handle stats
    if opts.stats:
        show_stats(db_path)
        return

    # Handle reindexing
    needs_reindex = False

    if opts.reindex:
        if os.path.exists(db_path):
            print("Force re-index requested. Cleaning old database...")
            os.unlink(db_path)
        reindex_all(db_path)
        needs_reindex = True

    elif opts.reindex_nhs:
        for section in config.CONFIG.sections():
            if section.startswith('SOURCE') and config.CONFIG.get(section, 'type', fallback='') == 'nhs':
                reindex_source(db_path, 'nhs', dict(config.CONFIG[section]))
        needs_reindex = True

    elif opts.reindex_dwp:
        for section in config.CONFIG.sections():
            if section.startswith('SOURCE') and config.CONFIG.get(section, 'type', fallback='') == 'dwp':
                reindex_source(db_path, 'dwp', dict(config.CONFIG[section]))
        needs_reindex = True

    # Auto-index if DB doesn't exist
    if not os.path.exists(db_path):
        print("No index found. Running first-time indexing...")
        reindex_all(db_path)
        needs_reindex = True

    # Quick search mode
    if opts.search_query:
        quick_search(db_path, opts.search_query, opts.location, opts.num_results)
        return

    # WhatsApp bot commands
    if opts.bot:
        from .whatsappbot import run_bot
        run_bot(config_path)
        return

    if opts.bot_test:
        from .whatsappbot import send_test_message
        send_test_message(config_path)
        return

    if opts.bot_digest:
        from .whatsappbot import send_digest_now
        send_digest_now(config_path)
        return

    # Standalone prompt generator (no job pre-selected)
    if opts.prompt:
        from .promptgen import run_prompt_generator
        run_prompt_generator()
        return

    # Interactive TUI
    if not (opts.reindex or opts.reindex_nhs or opts.reindex_dwp):
        display.show_display(db_path)


if __name__ == '__main__':
    run_tool()