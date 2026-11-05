"""Thin, defensive client for the public Speedrun.com REST API.

The client normalises the raw JSON payloads into small, template-friendly
dictionaries and always returns a structured result::

    {"ok": bool, "data": ..., "error": str | None, "total": int,
     "status_code": int | None}

Network failures (timeouts, connection errors, rate limits, redirects,
malformed JSON and unexpected payload shapes) never raise: they are reported
through the ``ok``/``error`` pair so views can degrade gracefully.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlparse

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "SpeedrunHub/1.0 (Django demo; +https://www.speedrun.com)"

TIMEOUT_ERROR = (
    "The Speedrun.com API took too long to respond. Please try again in a moment."
)
CONNECTION_ERROR = (
    "Could not reach the Speedrun.com API. Check your connection and try again."
)
RATE_LIMIT_ERROR = (
    "Speedrun.com is rate limiting requests right now. Please try again shortly."
)
GENERIC_ERROR = "The Speedrun.com API returned an unexpected response."
INVALID_PAYLOAD_ERROR = "The Speedrun.com API returned data we could not read."
NOT_FOUND_ERROR = "The requested Speedrun.com resource was not found."
REDIRECT_ERROR = "The Speedrun.com API returned an unexpected redirect."
INVALID_ID_ERROR = "The Speedrun.com identifier was not valid."

# Speedrun.com identifiers are short alphanumeric strings (for example
# ``o1y9wo6q``). Rejecting anything else prevents path traversal and header
# injection through URL segments.
_ID_PATTERN = re.compile(r"^[A-Za-z0-9]+$")

# Keep retries short so a slow upstream never makes a page hang.
DEFAULT_RETRY_DELAY_SECONDS = 0.5
MAX_RETRY_DELAY_SECONDS = 2.0


def _error(
    message: str, total: int = 0, status_code: int | None = None
) -> dict[str, Any]:
    """Build a consistent failure envelope."""
    return {
        "ok": False,
        "data": None,
        "error": message,
        "total": total,
        "status_code": status_code,
    }


def _success(
    data: Any, total: int = 0, status_code: int | None = 200
) -> dict[str, Any]:
    """Build a consistent success envelope."""
    return {
        "ok": True,
        "data": data,
        "error": None,
        "total": total,
        "status_code": status_code,
    }


def _safe_url(value: Any) -> str:
    """Return ``value`` only when it is an absolute http(s) URL.

    Anything else (``javascript:``, ``data:``, relative paths, non-strings)
    becomes an empty string so it can never reach a template.
    """
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if not value:
        return ""
    try:
        parsed = urlparse(value)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        return ""
    return value


def _validated_id(value: Any) -> str | None:
    """Return a normalised Speedrun.com ID or ``None`` when invalid."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or not _ID_PATTERN.fullmatch(value):
        return None
    return value


