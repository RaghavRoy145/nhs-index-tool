import curses
import os
import subprocess
import webbrowser
from . import database
from .jobitem import JobItem
from . import config
import re
import textwrap

try:
    import rapidfuzz
    HAS_RAPIDFUZZ = True
except ImportError:
    from difflib import SequenceMatcher
    HAS_RAPIDFUZZ = False


def _is_wsl():
    """Detect if running inside Windows Subsystem for Linux."""
    try:
        with open('/proc/version', 'r') as f:
            return 'microsoft' in f.read().lower()
    except (IOError, OSError):
        return False


def _open_url(url):
    """Open a URL in the default browser, with WSL fallback."""
    if _is_wsl():
        # WSL: use Windows-side browser via cmd.exe or wslview
        try:
            subprocess.Popen(
                ['wslview', url],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except FileNotFoundError:
            pass
        try:
            subprocess.Popen(
                ['cmd.exe', '/c', 'start', '', url.replace('&', '^&')],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except FileNotFoundError:
            pass
    # Standard path — works on macOS, native Linux, etc.
    webbrowser.open(url)


def _sanitise_row(text):
    """Strip ALL control characters (including newlines) for single-line row rendering."""
    if not text:
        return ''
    return re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', text).strip()


def _sanitise_popup(text):
    """Strip control characters but preserve newlines and tabs for multi-line popups."""
    if not text:
        return ''
    # Keep \n (\x0a) and \t (\x09), strip everything else
    return re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]', ' ', text)


class DisplayView(object):
    """Simple view class to manage current view of a list."""

    def __init__(self):
        self.height = 0
        self.width = 0
        self.active = 0
        self.top = 0
        self.max_pos = 0

    def move_up(self):
        self.active -= 1
        self.refocus()

    def move_down(self):
        self.active += 1
        self.refocus()

    def page_down(self):
        self.active += self.visible_item_count
        self.refocus()

    def page_up(self):
        self.active -= self.visible_item_count
        self.refocus()

    def refocus(self):
        self.active = min(self.active, self.max_pos - 1)
        self.active = max(self.active, 0)

        if self.active < self.top:
            self.top = self.active

        if self.active >= self.bottom:
            self.top = self.active - self.visible_item_count + 1

    @property
    def highlighted_row(self):
        return self.active - self.top

    @property
    def bottom(self):
        return self.top + self.visible_item_count

    @property
    def visible_item_count(self):
        return self.height - 3

    def resize(self, height, width):
        self.height = height
        self.width = width

    def set_max(self, max_pos):
        self.top = 0
        self.max_pos = max_pos
        self.active = 0


class DisplayMode(object):
    NAVIGATE = 'navigate',
    SEARCH_FUZZY = 'search_fuzzy',
    SEARCH_REGEX = 'search_regex'

    valid_modes = [NAVIGATE, SEARCH_FUZZY, SEARCH_REGEX]
    search_modes = [SEARCH_FUZZY, SEARCH_REGEX]


class Display(object):
    """Encapsulates the job search TUI with run() as the main loop."""

    # Column widths
    COL_SOURCE = 6
    COL_POSTED = 8
    COL_CLOSES = 8
    COL_CONTRACT = 12
    COL_SALARY = 18
    COL_EMPLOYER = 25

    HEADER_ROWS = 2

    def __init__(self, db, curses_stdscr):
        self.all_items = database.get_all_jobs(db)
        self.items = [item for item in self.all_items if item.title]
        if not self.items:
            raise Exception(
                "No jobs found in the index. Run with --reindex to populate.")
        self.filtered_items = self.items
        self.screen = curses_stdscr
        self.view = DisplayView()
        self.draw_row = 0
        self.search_query = ""
        self.mode = DisplayMode.NAVIGATE
        self.item_name_list = [item.title for item in self.items]

    def _highlight_match(self, text, query):
        """Return list of (substring, is_highlighted) segments.
        Finds all non-overlapping matches of query in text (case-insensitive)."""
        if not query:
            return [(text, False)]

        query_lower = query.lower()
        text_lower = text.lower()

        segments = []
        start = 0
        while start < len(text):
            match_pos = text_lower.find(query_lower, start)
            if match_pos == -1:
                segments.append((text[start:], False))
                break
            if match_pos > start:
                segments.append((text[start:match_pos], False))
            segments.append((text[match_pos:match_pos + len(query)], True))
            start = match_pos + len(query)

        return segments if segments else [(text, False)]

    @property
    def active_item(self) -> JobItem:
        if not self.filtered_items:
            return JobItem("")
        return self.filtered_items[self.view.active]

    def enable_character_cursor(self, enable=False):
        curses.curs_set(bool(enable))

    def show_help(self):
        help_text = """NAVIGATION:
   ↑/↓/PgUp/PgDn    Move cursor

SEARCH:
   /           Regex search (title)
   f           Fuzzy search (title)
   ESC         Clear search

ACTIONS:
   Enter/w     Open in web browser
   i           Show job details
   p           Generate application prompt
   ?           Show this help
   q           Quit
"""
        self.popup(help_text)
        self.screen.getch()

    @property
    def footer(self):
        FOOTERS = {
            DisplayMode.SEARCH_REGEX: f"/{self.search_query}",
            DisplayMode.SEARCH_FUZZY: f"f> {self.search_query}",
            DisplayMode.NAVIGATE: f"Press '?' for help | ({len(self.filtered_items)}/{len(self.items)}) jobs"
        }
        return FOOTERS[self.mode]

    def _truncate(self, text, width):
        if not text:
            return ''
        # Sanitise control characters before truncation
        text = _sanitise_row(text)
        if len(text) <= width:
            return text
        return text[:width - 1] + '…'

    def add_next_row(self, row_text, footer=False, highlight_query=None):
        row_id = self.draw_row
        if footer:
            row_id = self.view.height - 1
        else:
            self.draw_row += 1

        is_active_row = (row_id == self.view.highlighted_row + self.HEADER_ROWS
                         and self.mode == DisplayMode.NAVIGATE)
        base_attr = curses.color_pair(1) if is_active_row else curses.color_pair(0)

        # Truncate to screen width
        max_w = self.view.width - 1
        row_text = row_text[:max_w]

        try:
            if highlight_query and not is_active_row:
                # Render with search match highlighting
                segments = self._highlight_match(row_text, highlight_query)
                col = 0
                for text_part, is_match in segments:
                    if col >= max_w:
                        break
                    text_part = text_part[:max_w - col]
                    attr = curses.color_pair(2) | curses.A_BOLD if is_match else base_attr
                    self.screen.addstr(row_id, col, text_part, attr)
                    col += len(text_part)
            else:
                self.screen.addstr(row_id, 0, row_text, base_attr)
        except curses.error:
            pass

    def clear_screen(self):
        self.screen.clear()
        self.draw_row = 0

    def popup(self, text):
        max_h, max_w = self.screen.getmaxyx()
        # Sanitise text for popup display (preserve newlines for splitlines)
        text = _sanitise_popup(text)
        lines = sum((textwrap.wrap(line, width=max_w - 16, max_lines=int(max_h / 3),
                                   subsequent_indent="  ")
                     for line in text.splitlines()), [])

        height = len(lines)
        width = max(map(len, lines)) if lines else 20

        loc_x = 4
        loc_y = min(self.view.highlighted_row + 3,
                    self.view.height - height - 2)
        loc_y = max(0, loc_y)

        try:
            outer = self.screen.derwin(height + 2, min(width + 4, max_w - 6), loc_y, loc_x)
            outer.erase()
            outer.border()
            outer.refresh()

            inner = outer.derwin(height + 1, min(width + 1, max_w - 10), 1, 2)
            for line in lines:
                inner.addstr(line + "\n")
            inner.refresh()
        except curses.error:
            pass

    def search_regex(self):
        if not self.search_query:
            return self.items
        try:
            pattern = re.compile(self.search_query, re.IGNORECASE)
        except re.error:
            return []
        return [item for item in self.items if re.search(pattern, item.title or '')]

    def search_fuzzy(self):
        if not self.search_query:
            return self.items

        if HAS_RAPIDFUZZ:
            results = rapidfuzz.process.extract(
                self.search_query, self.item_name_list,
                scorer=rapidfuzz.fuzz.partial_ratio,
                processor=rapidfuzz.utils.default_process,
                score_cutoff=50, limit=100)
            return [self.items[result[2]] for result in results]
        else:
            # Fallback: difflib-based fuzzy matching
            query_lower = self.search_query.lower()
            scored = []
            for i, name in enumerate(self.item_name_list):
                if not name:
                    continue
                name_lower = name.lower()
                # Substring match gets high score
                if query_lower in name_lower:
                    scored.append((i, 90))
                else:
                    ratio = SequenceMatcher(None, query_lower, name_lower).ratio() * 100
                    if ratio >= 40:
                        scored.append((i, ratio))

            scored.sort(key=lambda x: x[1], reverse=True)
            return [self.items[idx] for idx, _ in scored[:100]]

    def _format_row(self, job):
        """Format a job into a fixed-width row string."""
        source = self._truncate(job.source.upper(), self.COL_SOURCE)
        posted = self._truncate(job.age, self.COL_POSTED)
        closes = self._truncate(job.closes_in, self.COL_CLOSES)
        contract = self._truncate(job.contract_type, self.COL_CONTRACT)
        salary = self._truncate(job.salary, self.COL_SALARY)
        employer = self._truncate(job.employer, self.COL_EMPLOYER)

        # Title gets whatever space is left
        prefix = (f"{source:<{self.COL_SOURCE}} "
                  f"{posted:<{self.COL_POSTED}} "
                  f"{closes:<{self.COL_CLOSES}} "
                  f"{contract:<{self.COL_CONTRACT}} "
                  f"{salary:<{self.COL_SALARY}} "
                  f"{employer:<{self.COL_EMPLOYER}} ")
        title_width = max(10, self.view.width - len(prefix) - 1)
        title = self._truncate(job.title, title_width)

        return f"{prefix}{title}"

    def draw_ui(self):
        self.clear_screen()
        self.view.resize(*self.screen.getmaxyx())

        header = (f"{'Src':<{self.COL_SOURCE}} "
                  f"{'Posted':<{self.COL_POSTED}} "
                  f"{'Closes':<{self.COL_CLOSES}} "
                  f"{'Contract':<{self.COL_CONTRACT}} "
                  f"{'Salary':<{self.COL_SALARY}} "
                  f"{'Employer':<{self.COL_EMPLOYER}} "
                  f"{'Title'}")
        self.add_next_row(header)
        self.add_next_row("─" * self.view.width)

        # Determine highlight query for search modes
        highlight_q = self.search_query if self.search_query and self.mode == DisplayMode.NAVIGATE else None
        # Also highlight after confirming search (query persists in navigate mode)
        if not highlight_q and self.search_query:
            highlight_q = self.search_query

        for item in self.filtered_items[self.view.top:self.view.bottom]:
            row_text = self._format_row(item)
            self.add_next_row(row_text, highlight_query=highlight_q)

        self.add_next_row(self.footer, footer=True)
        self.screen.refresh()
        self.enable_character_cursor(self.mode in DisplayMode.search_modes)

    def go(self):
        """The main application loop."""
        curses.curs_set(0)
        curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_WHITE)  # Active row
        curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK)  # Search highlight

        self.mode = DisplayMode.NAVIGATE
        self.view.set_max(len(self.filtered_items))

        while True:
            self.draw_ui()
            key = self.screen.getch()

            if self.mode in DisplayMode.search_modes:
                if key in (10, curses.KEY_ENTER, curses.KEY_UP, curses.KEY_DOWN):
                    self.mode = DisplayMode.NAVIGATE
                elif key == 27:
                    self.mode = DisplayMode.NAVIGATE
                    self.search_query = ""
                    self.filtered_items = self.items

                if key == curses.KEY_BACKSPACE or key == 127:
                    self.search_query = self.search_query[:-1]
                elif 32 <= key <= 126:
                    self.search_query += chr(key)

                if self.mode == DisplayMode.SEARCH_REGEX:
                    self.filtered_items = self.search_regex()
                if self.mode == DisplayMode.SEARCH_FUZZY:
                    self.filtered_items = self.search_fuzzy()

                self.view.set_max(len(self.filtered_items))

            if self.mode == DisplayMode.NAVIGATE:
                if key == curses.KEY_UP:
                    self.view.move_up()
                if key == curses.KEY_DOWN:
                    self.view.move_down()
                if key == curses.KEY_NPAGE:
                    self.view.page_down()
                if key == curses.KEY_PPAGE:
                    self.view.page_up()

                if key == ord('/'):
                    self.mode = DisplayMode.SEARCH_REGEX
                    self.search_query = ""

                if key == ord('f'):
                    self.mode = DisplayMode.SEARCH_FUZZY
                    self.search_query = ""

                if key == ord('?'):
                    self.show_help()

                if key == ord('i'):
                    job = self.active_item
                    if job:
                        detail_text = (
                            f"{job.title}\n"
                            f"Employer: {job.employer}\n"
                            f"Location: {job.location}\n"
                            f"Salary: {job.salary}\n"
                            f"Contract: {job.contract_type}\n"
                            f"Pattern: {job.working_pattern}\n"
                            f"Posted: {job.date_posted}\n"
                            f"Closes: {job.closing_date}\n"
                            f"Ref: {job.job_reference}\n"
                            f"URL: {job.url}\n"
                        )
                        self.popup(detail_text)
                        self.screen.getch()

                if key in (10, curses.KEY_ENTER, ord('w')):
                    if self.active_item and self.active_item.url:
                        _open_url(self.active_item.url)

                if key == ord('p'):
                    job = self.active_item
                    if not job:
                        continue

                    # Exit curses for the interactive prompt generator
                    curses.endwin()

                    try:
                        from .promptgen import run_prompt_generator
                        from .nhsconnector import NHSJobsConnector
                        from .dwpconnector import DWPJobsConnector
                        from .indeedconnector import IndeedConnector

                        # Fetch full job description
                        print(f"\nFetching full description for: {job.title}...")
                        detail = None
                        if job.source == 'nhs':
                            connector = NHSJobsConnector()
                            detail = connector.get_job_detail(job.url)
                        elif job.source == 'dwp':
                            connector = DWPJobsConnector()
                            detail = connector.get_job_detail(job.url)
                        elif job.source == 'indeed':
                            connector = IndeedConnector()
                            jd_text = connector.fetch_job_detail(job.url)
                            if jd_text:
                                detail = {'description': jd_text}

                        if detail and detail.get('description'):
                            jd = detail['description']
                        elif job.description:
                            jd = job.description
                        else:
                            print("Could not fetch job description.")
                            print("You can paste it manually in the next step.")
                            jd = None

                        run_prompt_generator(
                            job_description=jd,
                            job_title=job.title,
                            employer=job.employer,
                        )
                    except Exception as e:
                        print(f"Error: {e}")

                    input("\nPress Enter to return to the job list.")
                    self.screen.clear()
                    self.screen.refresh()

                if key == ord('q'):
                    return


def show_display_wrapped(stdscr, db):
    disp = Display(db, stdscr)
    disp.go()


def show_display(db_path):
    """Entry point for the interactive display."""
    curses.wrapper(show_display_wrapped, db_path)