from dataclasses import asdict
from typing import Annotated
import logging
import os
import time
from fastmcp import FastMCP
from pydantic import Field
from starlette.requests import Request
from starlette.middleware.base import BaseHTTPMiddleware

from webwork import WeBWorKManager, load_config

LOG_LEVEL = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=LOG_LEVEL, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
logging.getLogger("fastmcp").setLevel(LOG_LEVEL)
logging.getLogger("webwork").setLevel(LOG_LEVEL)
logger = logging.getLogger("webwork.mcp")

# Bootstrap

config = load_config()
manager = WeBWorKManager(config)

mcp = FastMCP(
    "WeBWorK",
    instructions=(
        "You are a helpful homework assistant connected to a WeBWorK "
        "online homework system. You can list classes, homework sets, "
        "due dates, individual problems (with LaTeX), check grades, "
        "download PDF hardcopies, and get course overviews. "
        "This server is read-only — you cannot submit or preview answers."
    ),
)

async def _log_requests(request: Request, call_next):
    client = request.client.host if request.client else "unknown"
    logger.info("HTTP %s %s from %s", request.method, request.url.path, client)
    logger.debug("Headers: %s", dict(request.headers))
    start = time.time()
    response = await call_next(request)
    logger.info(
        "Handled %s %s -> %s in %.3fs",
        request.method,
        request.url.path,
        getattr(response, "status_code", "n/a"),
        time.time() - start,
    )
    return response


if hasattr(mcp, "app"):
    try:
        mcp.app.add_middleware(BaseHTTPMiddleware, dispatch=_log_requests)
        logger.debug("Attached request logging middleware to mcp.app")
    except Exception as e:
        logger.warning("Could not attach middleware to mcp.app: %s", e)
else:
    logger.debug("mcp.app unavailable; request middleware not attached")

def log_tool(func):
    import inspect
    from functools import wraps

    if inspect.iscoroutinefunction(func):

        @wraps(func)
        async def _async_wrapper(*args, **kwargs):
            logger.info("Tool called: %s args=%s kwargs=%s", func.__name__, args, kwargs)
            start = time.time()
            try:
                result = await func(*args, **kwargs)
                logger.info("Tool %s completed in %.3fs", func.__name__, time.time() - start)
                return result
            except Exception:
                logger.exception("Tool %s raised", func.__name__)
                raise

        return _async_wrapper
    else:

        @wraps(func)
        def _sync_wrapper(*args, **kwargs):
            logger.info("Tool called: %s args=%s kwargs=%s", func.__name__, args, kwargs)
            start = time.time()
            try:
                result = func(*args, **kwargs)
                logger.info("Tool %s completed in %.3fs", func.__name__, time.time() - start)
                return result
            except Exception:
                logger.exception("Tool %s raised", func.__name__)
                raise

        return _sync_wrapper

def register_tool(*mcp_args, **mcp_kwargs):
    def decorator(func):
        wrapped = log_tool(func)
        return mcp.tool(*mcp_args, **mcp_kwargs)(wrapped)
    return decorator

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations={"readOnlyHint": True},
    tags={"navigation"},
)
@log_tool
def get_classes() -> list[dict[str, str]]:
    results = []
    for name in manager.get_classes():
        c = manager.client(name)
        results.append(
            {
                "class_name": name,
                "username": c.username,
                "url": c.class_url,
            }
        )
    return results


@mcp.tool(
    annotations={"readOnlyHint": True},
    tags={"navigation"},
)
@log_tool
def get_all_sets(
    class_name: Annotated[
        str, Field(description="The WeBWorK class name, e.g. 'Math221-Vanderlei'")
    ],
) -> list[dict]:
    """
    List every homework set for a class.

    Returns a list of sets with name, url, status, and due_date.
    """
    sets = manager.get_all_sets(class_name)
    return [asdict(s) for s in sets]


@mcp.tool(
    annotations={"readOnlyHint": True},
    tags={"navigation"},
)
@log_tool
def get_open_sets(
    class_name: Annotated[str, Field(description="The WeBWorK class name")],
) -> list[dict]:
    """
    List only the currently-open homework sets for a class.

    Useful for seeing what's available to work on right now.
    """
    sets = manager.get_open_sets(class_name)
    return [asdict(s) for s in sets]


@mcp.tool(
    annotations={"readOnlyHint": True},
    tags={"navigation", "deadlines"},
)
@log_tool
def get_due_dates(
    class_name: Annotated[str, Field(description="The WeBWorK class name")],
) -> list[dict[str, str]]:
    """
    Get due dates for every homework set in a class.

    Returns a list of {name, due_date, status} dicts.
    Useful for planning and prioritising work.
    """
    return manager.get_due_dates(class_name)


@mcp.tool(
    annotations={"readOnlyHint": True},
    tags={"navigation", "deadlines"},
)
@log_tool
def get_upcoming_deadlines(
    class_name: Annotated[str, Field(description="The WeBWorK class name")],
) -> list[dict[str, str]]:
    """
    Get due dates for only the open (upcoming) sets.

    A filtered view of get_due_dates showing only assignments you can
    still submit to.
    """
    sets = manager.get_open_sets(class_name)
    return [{"name": s.name, "due_date": s.due_date, "status": s.status} for s in sets]


@mcp.tool(
    annotations={"readOnlyHint": True},
    tags={"problems"},
)
@log_tool
def get_set_info(
    class_name: Annotated[str, Field(description="The WeBWorK class name")],
    set_name: Annotated[
        str,
        Field(
            description="Exact homework set name, e.g. 'Assignment9 Vector-Geometry'"
        ),
    ],
) -> dict | str:
    """
    Get detailed info for a specific homework set including its full
    problem list with attempt counts, scores, and point values.
    """
    hw = manager.get_set_info(class_name, set_name)
    if hw is None:
        return f"Set '{set_name}' not found in {class_name}."
    return asdict(hw)


