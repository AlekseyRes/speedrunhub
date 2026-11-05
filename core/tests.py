"""Tests for the core views, API client and template filters.

Every external call is mocked: the suite never touches the network.
"""

import threading
from unittest.mock import Mock, patch

import requests
from django.core.cache import cache
from django.test import TestCase, override_settings

from core.services.speedrun_api import SpeedrunAPIClient
from core.templatetags.speedrun_tags import run_time

SAMPLE_GAME = {
    "id": "abc123",
    "name": "Sample Game",
    "abbreviation": "SG",
    "weblink": "https://www.speedrun.com/sample",
    "released": "2017-01-15",
    "release_year": "2017",
    "cover": "https://example.test/cover.jpg",
    "background": "https://example.test/background.jpg",
}

SAMPLE_RUN = {
    "place": 1,
    "player_name": "Speedy",
    "time_seconds": 992.12,
    "weblink": "https://www.speedrun.com/run/1",
}


class HomeViewTests(TestCase):
    def setUp(self):
        cache.clear()

    @patch("core.views.get_client")
    def test_home_renders_with_live_stats(self, mock_get_client):
        api = mock_get_client.return_value
        api.get_games.return_value = {
            "ok": True,
            "data": [SAMPLE_GAME],
            "error": None,
            "total": 42,
            "total_known": True,
            "has_next": False,
        }

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sample Game")
        self.assertContains(response, "42")
        api.get_games.assert_called_once_with(limit=6, offset=0)

    @patch("core.views.get_client")
    def test_home_handles_api_error_gracefully(self, mock_get_client):
        api = mock_get_client.return_value
        api.get_games.return_value = {
            "ok": False,
            "data": [],
            "error": "The Speedrun.com API is offline.",
            "total": 0,
        }

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Live data is unavailable")
        self.assertContains(response, "The Speedrun.com API is offline.")


