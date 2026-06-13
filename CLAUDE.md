# CLAUDE.md

Guidance for working in this repository. Read this before making changes.

## What this project is

An MLB game-prediction web app. It pulls daily MLB data (schedules, team
records, starting pitchers, bullpens, hitters, advanced Statcast metrics, and
ballpark weather), stores it in Postgres, and serves a statistical model that
estimates win probability, expected run differential, and expected run total
for each game. The end use case is informing daily "pick'em" decisions — see
[mlb_pickem_lessons.txt](mlb_pickem_lessons.txt) for the hand-built analytical
framework the model is meant to support.

## Tech stack

- **Backend:** Django 5.0 (Python 3.11/3.12)
- **Database:** PostgreSQL (Supabase-hosted; SSL required). A `db.sqlite3` file
  is checked in but the app is configured for Postgres via env vars.
- **Static files:** WhiteNoise (compressed/manifest storage in production)
- **Deploy:** Gunicorn via [Dockerfile](Dockerfile) / [Procfile](Procfile)
  (Render-style, binds port 10000)
- **Data ingestion:** Scheduled GitHub Actions run Django management commands
  on a cron (see `.github/workflows/`)
- **Frontend:** Server-rendered Django templates with inline CSS. No JS
  framework or build step.

## Architecture

Two Django apps under the `core` project:

### `games` app — the core domain
- **Models** ([games/models.py](games/models.py)): `Team`, `Pitcher`,
  `Hitter`, `Reliever`, `Game`. Pitcher carries both basic (ERA, WHIP, K, BB,
  IP) and advanced metrics (FIP, K-BB%, wOBA, xERA, xwOBA, barrel%).
- **Services** ([games/services/](games/services/)):
  - `mlb_api.py` — wraps the public MLB Stats API (`statsapi.mlb.com`):
    schedule, standings, team/pitcher/hitter/reliever stats, game results.
  - `savant_stats.py` — pulls Baseball Savant CSV leaderboards for the
    Statcast subset (xERA, xwOBA, barrel%), keyed by MLBAM ID.
  - `prediction.py` — the statistical model. Pure functions over model
    instances; no DB or network. Produces win probability (logit + Bayesian
    Beta blend), expected run differential (normal), and expected run total
    (weighted season/recent hitting blend). Tunable constants live at the top.
- **Management command** ([games/management/commands/fetch_games.py](games/management/commands/fetch_games.py)):
  the daily ETL — fetches everything and upserts into the DB. Uses
  `ThreadPoolExecutor` for parallel per-game fetches.
- **Views** ([games/views.py](games/views.py)): home, game list (today/
  yesterday/tomorrow), per-game prediction page (with distribution charts
  computed server-side), trends table, and several CSV export endpoints.
- **Templates** ([games/templates/games/](games/templates/games/)): all extend
  `base.html`, which holds the shared nav and a dark inline-CSS theme
  (Catppuccin-style palette via CSS custom properties).

### `weather` app
- One model, `WeatherData`, in a 1:1 relation with `Game` (rain %, has_roof).
- `fetch_weather` command runs after `fetch_games` completes (chained via
  GitHub Actions `workflow_run`).

### Data flow
```
GitHub Actions cron
  → manage.py fetch_games   (MLB Stats API + Baseball Savant → Postgres)
  → manage.py fetch_weather (weather API → Postgres)
Django views read Postgres → prediction.py → templates → user
```

## Conventions

- **Services are I/O; `prediction.py` is pure.** Keep network/DB calls in
  `services/mlb_api.py` and `savant_stats.py` and the management commands. The
  prediction model should stay testable with plain objects.
- **Model tuning via named constants.** Coefficients and weights are
  module-level constants at the top of `prediction.py` with comments. Adjust
  there rather than scattering magic numbers.
- **Innings pitched** are stored as MLB strings (e.g. `"123.2"` = 123⅔). Use
  `parse_innings_pitched` — never treat them as plain floats.
- **Stat strings vs numbers.** Several rate stats (AVG, OPS) are stored as
  `CharField` strings; cast with care.
- **Graceful degradation.** Missing stats fall back to league-average priors so
  the model still works early in the season. Preserve this.
- **Styling lives in `base.html`.** There is no CSS pipeline; new pages should
  extend `base.html` and reuse its CSS variables and component classes
  (`.card`, `.streak-win`, etc.).

## Environment / running

Env vars (loaded from `.env` via `python-dotenv`):
`DATABASE_USER`, `DATABASE_PASSWORD`, `HOST` (Postgres/Supabase), and `DEBUG`
(`True` for local dev). `SECRET_KEY` is currently hardcoded in settings — see
Known issues.

```bash
python manage.py migrate
python manage.py runserver          # local dev (set DEBUG=True in .env)
python manage.py fetch_games        # run the ETL manually
python manage.py fetch_weather
python manage.py collectstatic --noinput
```

## Known issues / cleanup opportunities

- `SECRET_KEY` is hardcoded in [core/settings.py](core/settings.py); a
  `DJANGO_SECRET_KEY` secret is already wired into the workflows but unused in
  settings. Move to env.
- `ALLOWED_HOSTS = ["*"]` is marked "tighten later."
- `db.sqlite3` is committed but the app targets Postgres.
- `tests.py` files are empty — no test coverage yet.

---

## Planned / desired direction

The following are goals the owner wants to move toward. They are **not yet
built** — treat this section as intent, and confirm specifics before
implementing.

### 1. More professional visual design
Elevate the UI from the current functional dark theme to a polished,
professional look. The current styling is entirely inline in `base.html`. When
working on this, consider:
- A consistent, intentional design system (typography scale, spacing, color
  palette, component library) rather than ad-hoc inline styles.
- Improved layout, responsiveness, and visual hierarchy on the game list,
  prediction, and trends pages.
- Whether to introduce a static asset pipeline / dedicated CSS file(s) vs.
  keeping the single-file approach. Discuss trade-offs before adding build
  tooling.

### 2. User accounts (login / signup)
Add authentication so users can register and sign in. Likely uses Django's
built-in `django.contrib.auth` (already installed). Will introduce a `users`/
`accounts` app or extend an existing one, plus auth templates that match the
new design.

### 3. User dashboard for tracking picks
A personalized, authenticated dashboard where a logged-in user can record and
review their daily picks against actual game results. Implies:
- A model linking a user to the games/picks they've made.
- Views/templates for making, viewing, and grading picks (the app already
  ingests final scores and starter lines, so results are available).
- Performance tracking (record, win rate, trends over time).

### 4. LLM API integration for pick assistance
Within the dashboard, integrate an LLM to help the user make picks — e.g.
synthesizing the model's outputs, Statcast metrics, and the framework in
`mlb_pickem_lessons.txt` into a recommendation or explanation.
- **Provider is undecided.** Do not assume a vendor. When this is built,
  abstract the LLM call behind a service interface so the provider can be
  swapped, and ask the owner which provider/model to wire up first.
- Keep API keys in environment variables, never committed.
- The pick'em framework in `mlb_pickem_lessons.txt` is a strong candidate for
  grounding the LLM's reasoning (system prompt / context).

When implementing any of the above, follow the existing conventions (services
for I/O, pure model logic, template inheritance) and keep new secrets in env.