class SpeedrunAPIClient:
    """Small wrapper around ``requests.Session`` with caching and normalisation."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
        cache_ttl: int | None = None,
    ) -> None:
        self.base_url = (
            base_url or settings.SPEEDRUN_API_BASE_URL or "https://www.speedrun.com/api/v1"
        ).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.SPEEDRUN_API_KEY
        self.timeout = timeout if timeout is not None else settings.SPEEDRUN_API_TIMEOUT
        self.cache_ttl = cache_ttl if cache_ttl is not None else settings.SPEEDRUN_CACHE_TTL
        self.user_agent = (
            os.environ.get("SPEEDRUN_USER_AGENT", "")
            or getattr(settings, "SPEEDRUN_USER_AGENT", "")
            or DEFAULT_USER_AGENT
        )

        # A Session is not guaranteed to be thread-safe. Each worker thread gets
        # its own session with the same headers/timeout configuration.
        self._local = threading.local()

    @property
    def session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update(
                {
                    "User-Agent": self.user_agent,
                    "Accept": "application/json",
                }
            )
            if self.api_key:
                session.headers["X-API-Key"] = self.api_key
            self._local.session = session
        return session

    # ------------------------------------------------------------------
    # Low level request + cache plumbing
    # ------------------------------------------------------------------
    def _cache_key(self, path: str, params: dict[str, Any]) -> str:
        """Cache key that includes the base URL, path and every query param."""
        fingerprint = json.dumps(
            {"base": self.base_url, "path": path, "params": params},
            sort_keys=True,
            default=str,
        )
        digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
        return f"speedrun-hub:api:{digest}"

    @staticmethod
    def _retry_delay(response: Any) -> float:
        """Return a short delay, honouring ``Retry-After`` when usable."""
        headers = getattr(response, "headers", None)
        retry_after = None
        if isinstance(headers, dict):
            retry_after = headers.get("Retry-After") or headers.get("retry-after")
        elif headers is not None:
            try:
                retry_after = headers.get("Retry-After")
            except (AttributeError, TypeError):
                retry_after = None
        if retry_after is not None:
            try:
                delay = float(retry_after)
            except (TypeError, ValueError):
                delay = None
            if delay is not None:
                return max(0.0, min(delay, MAX_RETRY_DELAY_SECONDS))
        return DEFAULT_RETRY_DELAY_SECONDS

    def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Perform a cached GET request and return the raw parsed payload."""
        params = params or {}
        cache_key = self._cache_key(path, params)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        url = f"{self.base_url}{path}"
        request_timeout = timeout if timeout is not None else self.timeout

        response = None
        for attempt in range(2):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=request_timeout,
                    # Never follow redirects: the optional X-API-Key header must
                    # not be forwarded to another host.
                    allow_redirects=False,
                )
            except requests.Timeout:
                logger.warning("Speedrun API timeout for %s", url)
                return _error(TIMEOUT_ERROR)
            except requests.RequestException as exc:
                logger.warning("Speedrun API connection error for %s: %s", url, exc)
                return _error(CONNECTION_ERROR)

            transient = response.status_code == 429 or (
                500 <= response.status_code < 600
            )
            if attempt == 0 and transient:
                time.sleep(self._retry_delay(response))
                continue
            break

        status = response.status_code
        if 300 <= status < 400:
            logger.warning("Speedrun API returned redirect HTTP %s for %s", status, url)
            return _error(REDIRECT_ERROR, status_code=status)
        if status == 404:
            logger.warning("Speedrun API resource not found for %s", url)
            return _error(NOT_FOUND_ERROR, status_code=status)
        if status == 429:
            logger.warning("Speedrun API rate limit hit for %s", url)
            return _error(RATE_LIMIT_ERROR, status_code=status)
        if status != 200:
            logger.warning("Speedrun API returned HTTP %s for %s", status, url)
            return _error(
                f"{GENERIC_ERROR} (HTTP {status})", status_code=status
            )

        try:
            payload = response.json()
        except ValueError:
            logger.warning("Speedrun API returned invalid JSON for %s", url)
            return _error(INVALID_PAYLOAD_ERROR, status_code=status)

        if not isinstance(payload, dict):
            logger.warning("Speedrun API returned a non-object payload for %s", url)
            return _error(INVALID_PAYLOAD_ERROR, status_code=status)

        pagination = payload.get("pagination")
        if not isinstance(pagination, dict):
            pagination = {}

        total_known = False
        total = 0
        if "total" in pagination:
            try:
                total = int(pagination.get("total"))
                total_known = True
            except (TypeError, ValueError):
                total_known = False
                total = 0

        # The live Speedrun.com API omits ``pagination.total`` for /games and
        # exposes a ``next`` link instead. Track both shapes so pagination
        # works whether or not an exact total is available.
        links = pagination.get("links")
        if not isinstance(links, list):
            links = []
        has_next = any(
            isinstance(link, dict) and link.get("rel") == "next"
            for link in links
        )

        result = _success(payload, total, status_code=status)
        result["total_known"] = total_known
        result["has_next"] = has_next
        if self.cache_ttl > 0:
            cache.set(cache_key, result, self.cache_ttl)
        return result

    # ------------------------------------------------------------------
    # Normalisers
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_game(raw: Any) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            return None

        assets = raw.get("assets")
        if not isinstance(assets, dict):
            assets = {}

        def asset_uri(key: str) -> str:
            asset = assets.get(key)
            if not isinstance(asset, dict):
                return ""
            return _safe_url(asset.get("uri"))

        names = raw.get("names")
        if not isinstance(names, dict):
            names = {}

        abbreviation = raw.get("abbreviation")
        if not isinstance(abbreviation, str):
            abbreviation = ""

        name = names.get("international")
        if not isinstance(name, str) or not name.strip():
            name = abbreviation or "Unknown game"

        # ``release-date`` is an ISO date string while ``released`` may be a
        # Unix timestamp. Prefer the readable date and fall back gracefully.
        released = raw.get("release-date") or raw.get("released") or ""
        if isinstance(released, (int, float)):
            try:
                released = datetime.fromtimestamp(
                    released, tz=timezone.utc
                ).strftime("%Y-%m-%d")
            except (OverflowError, OSError, ValueError):
                released = ""
        elif not isinstance(released, str):
            released = ""
        release_year = released[:4] if released else ""

        game_id = raw.get("id")
        if not isinstance(game_id, str):
            game_id = ""

        return {
            "id": game_id,
            "name": name,
            "abbreviation": abbreviation,
            "weblink": _safe_url(raw.get("weblink")),
            "released": released,
            "release_year": release_year,
            "cover": asset_uri("cover-medium") or asset_uri("cover-small"),
            "background": asset_uri("background"),
        }

    @staticmethod
    def _normalize_category(raw: Any) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            return None

        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            name = "Unnamed category"

        category_type = raw.get("type")
        if not isinstance(category_type, str) or not category_type:
            category_type = "per-game"

        rules = raw.get("rules")
        if not isinstance(rules, str):
            rules = ""

        category_id = raw.get("id")
        if not isinstance(category_id, str):
            category_id = ""

        return {
            "id": category_id,
            "name": name,
            "type": category_type,
            "miscellaneous": bool(raw.get("miscellaneous")),
            "weblink": _safe_url(raw.get("weblink")),
            "rules": rules,
        }

    @staticmethod
    def extract_player_names(
        players: Any,
        user_name_map: dict[str, str] | None = None,
    ) -> str:
        """Resolve run players into a readable, comma-separated string.

        Handles embedded user relations, guests and unknown runners. Malformed
        player payloads are skipped instead of raising.
        """
        user_name_map = user_name_map if isinstance(user_name_map, dict) else {}
        if not isinstance(players, list):
            players = []

        names: list[str] = []
        for player in players:
            if not isinstance(player, dict):
                continue
            relation = player.get("rel")
            player_id = player.get("id")
            if not isinstance(player_id, str):
                player_id = None
            if relation == "user":
                names.append(user_name_map.get(player_id) or "Unknown runner")
            elif relation == "guest":
                guest_name = player.get("name")
                names.append(
                    guest_name if isinstance(guest_name, str) and guest_name else "Unknown runner"
                )
            else:
                player_name = player.get("name")
                names.append(
                    (player_name if isinstance(player_name, str) and player_name else None)
                    or user_name_map.get(player_id)
                    or "Unknown runner"
                )
        return ", ".join(names) if names else "Unknown runner"

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------
    def get_games(
        self, query: str | None = None, limit: int = 12, offset: int = 0
    ) -> dict[str, Any]:
        """Return a paginated, normalised list of games."""
        try:
            limit = max(1, min(int(limit), 50))
        except (TypeError, ValueError):
            limit = 12
        try:
            offset = max(0, int(offset))
        except (TypeError, ValueError):
            offset = 0

        params: dict[str, Any] = {"max": limit, "offset": offset}
        if query:
            params["name"] = query

        result = self._get("/games", params)
        if not result["ok"]:
            return {
                "ok": False,
                "data": [],
                "error": result["error"],
                "total": 0,
                "status_code": result.get("status_code"),
                "limit": limit,
                "offset": offset,
            }

        payload = result["data"]
        raw_games = payload.get("data")
        if raw_games is None:
            raw_games = []
        elif not isinstance(raw_games, list):
            return {
                "ok": False,
                "data": [],
                "error": INVALID_PAYLOAD_ERROR,
                "total": 0,
                "status_code": result.get("status_code"),
                "limit": limit,
                "offset": offset,
            }

        games = []
        for item in raw_games:
            game = self._normalize_game(item)
            if game is not None:
                games.append(game)

        total_known = result.get("total_known", False)
        has_next = result.get("has_next", False)
        total = result["total"]
        if not total_known:
            # Without an exact total, expose a lower bound so templates can
            # still reason about counts and pagination safely.
            total = offset + len(games) + (1 if has_next else 0)
        elif offset + limit < total:
            has_next = True

        return {
            "ok": True,
            "data": games,
            "error": None,
            "total": total,
            "status_code": result.get("status_code"),
            "total_known": total_known,
            "has_next": has_next,
            "limit": limit,
            "offset": offset,
        }

    def get_game(self, game_id: str) -> dict[str, Any]:
        """Return one normalised game."""
        safe_id = _validated_id(game_id)
        if safe_id is None:
            return _error(INVALID_ID_ERROR)

        result = self._get(f"/games/{quote(safe_id, safe='')}")
        if not result["ok"]:
            return {
                "ok": False,
                "data": None,
                "error": result["error"],
                "total": 0,
                "status_code": result.get("status_code"),
            }

        raw = result["data"].get("data")
        game = self._normalize_game(raw)
        if game is None:
            return _error(
                GENERIC_ERROR, status_code=result.get("status_code")
            )
        return _success(game, 1, status_code=result.get("status_code"))

    def get_categories(self, game_id: str) -> dict[str, Any]:
        """Return the normalised category list for a game."""
        safe_id = _validated_id(game_id)
        if safe_id is None:
            return {
                "ok": False,
                "data": [],
                "error": INVALID_ID_ERROR,
                "total": 0,
                "status_code": None,
            }

        result = self._get(f"/games/{quote(safe_id, safe='')}/categories")
        if not result["ok"]:
            return {
                "ok": False,
                "data": [],
                "error": result["error"],
                "total": 0,
                "status_code": result.get("status_code"),
            }

        raw_categories = result["data"].get("data")
        if raw_categories is None:
            raw_categories = []
        elif not isinstance(raw_categories, list):
            return {
                "ok": False,
                "data": [],
                "error": INVALID_PAYLOAD_ERROR,
                "total": 0,
                "status_code": result.get("status_code"),
            }

        categories = []
        for item in raw_categories:
            category = self._normalize_category(item)
            if category is not None:
                categories.append(category)

        return _success(
            categories, len(categories), status_code=result.get("status_code")
        )

    def get_leaderboard(
        self,
        game_id: str,
        category_id: str,
        top: int = 3,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Return the top runs for a category with resolved player names."""
        safe_game_id = _validated_id(game_id)
        safe_category_id = _validated_id(category_id)
        if safe_game_id is None or safe_category_id is None:
            return {
                "ok": False,
                "data": [],
                "error": INVALID_ID_ERROR,
                "total": 0,
                "status_code": None,
            }

        try:
            top = max(1, min(int(top), 10))
        except (TypeError, ValueError):
            top = 3

        params = {"top": top, "embed": "players"}
        result = self._get(
            f"/leaderboards/{quote(safe_game_id, safe='')}"
            f"/category/{quote(safe_category_id, safe='')}",
            params,
            timeout=timeout,
        )
        if not result["ok"]:
            return {
                "ok": False,
                "data": [],
                "error": result["error"],
                "total": 0,
                "status_code": result.get("status_code"),
            }

        payload = result["data"].get("data")
        if not isinstance(payload, dict):
            return _error(
                GENERIC_ERROR, status_code=result.get("status_code")
            )

        raw_runs = payload.get("runs")
        if raw_runs is None:
            raw_runs = []
        elif not isinstance(raw_runs, list):
            return {
                "ok": False,
                "data": [],
                "error": INVALID_PAYLOAD_ERROR,
                "total": 0,
                "status_code": result.get("status_code"),
            }

        players_block = payload.get("players")
        embedded_players = []
        if isinstance(players_block, dict):
            embedded = players_block.get("data")
            if isinstance(embedded, list):
                embedded_players = embedded

        user_name_map: dict[str, str] = {}
        for player in embedded_players:
            if not isinstance(player, dict):
                continue
            player_id = player.get("id")
            if not isinstance(player_id, str):
                continue
            names = player.get("names")
            if not isinstance(names, dict):
                names = {}
            name = names.get("international") or player.get("name")
            if not isinstance(name, str) or not name:
                name = "Unknown runner"
            user_name_map[player_id] = name

        runs = []
        for entry in raw_runs:
            if not isinstance(entry, dict):
                continue
            run = entry.get("run")
            if not isinstance(run, dict):
                run = {}
            times = run.get("times")
            if not isinstance(times, dict):
                times = {}
            primary = times.get("primary_t")
            if primary is None:
                primary = times.get("realtime_t")
            if primary is None:
                primary = times.get("ingame_t")
            players = run.get("players")
            if not isinstance(players, list):
                players = []
            runs.append(
                {
                    "place": entry.get("place"),
                    "player_name": self.extract_player_names(
                        players, user_name_map
                    ),
                    "time_seconds": primary,
                    "weblink": _safe_url(run.get("weblink")),
                }
            )

        return _success(runs, len(runs), status_code=result.get("status_code"))


def get_client() -> SpeedrunAPIClient:
    """Return a fresh client bound to the current settings.

    A new client per request keeps configuration changes (and test overrides)
    predictable while the client itself keeps one ``requests.Session`` per
    thread for safe concurrent leaderboard fetching.
    """
    return SpeedrunAPIClient()
