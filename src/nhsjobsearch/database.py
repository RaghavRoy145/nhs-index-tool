import sqlite3
import os
from .jobitem import JobItem


def init_db(db_path: str):
    """Create the DB file and ensure the jobs table exists."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs(
            url TEXT PRIMARY KEY,
            title TEXT,
            employer TEXT,
            location TEXT,
            salary TEXT,
            date_posted TEXT,
            closing_date TEXT,
            contract_type TEXT,
            working_pattern TEXT,
            description TEXT,
            job_reference TEXT,
            source TEXT,
            staff_group TEXT,
            indexed_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    return conn


def index_jobs(jobs, db_path):
    """Save a list of JobItem objects into the database. Returns count indexed."""
    _, _ , _ = index_jobs_with_diff(jobs, db_path)
    return len(jobs)


def index_jobs_with_diff(jobs, db_path):
    """
    Save jobs and return (new_jobs, updated_jobs, total_indexed).

    Compares incoming URLs against what's already in the DB to determine
    which listings are genuinely new. This is the key hook for push
    notifications — the caller gets back the JobItem list of *new* jobs.
    """
    conn = init_db(db_path)
    cur = conn.cursor()

    # Snapshot existing URLs for this diff
    cur.execute("SELECT url FROM jobs")
    existing_urls = {row[0] for row in cur.fetchall()}

    new_jobs = []
    updated_jobs = []

    rows = []
    for job in jobs:
        row = (
            job.url,
            job.title,
            job.employer,
            job.location,
            job.salary,
            job.date_posted,
            job.closing_date,
            job.contract_type,
            job.working_pattern,
            job.description,
            job.job_reference,
            job.source,
            job.staff_group,
        )
        rows.append(row)

        if job.url not in existing_urls:
            new_jobs.append(job)
        else:
            updated_jobs.append(job)

    cur.executemany(
        """
        INSERT OR REPLACE INTO jobs(
            url, title, employer, location, salary,
            date_posted, closing_date, contract_type, working_pattern,
            description, job_reference, source, staff_group)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        rows
    )

    conn.commit()
    conn.close()
    print(f"Indexed {len(rows)} jobs ({len(new_jobs)} new, {len(updated_jobs)} updated)")
    return new_jobs, updated_jobs, len(rows)


def get_all_jobs(db_path, source=None):
    """
    Fetch all jobs from the database and return as JobItem objects.
    Optionally filter by source ('nhs' or 'dwp').
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if source:
        cur.execute("SELECT * FROM jobs WHERE source = ? ORDER BY date_posted DESC", (source,))
    else:
        cur.execute("SELECT * FROM jobs ORDER BY date_posted DESC")

    rows = cur.fetchall()
    conn.close()

    return [_row_to_job(row) for row in rows]


def search_jobs(db_path, keyword=None, location=None, source=None, limit=50):
    """
    Search jobs using SQL LIKE for quick DB-level filtering.
    For fuzzy search, use the display module instead.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    conditions = []
    params = []

    if keyword:
        conditions.append("(title LIKE ? OR description LIKE ? OR employer LIKE ?)")
        kw = f"%{keyword}%"
        params.extend([kw, kw, kw])

    if location:
        conditions.append("location LIKE ?")
        params.append(f"%{location}%")

    if source:
        conditions.append("source = ?")
        params.append(source)

    where = " AND ".join(conditions) if conditions else "1=1"
    query = f"SELECT * FROM jobs WHERE {where} ORDER BY date_posted DESC LIMIT ?"
    params.append(limit)

    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()

    return [_row_to_job(row) for row in rows]


def get_job_by_url(db_path, url):
    """Fetch a single job by its URL."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM jobs WHERE url = ?", (url,))
    row = cur.fetchone()
    conn.close()
    return _row_to_job(row) if row else None


def get_job_count(db_path, source=None):
    """Return the count of jobs in the database."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    if source:
        cur.execute("SELECT COUNT(*) FROM jobs WHERE source = ?", (source,))
    else:
        cur.execute("SELECT COUNT(*) FROM jobs")
    count = cur.fetchone()[0]
    conn.close()
    return count


def purge_expired(db_path):
    """Remove jobs whose closing date has passed."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM jobs WHERE closing_date IS NOT NULL AND closing_date < date('now')"
    )
    removed = cur.rowcount
    conn.commit()
    conn.close()
    if removed:
        print(f"Purged {removed} expired jobs.")
    return removed


def _row_to_job(row):
    """Convert a database row to a JobItem."""
    return JobItem(
        url=row['url'],
        title=row['title'],
        employer=row['employer'],
        location=row['location'],
        salary=row['salary'],
        date_posted=row['date_posted'],
        closing_date=row['closing_date'],
        contract_type=row['contract_type'],
        working_pattern=row['working_pattern'],
        description=row['description'],
        job_reference=row['job_reference'],
        source=row['source'],
        staff_group=row['staff_group'],
    )