import os
import re
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import dotenv
import requests
from bs4 import BeautifulSoup, Tag

# Module logger. Callers can configure logging as needed; a helper is provided.
logger = logging.getLogger(__name__)


def configure_logging(level: int = logging.INFO) -> None:
    """Configure module logging (optional; safe to call from CLI)."""
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
    logger.setLevel(level)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class Problem:
    number: int
    name: str
    url: str
    attempts: int
    remaining: str
    worth: int
    status: str


@dataclass
class ProblemDetail:
    number: int
    name: str
    url: str
    body_text: str
    body_latex: str
    answer_fields: list[dict[str, str]]
    attempts: int
    remaining: str
    worth: int
    status: str
    hidden_fields: dict[str, str]


@dataclass
class HomeworkSet:
    name: str
    url: str
    status: str
    due_date: str
    problems: list[Problem] = field(default_factory=list)


@dataclass
class ClassGrade:
    set_name: str
    score: str
    out_of: str
    percent: str


@dataclass
class WwConfig:
    url: str
    classes: dict[str, tuple[str, str]]


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------


def load_config() -> WwConfig:
    """Load WeBWorK configuration from .env file."""
    dotenv.load_dotenv()
    raw = {"url": os.getenv("url"), "classes": os.getenv("classes")}
    if None in raw.values():
        raise RuntimeError("Missing 'url' or 'classes' in .env")

    url: str = str(raw["url"])
    class_names = str(raw["classes"]).split(",")

    logins: dict[str, tuple[str, str]] = {}
    for idx, cls in enumerate(class_names):
        u = os.getenv(f"username{idx}")
        p = os.getenv(f"password{idx}")
        if u is None or p is None:
            raise RuntimeError(f"Missing login credentials for {cls}")
        logins[cls] = (u, p)

    return WwConfig(url, logins)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_URL = "https://webwork.ufv.ca"


def _full_url(href: str) -> str:
    if href.startswith("http"):
        return href
    return f"{_BASE_URL}{href}"


def _extract_due_date(status_text: str) -> str:
    """Pull a due-date string out of a status like 'Open, closes 03/29/2026 at 11:30pm PDT.'"""
    m = re.search(r"closes\s+(.+?)(?:\.|$)", status_text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r"Closed", status_text, re.IGNORECASE)
    if m:
        return "Closed"
    return status_text


def _latex_text(tag: Tag) -> str:
    """
    Walk a BeautifulSoup tag and return a text representation where
    <script type="math/tex"> blocks are replaced with $...$ inline LaTeX.

    Hidden inputs, MathQuill fields, and previous-answer fields are
    filtered out so only the visible problem text remains.
    """
    parts: list[str] = []
    for child in tag.children:
        if isinstance(child, Tag):
            if child.name == "script" and child.get("type") in (
                "math/tex",
                "math/tex; mode=display",
            ):
                mode = child.get("type", "")
                latex = child.get_text()
                if "display" in str(mode):
                    parts.append(f"$${latex}$$")
                else:
                    parts.append(f"${latex}$")
            elif child.name in ("br",):
                parts.append("\n")
            elif child.name == "input":
                name = str(child.get("name", ""))
                inp_type = str(child.get("type", "text"))
                # Skip hidden inputs entirely (previous answers, MathQuill, etc.)
                if inp_type == "hidden":
                    continue
                # Skip MathQuill and previous-answer fields by name
                if name.startswith(("previous_", "MaThQuIlL_", "MuLtIaNsWeR_")):
                    continue
                # Visible answer field — show its label
                label = child.get("aria-label", name or "___")
                parts.append(f"[{label}]")
            elif child.name in ("div", "p", "table", "tr", "ul", "ol", "li"):
                inner = _latex_text(child)
                parts.append(f"\n{inner}\n")
            else:
                parts.append(_latex_text(child))
        else:
            parts.append(str(child))
    return "".join(parts)


# ---------------------------------------------------------------------------
# WeBWorK Client
# ---------------------------------------------------------------------------