@mcp.tool(
    annotations={"readOnlyHint": True},
    tags={"problems"},
)
@log_tool
def get_problem(
    class_name: Annotated[str, Field(description="The WeBWorK class name")],
    set_name: Annotated[str, Field(description="Exact homework set name")],
    problem_number: Annotated[
        int, Field(description="Problem number (1-indexed)", ge=1)
    ],
) -> dict | str:
    """
    Fetch a single problem's full content (read-only).

    Returns the problem statement with inline LaTeX ($...$),
    current attempt count, and remaining attempts.

    Use the 'body_latex' field to read the mathematical content.
    """
    p = manager.get_problem(class_name, set_name, problem_number)
    if p is None:
        return f"Problem {problem_number} not found in '{set_name}'."
    result = asdict(p)
    # Strip submission-related fields — this server is read-only
    result.pop("hidden_fields", None)
    result.pop("answer_fields", None)
    return result


@mcp.tool(
    annotations={"readOnlyHint": True},
    tags={"grades"},
)
@log_tool
def get_grades(
    class_name: Annotated[str, Field(description="The WeBWorK class name")],
) -> list[dict] | str:
    """
    Fetch the grades/scores for all homework sets in a class.

    Returns per-set scores including points earned, total points,
    and percentage.
    """
    grades = manager.get_grades(class_name)
    if not grades:
        return "No grades found (the grades page may have a different format)."
    return [asdict(g) for g in grades]


@mcp.tool(
    annotations={"readOnlyHint": True},
    tags={"problems"},
)
@log_tool
def get_set_progress(
    class_name: Annotated[str, Field(description="The WeBWorK class name")],
    set_name: Annotated[str, Field(description="Exact homework set name")],
) -> dict | str:
    """
    Get a quick progress summary for a homework set: how many problems
    are completed, total points, and which problems still need work.
    """
    hw = manager.get_set_info(class_name, set_name)
    if hw is None:
        return f"Set '{set_name}' not found in {class_name}."

    total_points = sum(p.worth for p in hw.problems)
    earned_points = sum(p.worth for p in hw.problems if p.status == "100%")
    completed = [p.number for p in hw.problems if p.status == "100%"]
    remaining = [p.number for p in hw.problems if p.status != "100%"]

    return {
        "set_name": hw.name,
        "status": hw.status,
        "due_date": hw.due_date,
        "total_problems": len(hw.problems),
        "completed_count": len(completed),
        "total_points": total_points,
        "earned_points": earned_points,
        "percent": f"{earned_points / total_points * 100:.0f}%"
        if total_points
        else "N/A",
        "completed_problems": completed,
        "remaining_problems": remaining,
    }


@mcp.tool(
    annotations={"readOnlyHint": True},
    tags={"navigation"},
)
@log_tool
def get_dashboard() -> list[dict]:
    """
    Get a high-level dashboard across ALL classes: open sets,
    due dates, and quick status. Great as a starting point to
    see what needs attention.
    """
    dashboard: list[dict] = []
    for class_name in manager.get_classes():
        open_sets = manager.get_open_sets(class_name)
        entry: dict = {
            "class": class_name,
            "open_sets": [],
        }
        for s in open_sets:
            entry["open_sets"].append(
                {
                    "name": s.name,
                    "due_date": s.due_date,
                    "status": s.status,
                }
            )
        dashboard.append(entry)
    return dashboard


# ---------------------------------------------------------------------------
# Single-course & all-courses overview
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations={"readOnlyHint": True},
    tags={"navigation", "course"},
)
@log_tool
def get_course_info(
    class_name: Annotated[str, Field(description="The WeBWorK class name")],
) -> dict:
    """
    Get a comprehensive overview of a single class.

    Returns the class name, username, URL, and for every open set:
    due date, problem count, completion progress, and which problems
    are done vs. remaining. Closed sets are listed with their status.

    This is the best starting tool when the user asks about a specific
    course — it gives you everything in one call.
    """
    return manager.get_course_info(class_name)


@mcp.tool(
    annotations={"readOnlyHint": True},
    tags={"navigation", "course"},
)
@log_tool
def get_all_courses_info() -> list[dict]:
    """
    Get a comprehensive overview of ALL enrolled classes at once.

    Calls get_course_info for every configured class and returns
    the combined list. Use this when the user asks something like
    "what do I have due?" or "show me everything" without specifying
    a class.
    """
    return manager.get_all_courses_info()


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
    },
    tags={"problems", "download"},
)
@log_tool
def download_hardcopy(
    class_name: Annotated[str, Field(description="The WeBWorK class name")],
    set_name: Annotated[str, Field(description="Exact homework set name")],
    save_dir: Annotated[
        str,
        Field(
            description=(
                "Directory to save the PDF into. Defaults to current directory."
            ),
        ),
    ] = ".",
    include_answers: Annotated[
        bool,
        Field(description="Include the student's previous answers in the PDF"),
    ] = True,
    include_comments: Annotated[
        bool,
        Field(description="Include grader comments in the PDF"),
    ] = False,
) -> dict:
    """
    Download a PDF hardcopy of a homework set.

    Generates and saves a PDF containing all problems in the set,
    optionally including previous answers and grader comments.
    Returns the file path of the saved PDF.
    """
    return manager.download_hardcopy(
        class_name, set_name, save_dir, include_answers, include_comments
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    
    if os.getenv("ENV") == "PROD":
        mcp.run(transport="http", host=os.getenv("HOST", "0.0.0.0"), port=os.getenv("PORT", 8000))
    else:
        mcp.run()
    