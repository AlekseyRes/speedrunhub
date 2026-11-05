# Speedrun Hub

A dark, gaming-styled Django web app for browsing Speedrun.com data and creating
user accounts. It pulls games, categories, and top runs from the public
Speedrun.com REST API, caches responses, and degrades gracefully for known
upstream failures such as timeouts, rate limits, redirects, and missing
resources. Unexpected payload shapes are validated and reported as errors
instead of crashing the page.

All code, comments, documentation, and UI copy are in English.

## Features

- **Home page** with a hero, calls to action, live catalog statistics, and a
  featured-games grid.
- **Registration** built on `UserCreationForm` with a required email address and
  strict validation:
  - form-level username uniqueness (case-insensitive),
  - form-level email format and uniqueness (case-insensitive),
  - one generic non-field message for duplicate accounts, which avoids revealing
    whether a username or an email is already registered,
  - Django's standard password validators with clear field-level errors,
  - matching passwords,
  - CSRF protection on the registration POST,
  - success message and redirect to the login page.
- **Login and logout** using Django's built-in authentication views with styled
  templates. Logout is a CSRF-protected POST.
- **Game explorer** with name search, 12-per-page pagination, result counts,
  cover art, release years, external Speedrun.com links, an empty state, and an
  API error banner.
- **Game detail** with cover/background art, metadata, categories, and top-three
  leaderboards for up to four per-game categories. Leaderboards are fetched
  concurrently with a bounded overall wait, so one slow category does not delay
  or break the rest of the page. Per-level categories are linked out instead of
  triggering unsupported leaderboard calls.
- **Resilient API client** using thread-local `requests.Session` instances,
  configurable timeout and cache TTL, cache keys derived from the base URL, path,
  and all query parameters, and structured
  `{ok, data, error, total, status_code}` results. Redirects are never followed,
  IDs are validated and URL-encoded, non-http(s) URLs are stripped, and
  transient 429/5xx responses are retried once with a short, capped delay.
- **Template filter** that formats run durations as `H:MM:SS` (for example
  `1:35:14`) or `M:SS.mmm` (for example `16:32.120`).
- **Responsive, accessible UI** with a mobile navigation menu, skip link,
  visible focus states, semantic landmarks, and labelled form controls.

## Project structure

```text
speedrun-hub/
├── manage.py
├── requirements.txt
├── README.md
├── .env.example
├── .gitignore
├── speedrun_hub/
│   ├── __init__.py
│   ├── settings.py
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
├── core/
│   ├── apps.py
│   ├── urls.py
│   ├── views.py
│   ├── tests.py
│   ├── services/
│   │   ├── __init__.py
│   │   └── speedrun_api.py
│   ├── templatetags/
│   │   ├── __init__.py
│   │   └── speedrun_tags.py
│   └── templates/core/
│       ├── home.html
│       ├── explorer.html
│       └── game_detail.html
├── accounts/
│   ├── apps.py
│   ├── forms.py
│   ├── urls.py
│   ├── views.py
│   ├── tests.py
│   └── templates/accounts/
│       ├── register.html
│       └── login.html
├── templates/
│   └── base.html
└── static/
    └── css/
        └── site.css
```

## Prerequisites

- Python 3.12+ (developed against Python 3.12)
- `pip`
- Network access to `https://www.speedrun.com/api/v1` for live data
  (tests use mocks and do not need network access)

## Setup

The repository ships with a virtual environment at `.venv` in the reference
environment. If you are starting from a fresh clone, create and activate your
own:

```bash
cd speedrun-hub
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

If the bundled interpreter already exists, use it directly:

```bash
.venv/bin/python -m pip install -r requirements.txt
```

## Environment configuration

Copy the example file and adjust the values:

```bash
cp .env.example .env
```

For local development, set `DJANGO_DEBUG=True` in `.env` (and keep
`DJANGO_SECURE_SSL_REDIRECT=False`). The example file ships with production-safe
defaults, so a plain copy would redirect the development server to HTTPS and
make `http://127.0.0.1:8000/` unreachable.

