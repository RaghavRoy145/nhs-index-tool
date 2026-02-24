import datetime
import webbrowser


def format_age(date_str):
    """
    Converts an ISO 8601 date string or 'DD Month YYYY' to a human-readable age.
    Returns strings like '3 days ago', '2 months ago', '1 year ago'.
    """
    if not date_str:
        return 'N/A'

    try:
        if isinstance(date_str, datetime.datetime):
            dt_object = date_str
        elif isinstance(date_str, datetime.date):
            dt_object = datetime.datetime.combine(date_str, datetime.time())
        else:
            # Try ISO format first
            try:
                if date_str.endswith('Z'):
                    date_str = date_str[:-1] + '+00:00'
                dt_object = datetime.datetime.fromisoformat(date_str)
            except ValueError:
                # Try common date formats
                for fmt in ('%d %B %Y', '%Y-%m-%d', '%d/%m/%Y', '%d %b %Y'):
                    try:
                        dt_object = datetime.datetime.strptime(date_str, fmt)
                        break
                    except ValueError:
                        continue
                else:
                    return 'N/A'

        if dt_object.tzinfo is not None:
            dt_object = dt_object.replace(tzinfo=None)

        now = datetime.datetime.now()
        delta = now - dt_object

        days = delta.days
        if days < 0:
            # Future date (closing date)
            days = abs(days)
            if days < 1:
                return 'today'
            elif days == 1:
                return 'in 1d'
            elif days < 7:
                return f'in {days}d'
            elif days < 30:
                weeks = days // 7
                return f'in {weeks}w'
            else:
                months = days // 30
                return f'in {months}mo'

        if days < 1:
            hours = delta.seconds // 3600
            if hours < 1:
                return 'just now'
            return f'{hours}h ago'
        elif days == 1:
            return '1d ago'
        elif days < 7:
            return f'{days}d ago'
        elif days < 30:
            weeks = days // 7
            return f'{weeks}w ago'
        elif days < 365:
            months = days // 30
            return f'{months}mo ago'
        else:
            years = days // 365
            return f'{years}y ago'
    except (ValueError, TypeError):
        return 'N/A'


class JobItem:
    """Represents a single job listing from any source."""

    def __init__(self, url, title="", employer="", location="",
                 salary="", date_posted=None, closing_date=None,
                 contract_type="", working_pattern="", description="",
                 job_reference="", source="", staff_group=""):
        self.url = url
        self.title = title
        self.employer = employer
        self.location = location
        self.salary = salary
        self.date_posted = date_posted
        self.closing_date = closing_date
        self.contract_type = contract_type
        self.working_pattern = working_pattern
        self.description = description
        self.job_reference = job_reference
        self.source = source  # 'nhs' or 'dwp'
        self.staff_group = staff_group

    def __bool__(self):
        return bool(self.url)

    def __str__(self):
        return (
            f"Job [{self.source}] {self.title}\n"
            f"-------\n"
            f"employer={self.employer}\n"
            f"location={self.location}\n"
            f"salary={self.salary}\n"
            f"posted={self.date_posted}\n"
            f"closes={self.closing_date}\n"
            f"contract={self.contract_type}\n"
            f"pattern={self.working_pattern}\n"
            f"url={self.url}\n"
            f"ref={self.job_reference}\n"
            f"-------"
        )

    @property
    def age(self):
        """Human-readable age since posting."""
        return format_age(self.date_posted)

    @property
    def closes_in(self):
        """Human-readable time until closing."""
        return format_age(self.closing_date)

    @property
    def name(self):
        """Compatibility with the existing display code."""
        return self.title

    def open(self):
        """Open the job listing in the default web browser."""
        if self.url:
            webbrowser.open(self.url)