class ExplorerViewTests(TestCase):
    def setUp(self):
        cache.clear()

    @patch("core.views.get_client")
    def test_explorer_passes_search_query_and_renders_results(
        self, mock_get_client
    ):
        api = mock_get_client.return_value
        api.get_games.return_value = {
            "ok": True,
            "data": [SAMPLE_GAME],
            "error": None,
            "total": 1,
            "total_known": True,
            "has_next": False,
        }

        response = self.client.get("/explorer/", {"name": "mario"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sample Game")
        self.assertContains(response, "mario")
        api.get_games.assert_called_once_with(
            query="mario", limit=12, offset=0
        )

    @patch("core.views.get_client")
    def test_explorer_uses_page_for_offset(self, mock_get_client):
        api = mock_get_client.return_value
        api.get_games.return_value = {
            "ok": True,
            "data": [SAMPLE_GAME],
            "error": None,
            "total": 40,
            "total_known": True,
            "has_next": True,
        }

        response = self.client.get(
            "/explorer/", {"name": "mario", "page": "2"}
        )

        self.assertEqual(response.status_code, 200)
        api.get_games.assert_called_once_with(
            query="mario", limit=12, offset=12
        )
        self.assertContains(response, "Next")

    @patch("core.views.get_client")
    def test_explorer_shows_error_banner(self, mock_get_client):
        api = mock_get_client.return_value
        api.get_games.return_value = {
            "ok": False,
            "data": [],
            "error": "Rate limited.",
            "total": 0,
        }

        response = self.client.get("/explorer/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Could not load games")
        self.assertContains(response, "Rate limited.")

    @patch("core.views.get_client")
    def test_explorer_clamps_page_below_one(self, mock_get_client):
        api = mock_get_client.return_value
        api.get_games.return_value = {
            "ok": True,
            "data": [SAMPLE_GAME],
            "error": None,
            "total": 1,
            "total_known": True,
            "has_next": False,
        }

        response = self.client.get("/explorer/", {"page": "0"})

        self.assertEqual(response.status_code, 200)
        api.get_games.assert_called_once_with(query=None, limit=12, offset=0)

    @patch("core.views.get_client")
    def test_explorer_redirects_past_last_page(self, mock_get_client):
        api = mock_get_client.return_value
        api.get_games.return_value = {
            "ok": True,
            "data": [],
            "error": None,
            "total": 40,
            "total_known": True,
            "has_next": False,
        }

        response = self.client.get(
            "/explorer/", {"page": "999", "name": "mario"}
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("page=4", response.url)
        self.assertIn("name=mario", response.url)

    @patch("core.views.get_client")
    def test_explorer_empty_state_past_unknown_total_shows_previous(
        self, mock_get_client
    ):
        api = mock_get_client.return_value
        api.get_games.return_value = {
            "ok": True,
            "data": [],
            "error": None,
            "total": 0,
            "total_known": False,
            "has_next": False,
        }

        response = self.client.get("/explorer/", {"page": "5"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No games found")
        self.assertContains(response, "Previous")


class GameDetailViewTests(TestCase):
    def setUp(self):
        cache.clear()

    @patch("core.views.get_client")
    def test_game_detail_renders_categories_and_limits_leaderboards(
        self, mock_get_client
    ):
        per_game_categories = [
            {
                "id": f"cat-{index}",
                "name": f"Category {index}",
                "type": "per-game",
                "miscellaneous": False,
                "weblink": f"https://www.speedrun.com/cat-{index}",
                "rules": "",
            }
            for index in range(5)
        ]
        per_level_category = {
            "id": "levels",
            "name": "Individual Levels",
            "type": "per-level",
            "miscellaneous": False,
            "weblink": "https://www.speedrun.com/levels",
            "rules": "",
        }

        api = mock_get_client.return_value
        api.get_game.return_value = {
            "ok": True,
            "data": SAMPLE_GAME,
            "error": None,
            "total": 1,
        }
        api.get_categories.return_value = {
            "ok": True,
            "data": per_game_categories + [per_level_category],
            "error": None,
            "total": 6,
        }
        api.get_leaderboard.return_value = {
            "ok": True,
            "data": [SAMPLE_RUN],
            "error": None,
            "total": 1,
        }

        response = self.client.get("/explorer/game/abc123/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sample Game")
        self.assertContains(response, "Speedy")
        self.assertContains(response, "16:32.120")
        self.assertContains(response, "Per-level")
        # Only four per-game categories may trigger a leaderboard fetch.
        self.assertEqual(api.get_leaderboard.call_count, 4)
        called_category_ids = {
            call.args[1] for call in api.get_leaderboard.call_args_list
        }
        self.assertNotIn("levels", called_category_ids)

    @patch("core.views.get_client")
    def test_game_detail_handles_category_error(self, mock_get_client):
        api = mock_get_client.return_value
        api.get_game.return_value = {
            "ok": True,
            "data": SAMPLE_GAME,
            "error": None,
            "total": 1,
        }
        api.get_categories.return_value = {
            "ok": False,
            "data": [],
            "error": "Categories are temporarily unavailable.",
            "total": 0,
        }

        response = self.client.get("/explorer/game/abc123/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sample Game")
        self.assertContains(response, "Categories are temporarily unavailable.")
        api.get_leaderboard.assert_not_called()

    @patch("core.views.get_client")
    def test_game_detail_handles_missing_game(self, mock_get_client):
        api = mock_get_client.return_value
        api.get_game.return_value = {
            "ok": False,
            "data": None,
            "error": "Game not found.",
            "total": 0,
        }

        response = self.client.get("/explorer/game/missing/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Could not load this game")
        api.get_categories.assert_not_called()

    @patch("core.views.get_client")
    def test_game_detail_upstream_404_shows_friendly_not_found(
        self, mock_get_client
    ):
        api = mock_get_client.return_value
        api.get_game.return_value = {
            "ok": False,
            "data": None,
            "error": "The requested Speedrun.com resource was not found.",
            "total": 0,
            "status_code": 404,
        }

        response = self.client.get("/explorer/game/missing/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Game not found")
        self.assertNotContains(response, "Could not load this game")
        api.get_categories.assert_not_called()

    @patch("core.views.get_client")
    def test_game_detail_isolates_a_single_leaderboard_failure(
        self, mock_get_client
    ):
        categories = [
            {
                "id": "cat-0",
                "name": "Any%",
                "type": "per-game",
                "miscellaneous": False,
                "weblink": "https://www.speedrun.com/cat-0",
                "rules": "",
            },
            {
                "id": "cat-1",
                "name": "100%",
                "type": "per-game",
                "miscellaneous": False,
                "weblink": "https://www.speedrun.com/cat-1",
                "rules": "",
            },
        ]

        def leaderboard(game_id, category_id, **kwargs):
            if category_id == "cat-1":
                return {
                    "ok": False,
                    "data": [],
                    "error": "Leaderboard unavailable.",
                    "total": 0,
                }
            return {
                "ok": True,
                "data": [SAMPLE_RUN],
                "error": None,
                "total": 1,
            }

        api = mock_get_client.return_value
        api.get_game.return_value = {
            "ok": True,
            "data": SAMPLE_GAME,
            "error": None,
            "total": 1,
        }
        api.get_categories.return_value = {
            "ok": True,
            "data": categories,
            "error": None,
            "total": 2,
        }
        api.get_leaderboard.side_effect = leaderboard

        response = self.client.get("/explorer/game/abc123/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Leaderboard unavailable.")
        self.assertContains(response, "Speedy")
        self.assertEqual(api.get_leaderboard.call_count, 2)


@override_settings(SPEEDRUN_CACHE_TTL=0)
class SpeedrunAPIClientTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = SpeedrunAPIClient(
            base_url="https://example.test/api/v1",
            api_key="",
            timeout=1,
            cache_ttl=0,
        )

    def test_timeout_returns_structured_error(self):
        with patch.object(
            self.client.session, "get", side_effect=requests.Timeout
        ):
            result = self.client.get_games()

        self.assertFalse(result["ok"])
        self.assertEqual(result["data"], [])
        self.assertIn("too long", result["error"])

    def test_connection_error_returns_structured_error(self):
        with patch.object(
            self.client.session,
            "get",
            side_effect=requests.ConnectionError,
        ):
            result = self.client.get_game("abc123")

        self.assertFalse(result["ok"])
        self.assertIsNone(result["data"])
        self.assertIn("Could not reach", result["error"])

    def test_http_error_returns_structured_error(self):
        response = Mock(status_code=500)
        with patch.object(self.client.session, "get", return_value=response):
            result = self.client.get_categories("abc123")

        self.assertFalse(result["ok"])
        self.assertEqual(result["data"], [])
        self.assertIn("HTTP 500", result["error"])

    def test_rate_limit_returns_structured_error(self):
        response = Mock(status_code=429)
        with patch.object(self.client.session, "get", return_value=response):
            result = self.client.get_leaderboard("abc123", "cat1")

        self.assertFalse(result["ok"])
        self.assertIn("rate limiting", result["error"])

    def test_get_games_normalises_payload_and_pagination(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "data": [
                {
                    "id": "abc123",
                    "names": {"international": "Sample Game"},
                    "abbreviation": "SG",
                    "weblink": "https://www.speedrun.com/sample",
                    "released": "2017-01-15",
                    "assets": {
                        "cover-medium": {"uri": "https://example.test/cover.jpg"},
                        "background": {"uri": "https://example.test/bg.jpg"},
                    },
                }
            ],
            "pagination": {"offset": 0, "max": 12, "size": 1, "total": 99},
        }

        with patch.object(self.client.session, "get", return_value=response):
            result = self.client.get_games(query="sample", limit=12, offset=0)

        self.assertTrue(result["ok"])
        self.assertEqual(result["total"], 99)
        self.assertEqual(result["data"][0]["name"], "Sample Game")
        self.assertEqual(result["data"][0]["release_year"], "2017")
        self.assertEqual(
            result["data"][0]["cover"], "https://example.test/cover.jpg"
        )

    def test_get_games_handles_missing_total_with_next_link(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "data": [SAMPLE_GAME],
            "pagination": {
                "offset": 0,
                "max": 12,
                "size": 1,
                "links": [{"rel": "next", "uri": "https://example.test/next"}],
            },
        }

        with patch.object(self.client.session, "get", return_value=response):
            result = self.client.get_games(limit=12, offset=0)

        self.assertTrue(result["ok"])
        self.assertFalse(result["total_known"])
        self.assertTrue(result["has_next"])
        self.assertEqual(result["total"], 2)

    def test_get_game_handles_unix_timestamp_release_date(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "data": {
                "id": "abc123",
                "names": {"international": "Sample Game"},
                "released": 1484438400,
            }
        }

        with patch.object(self.client.session, "get", return_value=response):
            result = self.client.get_game("abc123")

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["released"], "2017-01-15")
        self.assertEqual(result["data"]["release_year"], "2017")

    def test_get_leaderboard_resolves_players_and_guest_names(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "data": {
                "runs": [
                    {
                        "place": 1,
                        "run": {
                            "times": {"primary_t": 120.5},
                            "weblink": "https://www.speedrun.com/run/1",
                            "players": [{"rel": "user", "id": "user-1"}],
                        },
                    },
                    {
                        "place": 2,
                        "run": {
                            "times": {"primary_t": 130},
                            "weblink": "https://www.speedrun.com/run/2",
                            "players": [
                                {"rel": "guest", "name": "Guest Runner"}
                            ],
                        },
                    },
                ],
                "players": {
                    "data": [
                        {
                            "id": "user-1",
                            "names": {"international": "Speedy"},
                        }
                    ]
                },
            }
        }

        with patch.object(self.client.session, "get", return_value=response):
            result = self.client.get_leaderboard("abc123", "cat1", top=3)

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"][0]["player_name"], "Speedy")
        self.assertEqual(result["data"][1]["player_name"], "Guest Runner")
        self.assertEqual(result["data"][0]["time_seconds"], 120.5)

    def test_extract_player_names_falls_back_to_unknown(self):
        names = SpeedrunAPIClient.extract_player_names(
            [{"rel": "user", "id": "missing"}], {}
        )
        self.assertEqual(names, "Unknown runner")

    def test_api_key_header_is_sent_when_configured(self):
        client = SpeedrunAPIClient(
            base_url="https://example.test/api/v1",
            api_key="secret-key",
            timeout=1,
            cache_ttl=0,
        )
        self.assertEqual(client.session.headers["X-API-Key"], "secret-key")

    @override_settings(SPEEDRUN_CACHE_TTL=300)
    def test_successful_response_is_cached(self):
        cached_client = SpeedrunAPIClient(
            base_url="https://example.test/api/v1",
            api_key="",
            timeout=1,
            cache_ttl=300,
        )
        response = Mock(status_code=200)
        response.json.return_value = {
            "data": [],
            "pagination": {"offset": 0, "max": 12, "size": 0, "total": 0},
        }

        with patch.object(
            cached_client.session, "get", return_value=response
        ) as mocked_get:
            cached_client.get_games(query="mario")
            cached_client.get_games(query="mario")

        self.assertEqual(mocked_get.call_count, 1)

    def test_non_object_json_payload_returns_structured_error(self):
        response = Mock(status_code=200)
        response.json.return_value = ["unexpected", "list"]

        with patch.object(self.client.session, "get", return_value=response):
            result = self.client.get_games()

        self.assertFalse(result["ok"])
        self.assertEqual(result["data"], [])
        self.assertIn("could not read", result["error"])

    def test_non_list_data_payload_returns_structured_error(self):
        response = Mock(status_code=200)
        response.json.return_value = {"data": "not-a-list"}

        with patch.object(self.client.session, "get", return_value=response):
            result = self.client.get_games()

        self.assertFalse(result["ok"])
        self.assertEqual(result["data"], [])
        self.assertIn("could not read", result["error"])

    def test_invalid_json_returns_structured_error(self):
        response = Mock(status_code=200)
        response.json.side_effect = ValueError("invalid json")

        with patch.object(self.client.session, "get", return_value=response):
            result = self.client.get_game("abc123")

        self.assertFalse(result["ok"])
        self.assertIsNone(result["data"])
        self.assertIn("could not read", result["error"])

    def test_unexpected_nested_shapes_do_not_raise(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "data": [
                {
                    "id": "abc123",
                    "names": "not-a-dict",
                    "assets": ["not-a-dict"],
                    "weblink": ["not-a-string"],
                    "released": {"unexpected": True},
                }
            ],
            "pagination": ["not-a-dict"],
        }

        with patch.object(self.client.session, "get", return_value=response):
            result = self.client.get_games()

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"][0]["name"], "Unknown game")
        self.assertEqual(result["data"][0]["cover"], "")
        self.assertEqual(result["data"][0]["background"], "")
        self.assertEqual(result["data"][0]["weblink"], "")

    def test_leaderboard_unexpected_shapes_do_not_raise(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "data": {
                "runs": [
                    {"place": 1, "run": "not-a-dict"},
                    {
                        "place": 2,
                        "run": {
                            "times": ["bad"],
                            "players": "bad",
                            "weblink": "javascript:alert(1)",
                        },
                    },
                    "not-a-dict",
                ],
                "players": "not-a-dict",
            }
        }

        with patch.object(self.client.session, "get", return_value=response):
            result = self.client.get_leaderboard("abc123", "cat1")

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["data"]), 2)
        self.assertEqual(result["data"][0]["player_name"], "Unknown runner")
        self.assertEqual(result["data"][1]["weblink"], "")

    def test_404_returns_friendly_not_found(self):
        response = Mock(status_code=404)

        with patch.object(self.client.session, "get", return_value=response):
            result = self.client.get_game("abc123")

        self.assertFalse(result["ok"])
        self.assertEqual(result["status_code"], 404)
        self.assertIn("not found", result["error"].lower())

    def test_redirect_response_is_rejected_without_following(self):
        response = Mock(status_code=302)

        with patch.object(
            self.client.session, "get", return_value=response
        ) as mocked_get:
            result = self.client.get_game("abc123")

        self.assertFalse(result["ok"])
        self.assertEqual(result["status_code"], 302)
        self.assertIn("redirect", result["error"].lower())
        self.assertFalse(mocked_get.call_args.kwargs["allow_redirects"])

    def test_invalid_game_ids_are_rejected_without_a_request(self):
        for bad_id in ("../admin", "abc/def", "abc?x=1", "abc def", "abc#frag", ""):
            with self.subTest(bad_id=bad_id):
                with patch.object(self.client.session, "get") as mocked_get:
                    result = self.client.get_game(bad_id)

                self.assertFalse(result["ok"])
                self.assertIsNone(result["status_code"])
                mocked_get.assert_not_called()

    def test_invalid_category_id_is_rejected_without_a_request(self):
        with patch.object(self.client.session, "get") as mocked_get:
            result = self.client.get_leaderboard("abc123", "../../etc")

        self.assertFalse(result["ok"])
        self.assertEqual(result["data"], [])
        mocked_get.assert_not_called()

    def test_unsafe_url_schemes_are_stripped(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "data": {
                "id": "abc123",
                "names": {"international": "Unsafe"},
                "weblink": "javascript:alert(1)",
                "assets": {
                    "cover-medium": {"uri": "data:image/png;base64,abc"},
                    "background": {"uri": "ftp://example.test/bg.jpg"},
                },
            }
        }

        with patch.object(self.client.session, "get", return_value=response):
            result = self.client.get_game("abc123")

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["weblink"], "")
        self.assertEqual(result["data"]["cover"], "")
        self.assertEqual(result["data"]["background"], "")

    def test_unsafe_category_weblink_is_stripped(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "data": [
                {
                    "id": "cat1",
                    "name": "Any%",
                    "type": "per-game",
                    "weblink": "javascript:alert(1)",
                }
            ]
        }

        with patch.object(self.client.session, "get", return_value=response):
            result = self.client.get_categories("abc123")

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"][0]["weblink"], "")

    def test_cache_key_includes_all_query_params(self):
        first = self.client._cache_key("/games", {"max": 12, "offset": 0})
        second = self.client._cache_key("/games", {"max": 12, "offset": 12})
        third = self.client._cache_key(
            "/games", {"max": 12, "offset": 0, "name": "mario"}
        )

        self.assertNotEqual(first, second)
        self.assertNotEqual(first, third)

    def test_session_is_thread_local(self):
        sessions = []

        def capture_session():
            sessions.append(self.client.session)

        threads = [threading.Thread(target=capture_session) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(sessions), 2)
        self.assertIsNot(sessions[0], sessions[1])
        self.assertIsNot(sessions[0], self.client.session)

    @override_settings(SPEEDRUN_USER_AGENT="TestAgent/9.0")
    def test_user_agent_comes_from_settings(self):
        client = SpeedrunAPIClient(
            base_url="https://example.test/api/v1",
            api_key="",
            timeout=1,
            cache_ttl=0,
        )

        self.assertEqual(client.session.headers["User-Agent"], "TestAgent/9.0")

    def test_retries_once_on_server_error(self):
        first = Mock(status_code=500)
        second = Mock(status_code=200)
        second.json.return_value = {
            "data": [],
            "pagination": {"offset": 0, "max": 12, "size": 0, "total": 0},
        }

        with patch.object(
            self.client.session, "get", side_effect=[first, second]
        ) as mocked_get, patch(
            "core.services.speedrun_api.time.sleep"
        ) as mock_sleep:
            result = self.client.get_games()

        self.assertTrue(result["ok"])
        self.assertEqual(mocked_get.call_count, 2)
        mock_sleep.assert_called_once()

    def test_retry_honours_retry_after_header(self):
        first = Mock(status_code=429)
        first.headers = {"Retry-After": "1"}
        second = Mock(status_code=200)
        second.json.return_value = {
            "data": [],
            "pagination": {"offset": 0, "max": 12, "size": 0, "total": 0},
        }

        with patch.object(
            self.client.session, "get", side_effect=[first, second]
        ), patch("core.services.speedrun_api.time.sleep") as mock_sleep:
            result = self.client.get_games()

        self.assertTrue(result["ok"])
        mock_sleep.assert_called_once_with(1.0)


class RunTimeFilterTests(TestCase):
    def test_hours_format(self):
        self.assertEqual(run_time(95 * 60 + 14), "1:35:14")

    def test_minutes_and_milliseconds_format(self):
        self.assertEqual(run_time(16 * 60 + 32.12), "16:32.120")

    def test_invalid_values_return_dash(self):
        self.assertEqual(run_time(None), "\u2014")
        self.assertEqual(run_time("not-a-time"), "\u2014")