`.env` is ignored by Git and must never be committed. `.env.example` is safe to
commit and documents every supported variable.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | none | Secret key used by Django. Required when `DJANGO_DEBUG=False`; startup raises `ImproperlyConfigured` if it is missing or blank. With `DJANGO_DEBUG=True`, a clearly marked insecure local fallback is used. |
| `DJANGO_DEBUG` | `False` | Debug mode. Keep `False` in production; the local `.env` may set `True`. |
| `DJANGO_ALLOWED_HOSTS` | `127.0.0.1,localhost` | Comma-separated hostnames Django will serve. |
| `DJANGO_SECURE_SSL_REDIRECT` | `True` when `DEBUG=False` | Redirect all HTTP requests to HTTPS. |
| `DJANGO_SESSION_COOKIE_SECURE` | `True` when `DEBUG=False` | Only send the session cookie over HTTPS. |
| `DJANGO_CSRF_COOKIE_SECURE` | `True` when `DEBUG=False` | Only send the CSRF cookie over HTTPS. |
| `DJANGO_SECURE_HSTS_SECONDS` | `31536000` when `DEBUG=False`, `0` otherwise | HSTS lifetime in seconds. |
| `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS` | `True` when `DEBUG=False` | Apply HSTS to subdomains. |
| `DJANGO_SECURE_HSTS_PRELOAD` | `True` when `DEBUG=False` | Emit the HSTS preload directive. |
| `DJANGO_SECURE_CONTENT_TYPE_NOSNIFF` | `True` | Send `X-Content-Type-Options: nosniff`. |
| `DJANGO_SECURE_REFERRER_POLICY` | `same-origin` | Value for the `Referrer-Policy` header. |
| `DJANGO_SECURE_PROXY_SSL_HEADER` | empty | Optional `HEADER_NAME,header-value` pair, for example `HTTP_X_FORWARDED_PROTO,https`. Only set this behind a trusted TLS-terminating proxy. |
| `SPEEDRUN_API_BASE_URL` | `https://www.speedrun.com/api/v1` | Base URL for the Speedrun.com API. |
| `SPEEDRUN_API_KEY` | empty | Optional API key sent as the `X-API-Key` header. Redirects are never followed so the key cannot leak to another host. |
| `SPEEDRUN_API_TIMEOUT` | `10` | Request timeout in seconds. Leaderboard calls use a shorter 5-second timeout. |
| `SPEEDRUN_CACHE_TTL` | `300` | Cache lifetime for successful API responses, in seconds. Set to `0` to disable caching. |
| `SPEEDRUN_USER_AGENT` | `SpeedrunHub/1.0 (...)` | User-Agent header sent with every API request. |

The client always sends a descriptive `User-Agent` header identifying the app.

## Install, migrate, and run

```bash
cd speedrun-hub
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver
```

Open <http://127.0.0.1:8000/>.

To run the smoke-test server on a different port:

```bash
.venv/bin/python manage.py runserver 127.0.0.1:8001
```

## Tests

```bash
.venv/bin/python manage.py test
```

The suite covers:

- home rendering with mocked API data and with API failures,
- explorer search parameters, pagination offsets, page clamping, redirects past
  the last page, empty-state navigation, and error banners,
- game detail rendering, concurrent leaderboard normalisation, the
  four-category leaderboard cap, per-category failure isolation, upstream 404
  handling, and per-level handling,
- API client timeout, connection, HTTP, rate-limit, redirect, and 404 errors,
- malformed payload shapes (non-object JSON, non-list data, invalid JSON, and
  unexpected nested types) without unhandled exceptions,
- invalid IDs, URL encoding, unsafe URL schemes, cache-key completeness,
  thread-local sessions, user-agent configuration, and transient retries,
- run-time formatting,
- registration success, generic duplicate-account messages, weak passwords,
  password mismatch, invalid email, CSRF enforcement, and authenticated
  redirects,
- login and logout flows, including ignoring unsafe external `next` values.

All external requests are mocked with `unittest.mock.patch`; the tests never
hit the real Speedrun.com API.

## API notes and rate limits

The app uses these public endpoints:

- `GET /games?max=12&offset=0&name=<query>`
- `GET /games/{id}`
- `GET /games/{id}/categories`
- `GET /leaderboards/{game}/category/{category}?top=3&embed=players`

Behaviour and limits:

- Successful responses are cached with Django's `LocMemCache` for
  `SPEEDRUN_CACHE_TTL` seconds. Cache keys include the base URL, path, and every
  query parameter, so searches and pages never collide.