class WeBWorKClient:
    """Stateful client for a single WeBWorK class."""

    def __init__(self, base_url: str, class_name: str, username: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.class_name = class_name
        self.username = username
        self.password = password
        self.class_url = f"{self.base_url}/{self.class_name}"
        self._session = requests.Session()
        self._logged_in = False
        # Per-instance logger to help when managing multiple class clients.
        self.logger = logger.getChild(self.class_name)
        self.logger.debug(
            "Initialized WeBWorKClient (base_url=%s, username=%s)",
            self.base_url,
            self.username,
        )

    # -- lifecycle -----------------------------------------------------------

    def login(self) -> bool:
        """Authenticate with WeBWorK. Returns True on success."""
        if self._logged_in:
            self.logger.debug("Already logged in; skipping login.")
            return True
        self.logger.debug("Attempting login to %s as %s", self.class_url, self.username)
        start = time.time()
        try:
            res = self._session.post(
                self.class_url,
                data={
                    "user": self.username,
                    "passwd": self.password,
                    ".submit": "Continue",
                },
                timeout=30,
            )
        except Exception as exc:
            elapsed = time.time() - start
            self.logger.warning(
                "Login POST failed after %.2fs for %s: %s", elapsed, self.class_name, exc
            )
            return False

        elapsed = time.time() - start
        self.logger.debug(
            "Login POST completed in %.2fs (status_code=%s)",
            elapsed,
            getattr(res, "status_code", "n/a"),
        )

        soup = BeautifulSoup(res.text, "lxml")
        status = soup.select_one("#loginstatus")
        if status and "Logged in as" in status.get_text():
            self._logged_in = True
            self.logger.info("Logged in as %s for class %s", self.username, self.class_name)
            return True

        # If we reach here, login did not succeed
        self.logger.warning("Login failed for %s; loginstatus element missing or unexpected", self.username)
        return False

    def _ensure_login(self) -> None:
        if not self._logged_in:
            self.logger.debug("Not logged in; attempting to login.")
            if not self.login():
                self.logger.error(
                    "Failed to log into %s as %s", self.class_name, self.username
                )
                raise RuntimeError(
                    f"Failed to log into {self.class_name} as {self.username}"
                )

    # -- sets ----------------------------------------------------------------

    def get_all_sets(self) -> list[HomeworkSet]:
        """Return every homework set for this class."""
        self._ensure_login()
        res = self._session.get(self.class_url)
        soup = BeautifulSoup(res.text, "lxml")

        sets: list[HomeworkSet] = []
        table = soup.select_one("table.problem_set_table")
        if not table:
            return sets

        for row in table.select("tbody tr"):
            cells = row.select("td")
            if len(cells) < 2:
                continue
            link = cells[0].select_one("a")
            if not link:
                continue

            name = link.get_text(strip=True)
            href = str(link.get("href", ""))
            status = cells[1].get_text(strip=True)
            due = _extract_due_date(status)

            sets.append(
                HomeworkSet(name=name, url=_full_url(href), status=status, due_date=due)
            )
        return sets

    def get_open_sets(self) -> list[HomeworkSet]:
        """Return only sets whose status contains 'Open'."""
        return [s for s in self.get_all_sets() if "open" in s.status.lower()]

    def get_due_dates(self) -> list[dict[str, str]]:
        """Return a list of {name, due_date, status} for every set."""
        return [
            {"name": s.name, "due_date": s.due_date, "status": s.status}
            for s in self.get_all_sets()
        ]

    # -- set info (problems list) --------------------------------------------

    def get_set_info(self, set_name: str) -> HomeworkSet | None:
        """Fetch a specific set's page and parse its problem table."""
        self._ensure_login()
        all_sets = self.get_all_sets()
        hw = next((s for s in all_sets if s.name == set_name), None)
        if hw is None:
            return None

        res = self._session.get(hw.url)
        soup = BeautifulSoup(res.text, "lxml")
        table = soup.select_one("table.problem_set_table")
        if not table:
            return hw

        for row in table.select("tbody tr"):
            cells = row.select("td")
            if len(cells) < 5:
                continue
            link = cells[0].select_one("a")
            if not link:
                continue

            name = link.get_text(strip=True)
            href = str(link.get("href", ""))
            attempts_text = cells[1].get_text(strip=True)
            remaining = cells[2].get_text(strip=True)
            worth_text = cells[3].get_text(strip=True)
            status = cells[4].get_text(strip=True)

            # Extract problem number from name like "Problem 3"
            num_match = re.search(r"\d+", name)
            num = int(num_match.group()) if num_match else 0

            hw.problems.append(
                Problem(
                    number=num,
                    name=name,
                    url=_full_url(href),
                    attempts=int(attempts_text) if attempts_text.isdigit() else 0,
                    remaining=remaining,
                    worth=int(worth_text) if worth_text.isdigit() else 0,
                    status=status,
                )
            )
        return hw

    # -- single problem ------------------------------------------------------

    def get_problem(self, set_name: str, problem_number: int) -> ProblemDetail | None:
        """Fetch a single problem page and return its content with LaTeX."""
        self._ensure_login()

        # Build the problem URL
        set_slug = set_name.replace(" ", "_")
        problem_url = (
            f"{self.class_url}/{set_slug}/{problem_number}/"
            f"?effectiveUser={self.username}"
        )

        res = self._session.get(problem_url)
        soup = BeautifulSoup(res.text, "lxml")

        # Problem body
        prob_body = soup.select_one("#problem_body")
        if not prob_body:
            return None

        body_text = prob_body.get_text(separator="\n", strip=True)
        body_latex = _latex_text(prob_body).strip()
        # Collapse runs of blank lines into a single blank line
        body_latex = re.sub(r"\n{3,}", "\n\n", body_latex)

        # Answer fields
        answer_fields: list[dict[str, str]] = []
        # Capture all visible answer inputs: AnSwEr* and MuLtIaNsWeR_AnSwEr*
        # but skip hidden fields, previous-answer fields, and MathQuill fields
        for inp in prob_body.select("input"):
            name = str(inp.get("name", ""))
            inp_type = str(inp.get("type", "text"))
            if inp_type == "hidden":
                continue
            if name.startswith(("previous_", "MaThQuIlL_")):
                continue
            if not (name.startswith("AnSwEr") or name.startswith("MuLtIaNsWeR_AnSwEr")):
                continue
            answer_fields.append(
                {
                    "name": name,
                    "type": inp_type,
                    "value": str(inp.get("value", "")),
                    "label": str(inp.get("aria-label", "")),
                }
            )
        for sel in prob_body.select("select"):
            name = str(sel.get("name", ""))
            if not (name.startswith("AnSwEr") or name.startswith("MuLtIaNsWeR_AnSwEr")):
                continue
            options = [o.get_text(strip=True) for o in sel.select("option")]
            answer_fields.append(
                {
                    "name": name,
                    "type": "select",
                    "value": "",
                    "options": ", ".join(options),
                    "label": str(sel.get("aria-label", "")),
                }
            )

        # Hidden form fields needed for submission
        form = soup.select_one("#problemMainForm")
        hidden_fields: dict[str, str] = {}
        if form:
            for inp in form.select("input[type=hidden]"):
                n = str(inp.get("name", ""))
                v = str(inp.get("value", ""))
                if n:
                    hidden_fields[n] = v

        # Attempts / status from the page
        num_attempts = 0
        remaining = "unknown"
        att_match = re.search(r"attempted this problem\s+(\d+)\s+time", res.text)
        if att_match:
            num_attempts = int(att_match.group(1))
        rem_match = re.search(
            r"You have\s+(unlimited|\d+)\s+attempts?\s+remaining", res.text
        )
        if rem_match:
            remaining = rem_match.group(1)

        # Worth / score from score summary
        worth = 1
        status = "0%"
        score_div = soup.select_one("#score_summary")
        if score_div:
            score_text = score_div.get_text()
            pct_match = re.search(r"(\d+)%", score_text)
            if pct_match:
                status = pct_match.group(0)

        return ProblemDetail(
            number=problem_number,
            name=f"Problem {problem_number}",
            url=problem_url,
            body_text=body_text,
            body_latex=body_latex,
            answer_fields=answer_fields,
            attempts=num_attempts,
            remaining=remaining,
            worth=worth,
            status=status,
            hidden_fields=hidden_fields,
        )

    # -- submit answers ------------------------------------------------------

    def submit_answer(
        self,
        set_name: str,
        problem_number: int,
        answers: dict[str, str],
    ) -> dict:
        """
        Submit answers for a problem.

        Parameters
        ----------
        set_name : str
            The homework set name (e.g. "Assignment9 Vector-Geometry").
        problem_number : int
            The problem number.
        answers : dict[str, str]
            Mapping of answer field names to values,
            e.g. {"AnSwEr0001": "(14,2,10)"}.

        Returns
        -------
        dict with keys: success (bool), message (str), results (list[dict])
        """
        self._ensure_login()

        self.logger.info(
            "Submitting answers for class=%s set=%s problem=%s",
            self.class_name,
            set_name,
            problem_number,
        )
        start = time.time()

        # First fetch the problem to get hidden fields
        problem = self.get_problem(set_name, problem_number)
        if problem is None:
            self.logger.error(
                "Could not load problem %s from %s for submission", problem_number, set_name
            )
            return {
                "success": False,
                "message": f"Could not load problem {problem_number} from {set_name}.",
                "results": [],
            }

        # Build submission payload
        payload = dict(problem.hidden_fields)
        payload["submitAnswers"] = "Submit Answers"

        # Set previous answers and actual answers
        for af in problem.answer_fields:
            name = af["name"]
            payload[name] = answers.get(name, "")
            payload[f"previous_{name}"] = af.get("value", "")

        set_slug = set_name.replace(" ", "_")
        submit_url = (
            f"{self.class_url}/{set_slug}/{problem_number}/"
            f"?effectiveUser={self.username}"
        )

        try:
            res = self._session.post(submit_url, data=payload, timeout=30)
        except Exception as exc:
            elapsed = time.time() - start
            self.logger.error(
                "Submission POST failed after %.2fs for %s/%s: %s",
                elapsed,
                set_name,
                problem_number,
                exc,
            )
            return {"success": False, "message": str(exc), "results": []}

        elapsed = time.time() - start
        self.logger.debug(
            "Submission POST completed in %.2fs (status=%s, bytes=%s)",
            elapsed,
            getattr(res, "status_code", "n/a"),
            len(getattr(res, "content", b"")),
        )

        soup = BeautifulSoup(res.text, "lxml")

        # Parse results
        results: list[dict[str, str]] = []
        result_rows = soup.select("table.attemptResults tbody tr")
        for row in result_rows:
            cells = row.select("td")
            if len(cells) >= 3:
                results.append(
                    {
                        "field": cells[0].get_text(strip=True),
                        "entered": cells[1].get_text(strip=True),
                        "result": cells[2].get_text(strip=True),
                    }
                )

        # Check for score
        score_div = soup.select_one("#score_summary")
        score_text = score_div.get_text(strip=True) if score_div else ""

        # Check overall result
        message_div = soup.select_one("#Message")
        message_text = message_div.get_text(strip=True) if message_div else ""

        # Determine success from results
        all_correct = (
            all("correct" in r.get("result", "").lower() for r in results)
            if results
            else False
        )

        self.logger.info(
            "Submission completed for %s #%s: success=%s message=%s",
            set_name,
            problem_number,
            all_correct,
            message_text or score_text,
        )

        return {
            "success": all_correct,
            "message": message_text or score_text,
            "score_summary": score_text,
            "results": results,
        }

    def preview_answer(
        self,
        set_name: str,
        problem_number: int,
        answers: dict[str, str],
    ) -> dict:
        """
        Preview answers without submitting (doesn't count as an attempt).

        Same interface as submit_answer but uses the Preview button.
        """
        self._ensure_login()

        problem = self.get_problem(set_name, problem_number)
        if problem is None:
            return {
                "success": False,
                "message": f"Could not load problem {problem_number} from {set_name}.",
                "previews": [],
            }

        payload = dict(problem.hidden_fields)
        payload["previewAnswers"] = "Preview My Answers"

        for af in problem.answer_fields:
            name = af["name"]
            payload[name] = answers.get(name, "")
            payload[f"previous_{name}"] = af.get("value", "")

        set_slug = set_name.replace(" ", "_")
        preview_url = (
            f"{self.class_url}/{set_slug}/{problem_number}/"
            f"?effectiveUser={self.username}"
        )

        res = self._session.post(preview_url, data=payload)
        soup = BeautifulSoup(res.text, "lxml")

        previews: list[dict[str, str]] = []
        result_rows = soup.select("table.attemptResults tbody tr")
        for row in result_rows:
            cells = row.select("td")
            if len(cells) >= 2:
                previews.append(
                    {
                        "field": cells[0].get_text(strip=True),
                        "entered": cells[1].get_text(strip=True),
                        "preview": cells[2].get_text(strip=True)
                        if len(cells) >= 3
                        else "",
                    }
                )

        return {
            "success": True,
            "message": "Preview generated (no attempt used).",
            "previews": previews,
        }

    # -- grades --------------------------------------------------------------

    def get_grades(self) -> list[ClassGrade]:
        """Fetch the grades page and parse the scores table."""
        self._ensure_login()
        grades_url = f"{self.class_url}/grades/?effectiveUser={self.username}"
        res = self._session.get(grades_url)
        soup = BeautifulSoup(res.text, "lxml")

        grades: list[ClassGrade] = []
        table = soup.select_one("table.grade_table") or soup.select_one("table")
        if not table:
            return grades

        for row in table.select("tbody tr"):
            cells = row.select("td")
            if len(cells) < 3:
                continue
            set_name = cells[0].get_text(strip=True)
            score = cells[1].get_text(strip=True)
            out_of = cells[2].get_text(strip=True) if len(cells) > 2 else ""
            percent = cells[3].get_text(strip=True) if len(cells) > 3 else ""
            grades.append(
                ClassGrade(
                    set_name=set_name,
                    score=score,
                    out_of=out_of,
                    percent=percent,
                )
            )
        return grades

    # -- course info (single-class overview) ---------------------------------

    def get_course_info(self) -> dict:
        """
        Return a comprehensive overview of this single class:
        class name, username, all sets, open sets with due dates,
        and a quick progress snapshot for each open set.
        """
        self._ensure_login()

        all_sets = self.get_all_sets()
        open_sets = [s for s in all_sets if "open" in s.status.lower()]

        open_set_summaries: list[dict] = []
        for s in open_sets:
            info = self.get_set_info(s.name)
            if info and info.problems:
                total_pts = sum(p.worth for p in info.problems)
                earned_pts = sum(p.worth for p in info.problems if p.status == "100%")
                done = [p.number for p in info.problems if p.status == "100%"]
                todo = [p.number for p in info.problems if p.status != "100%"]
                open_set_summaries.append(
                    {
                        "name": s.name,
                        "due_date": s.due_date,
                        "status": s.status,
                        "total_problems": len(info.problems),
                        "completed_count": len(done),
                        "total_points": total_pts,
                        "earned_points": earned_pts,
                        "percent": f"{earned_pts / total_pts * 100:.0f}%"
                        if total_pts
                        else "N/A",
                        "completed_problems": done,
                        "remaining_problems": todo,
                    }
                )
            else:
                open_set_summaries.append(
                    {
                        "name": s.name,
                        "due_date": s.due_date,
                        "status": s.status,
                        "total_problems": 0,
                        "completed_count": 0,
                        "total_points": 0,
                        "earned_points": 0,
                        "percent": "N/A",
                        "completed_problems": [],
                        "remaining_problems": [],
                    }
                )

        closed_set_summaries: list[dict] = [
            {"name": s.name, "due_date": s.due_date, "status": s.status}
            for s in all_sets
            if "open" not in s.status.lower()
        ]

        return {
            "class_name": self.class_name,
            "username": self.username,
            "url": self.class_url,
            "total_sets": len(all_sets),
            "open_sets_count": len(open_sets),
            "closed_sets_count": len(closed_set_summaries),
            "open_sets": open_set_summaries,
            "closed_sets": closed_set_summaries,
        }

    # -- hardcopy (PDF download) ---------------------------------------------

    def download_hardcopy(
        self,
        set_name: str,
        save_dir: str | Path = ".",
        include_answers: bool = True,
        include_comments: bool = False,
    ) -> dict:
        """
        Download a PDF hardcopy of a homework set.

        Parameters
        ----------
        set_name : str
            The homework set name (e.g. "Assignment9 Vector-Geometry").
        save_dir : str | Path
            Directory to save the PDF into. Defaults to current directory.
        include_answers : bool
            Include student's previous answers in the hardcopy.
        include_comments : bool
            Include grader comments in the hardcopy.

        Returns
        -------
        dict with keys: success (bool), message (str), path (str | None)
        """
        self._ensure_login()

        set_slug = set_name.replace(" ", "_")
        hc_page_url = (
            f"{self.class_url}/hardcopy/{set_slug}/?effectiveUser={self.username}"
        )

        # GET the hardcopy page to retrieve hidden form fields
        res = self._session.get(hc_page_url)
        soup = BeautifulSoup(res.text, "lxml")
        form = soup.select_one("#hardcopy-form")
        if form is None:
            return {
                "success": False,
                "message": "Could not find the hardcopy form on the page.",
                "path": None,
            }

        # Collect hidden fields
        payload: dict[str, str] = {}
        for inp in form.select("input[type=hidden]"):
            n = str(inp.get("name", ""))
            v = str(inp.get("value", ""))
            if n and n != ".cgifields":
                payload[n] = v

        # Set options
        payload["hardcopy_format"] = "pdf"
        payload["generate_hardcopy"] = "Generate Hardcopy"
        if include_answers:
            payload["printStudentAnswers"] = "on"
        if include_comments:
            payload["showComments"] = "on"

        # POST to generate the PDF
        action = str(form.get("action", ""))
        post_url = _full_url(action) if action else hc_page_url
        res2 = self._session.post(post_url, data=payload)

        content_type = res2.headers.get("Content-Type", "")
        if "application/pdf" not in content_type:
            return {
                "success": False,
                "message": (
                    f"Expected PDF but got Content-Type: {content_type}. "
                    "The server may not support hardcopy for this set."
                ),
                "path": None,
            }

        disp = res2.headers.get("Content-Disposition", "")
        fname_match = re.search(r'filename="?([^";\n]+)"?', disp)
        if fname_match:
            filename = fname_match.group(1).strip()
        else:
            filename = f"{self.class_name}.{self.username}.{set_slug}.pdf"

        save_path = Path(save_dir) / filename
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(res2.content)

        return {
            "success": True,
            "message": f"Saved {len(res2.content)} bytes to {save_path}",
            "path": str(save_path),
        }


# ---------------------------------------------------------------------------
# Multi-class manager
# ---------------------------------------------------------------------------


class WeBWorKManager:
    """Manages multiple WeBWorK class clients from a single config."""

    def __init__(self, config: WwConfig | None = None):
        if config is None:
            config = load_config()
        self.config = config
        self._clients: dict[str, WeBWorKClient] = {}
        for class_name, (username, password) in config.classes.items():
            self._clients[class_name] = WeBWorKClient(
                base_url=config.url,
                class_name=class_name,
                username=username,
                password=password,
            )

    def get_classes(self) -> list[str]:
        """Return the names of all configured classes."""
        return list(self._clients.keys())

    def client(self, class_name: str) -> WeBWorKClient:
        """Get the client for a specific class."""
        if class_name not in self._clients:
            available = ", ".join(self._clients.keys())
            raise ValueError(f"Unknown class '{class_name}'. Available: {available}")
        return self._clients[class_name]

    # -- convenience wrappers ------------------------------------------------

    def get_all_sets(self, class_name: str) -> list[HomeworkSet]:
        return self.client(class_name).get_all_sets()

    def get_open_sets(self, class_name: str) -> list[HomeworkSet]:
        return self.client(class_name).get_open_sets()

    def get_due_dates(self, class_name: str) -> list[dict[str, str]]:
        return self.client(class_name).get_due_dates()

    def get_set_info(self, class_name: str, set_name: str) -> HomeworkSet | None:
        return self.client(class_name).get_set_info(set_name)

    def get_problem(
        self, class_name: str, set_name: str, problem_number: int
    ) -> ProblemDetail | None:
        return self.client(class_name).get_problem(set_name, problem_number)

    def submit_answer(
        self,
        class_name: str,
        set_name: str,
        problem_number: int,
        answers: dict[str, str],
    ) -> dict:
        return self.client(class_name).submit_answer(set_name, problem_number, answers)

    def preview_answer(
        self,
        class_name: str,
        set_name: str,
        problem_number: int,
        answers: dict[str, str],
    ) -> dict:
        return self.client(class_name).preview_answer(set_name, problem_number, answers)

    def get_grades(self, class_name: str) -> list[ClassGrade]:
        return self.client(class_name).get_grades()

    def get_course_info(self, class_name: str) -> dict:
        return self.client(class_name).get_course_info()

    def get_all_courses_info(self) -> list[dict]:
        """Return get_course_info for every configured class."""
        return [self.client(name).get_course_info() for name in self._clients]

    def download_hardcopy(
        self,
        class_name: str,
        set_name: str,
        save_dir: str | Path = ".",
        include_answers: bool = True,
        include_comments: bool = False,
    ) -> dict:
        return self.client(class_name).download_hardcopy(
            set_name, save_dir, include_answers, include_comments
        )
