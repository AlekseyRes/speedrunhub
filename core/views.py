"""Views for the Speedrun Hub home, explorer and game detail pages."""

import logging
from concurrent.futures import ThreadPoolExecutor, wait
from urllib.parse import urlencode

from django.shortcuts import redirect, render

from .services.speedrun_api import get_client

logger = logging.getLogger(__name__)

EXPLORER_PAGE_SIZE = 12
HOME_FEATURED_LIMIT = 6
MAX_LEADERBOARD_FETCHES = 4
LEADERBOARD_TIMEOUT = 5.0
LEADERBOARD_OVERALL_BUDGET = 6.0
LEADERBOARD_TIMEOUT_ERROR = (
    "This leaderboard took too long to load. Open it on Speedrun.com to see the runs."
)
LEADERBOARD_GENERIC_ERROR = (
    "This leaderboard could not be loaded right now. Try again in a moment."
)


def home(request):
    """Landing page with hero, CTAs and live Speedrun.com stats."""
    api = get_client()
    result = api.get_games(limit=HOME_FEATURED_LIMIT, offset=0)

    context = {
        "featured_games": result["data"] if result["ok"] else [],
        "total_games": result["total"] if result["ok"] else 0,
        "total_known": result.get("total_known", False) if result["ok"] else False,
        "api_error": None if result["ok"] else result["error"],
    }
    return render(request, "core/home.html", context)


def explorer(request):
    """Searchable, paginated game browser."""
    query = (request.GET.get("name") or "").strip()
    try:
        page = int(request.GET.get("page", "1"))
    except (TypeError, ValueError):
        page = 1
    page = max(page, 1)

    offset = (page - 1) * EXPLORER_PAGE_SIZE
    api = get_client()
    result = api.get_games(
        query=query or None, limit=EXPLORER_PAGE_SIZE, offset=offset
    )

    total = result["total"] if result["ok"] else 0
    total_known = result.get("total_known", False) if result["ok"] else False
    games = result["data"] if result["ok"] else []

    def page_url(target_page):
        params = {"page": target_page}
        if query:
            params["name"] = query
        return f"?{urlencode(params)}"

    # Never strand a visitor past the last page. When the upstream reports a
    # total, redirect to the last valid page instead of showing an empty grid.
    if result["ok"] and total_known and page > 1 and offset >= total:
        last_page = max(1, (total + EXPLORER_PAGE_SIZE - 1) // EXPLORER_PAGE_SIZE)
        if last_page < page:
            return redirect(f"{request.path}{page_url(last_page)}")

    has_previous = page > 1
    has_next = result["ok"] and result.get("has_next", False)

    context = {
        "games": games,
        "query": query,
        "page": page,
        "total": total,
        "total_known": total_known,
        "result_count": len(games),
        "has_previous": has_previous,
        "has_next": has_next,
        "previous_url": page_url(page - 1) if has_previous else "",
        "next_url": page_url(page + 1) if has_next else "",
        "api_error": None if result["ok"] else result["error"],
    }
    return render(request, "core/explorer.html", context)


def _attach_leaderboards(api, game_id, categories):
    """Fetch up to four per-game leaderboards concurrently.

    Failures are isolated per category so one slow or broken leaderboard never
    prevents the rest of the page from rendering.
    """
    targets = []
    for category in categories:
        if category["type"] != "per-game":
            # Per-level categories need extra variable/level lookups that the
            # public API does not expose in one call. Link out instead.
            category["top_runs"] = None
            category["leaderboard_error"] = None
            continue
        if len(targets) >= MAX_LEADERBOARD_FETCHES:
            category["top_runs"] = None
            category["leaderboard_error"] = None
            continue
        targets.append(category)

    if not targets:
        return

    executor = ThreadPoolExecutor(max_workers=MAX_LEADERBOARD_FETCHES)
    try:
        futures = {
            executor.submit(
                api.get_leaderboard,
                game_id,
                category["id"],
                top=3,
                timeout=LEADERBOARD_TIMEOUT,
            ): category
            for category in targets
        }
        done, _ = wait(futures, timeout=LEADERBOARD_OVERALL_BUDGET)

        for future, category in futures.items():
            if future not in done:
                category["top_runs"] = []
                category["leaderboard_error"] = LEADERBOARD_TIMEOUT_ERROR
                continue
            try:
                leaderboard = future.result()
            except Exception:  # pragma: no cover - defensive isolation
                logger.exception(
                    "Unexpected leaderboard failure for %s/%s",
                    game_id,
                    category["id"],
                )
                category["top_runs"] = []
                category["leaderboard_error"] = LEADERBOARD_GENERIC_ERROR
                continue

            if leaderboard.get("ok"):
                category["top_runs"] = leaderboard.get("data") or []
                category["leaderboard_error"] = None
            else:
                category["top_runs"] = []
                category["leaderboard_error"] = leaderboard.get("error")
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def game_detail(request, game_id):
    """Game overview with categories and top three runs per-game category."""
    api = get_client()
    game_result = api.get_game(game_id)

    context = {
        "game": game_result["data"] if game_result["ok"] else None,
        "game_id": game_id,
        "categories": [],
        "api_error": None,
        "categories_error": None,
        "not_found": False,
    }

    if not game_result["ok"]:
        if game_result.get("status_code") == 404:
            context["not_found"] = True
        else:
            context["api_error"] = game_result["error"]
        return render(request, "core/game_detail.html", context)

    categories_result = api.get_categories(game_id)
    if not categories_result["ok"]:
        context["categories_error"] = categories_result["error"]
        return render(request, "core/game_detail.html", context)

    categories = categories_result["data"]
    _attach_leaderboards(api, game_id, categories)

    context["categories"] = categories
    return render(request, "core/game_detail.html", context)