- The game detail view makes at most four leaderboard requests, one per per-game
  category, using a `ThreadPoolExecutor` with four workers and a bounded overall
  wait. Each request uses a shorter 5-second timeout. A failed or slow
  leaderboard only affects its own category card. Remaining categories link to
  Speedrun.com instead.
- Per-level categories are not queried for leaderboards because they require
  additional level and variable lookups.
- Game and category IDs are validated as alphanumeric and URL-encoded before
  being placed in a path. Invalid IDs return a structured error without a
  network call.
- Only absolute `http`/`https` URLs are passed to templates. `javascript:`,
  `data:`, and other schemes are replaced with an empty string.
- The live API sometimes omits `pagination.total` for `/games` and exposes a
  `links` entry with `rel: "next"` instead. The client supports both shapes:
  exact totals are shown when available, otherwise pagination is driven by the
  next link and the UI reports the number of results on the current page.
- Non-200 responses, HTTP 429 rate limits, timeouts, connection errors,
  redirects, 404s, and malformed JSON are converted into user-facing error
  banners. Known upstream failures are handled gracefully; unexpected payload
  shapes are reported as structured errors rather than raising.
- Upstream 404 responses map to a friendly "Game not found" state.
- Transient 429/5xx responses are retried once with a short delay, capped at two
  seconds and honouring `Retry-After` when it is a numeric value. Pages stay
  responsive even when the upstream is slow.
- Speedrun.com applies its own rate limits. If you see repeated rate-limit
  banners, raise `SPEEDRUN_CACHE_TTL`, add an API key, or reduce traffic.
- If `SPEEDRUN_API_KEY` is set, every request includes the `X-API-Key` header.
  Redirects are disabled so the header can never follow a cross-host redirect.

## Troubleshooting

**The home or explorer page shows an API error banner.**
The upstream API may be slow, rate-limited, or unreachable. Confirm that
`https://www.speedrun.com/api/v1/games` responds in a browser, check your
network, and retry. Cached pages may continue to work during brief outages.

**`DisallowedHost` when opening the app.**
Add the hostname you are using to `DJANGO_ALLOWED_HOSTS` in `.env` and restart
the server.

**Styles look broken.**
Tailwind CSS and Google Fonts are loaded from CDNs. Check network access and
any content blockers. `static/css/site.css` provides the glow, grid, scrollbar,
and animation details, so run `collectstatic` before deploying.

**Logout link returns a 405 error.**
Django 5 only accepts POST for logout. Use the logout button rendered in the
navbar; it includes a CSRF token.

**Tests fail with a stale cache.**
The tests clear Django's cache in `setUp`. If you add tests, do the same or
override `SPEEDRUN_CACHE_TTL=0`.

## Production notes

This project is a demo and intentionally keeps deployment simple.

- **Tailwind CDN is demo-only.** The Play CDN compiles styles in the browser,
  adds a runtime dependency, and is not recommended for production. For a real
  deployment, install Tailwind locally, create a build step, and ship a
  minified stylesheet.
- Set `DJANGO_DEBUG=False`, a strong `DJANGO_SECRET_KEY`, and an explicit
  `DJANGO_ALLOWED_HOSTS`. Startup refuses to run with `DEBUG=False` when the
  secret key is missing or blank.
- Security defaults for `DEBUG=False` enable HTTPS redirects, secure session and
  CSRF cookies, and HSTS (one year, subdomains, preload). Override the
  `DJANGO_SECURE_*` variables when your topology differs, and set
  `DJANGO_SECURE_PROXY_SSL_HEADER` only behind a trusted proxy.
- Email uniqueness is enforced at the form level with Django's default `User`
  model. This is fine for a single instance, but for multi-instance production
  use a custom user model with a database-level unique constraint (or a unique
  functional index on the email address) so concurrent registrations cannot
  create duplicates.
- Replace SQLite with PostgreSQL (or another production database).
- Replace `LocMemCache` with Redis or Memcached so cached API data is shared
  across workers and survives restarts.
- Serve static files through WhiteNoise or a reverse proxy after running
  `python manage.py collectstatic`.
- Terminate TLS at a reverse proxy and keep the secure cookie and HSTS settings
  enabled.
- Run with a production WSGI/ASGI server such as Gunicorn or Uvicorn behind
  Nginx, not the development server.
- Respect Speedrun.com's API terms and rate limits; configure an API key if
  your traffic requires it.

## Local URL

<http://127.0.0.1:8000/>
