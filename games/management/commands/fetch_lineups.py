"""Populate projected lineups (RotoWire), splits via the MLB Stats API.

Runs after fetch_games (which sets MLB-announced probable pitchers) and before
fetch_weather. This command is the sole source of Hitter rows — fetch_games no
longer fetches a top-6 baseline. For today + tomorrow:

  * Starters: MLB first. Only games still missing a probable pitcher get the
    RotoWire starter, resolved name -> MLBAM id and stored like any pitcher.
  * Hitters: store the actual projected batting order (rank = lineup spot) and
    pull each hitter's season line + L/R splits from the MLB Stats API. Teams
    without a usable RotoWire lineup get no hitters (there is no fallback).

Name -> MLBAM id resolution is cache-first (PlayerIDMap), so the team roster is
only fetched for never-seen names. Hitter splits are fetched once per unique
player across both dates, so a player in both lineups isn't fetched twice.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction

from games.models import Team, Pitcher, Game, Hitter
from games.services.lineups import fetch_projected_lineups
from games.services.player_ids import resolve_player_id, resolve_players
from games.services.mlb_api import get_pitcher_stats, get_hitter_details, get_teams
from games.services.savant_stats import get_savant_leaderboard
from games.services.dates import eastern_today

import logging
logger = logging.getLogger(__name__)

# A RotoWire lineup must resolve at least this many batters to MLBAM ids before
# we store it. Below this we skip the lineup rather than store a sparse/garbled
# one (the team simply gets no hitters for that date).
MIN_RESOLVED_BATTERS = 8

# RotoWire abbreviations vs. MLB Stats API abbreviations differ for a handful of
# teams. Canonicalize both sides to one token so they match regardless of which
# variant each source uses.
_ABBR_CANON = {
    "CHW": "CWS", "CWS": "CWS",
    "WAS": "WSH", "WSN": "WSH", "WSH": "WSH",
    "SDP": "SD", "SD": "SD",
    "SFG": "SF", "SF": "SF",
    "TBR": "TB", "TB": "TB",
    "KCR": "KC", "KC": "KC",
    "ARI": "ARI", "AZ": "ARI",
    "LAD": "LAD", "LA": "LAD",
    "ATH": "OAK", "OAK": "OAK",
}


def _canon(abbr):
    a = (abbr or "").upper()
    return _ABBR_CANON.get(a, a)


class Command(BaseCommand):
    help = "Fill missing starters and replace top-6 hitters with actual lineups (RotoWire)."

    def handle(self, *args, **kwargs):
        today = eastern_today()
        tomorrow = today + timedelta(days=1)

        # Map RotoWire abbreviation -> MLBAM team id. The stored
        # Team.abbreviation is not reliably populated, so we match on team id.
        try:
            canon_to_team_id = {
                _canon(t["abbreviation"]): t["mlb_id"]
                for t in get_teams(season=2026)
                if t.get("abbreviation")
            }
        except Exception as e:
            logger.error(f"Failed to fetch team list for abbreviation mapping: {e}")
            self.stdout.write(self.style.ERROR(
                "Could not fetch team list; aborting lineup fetch."
            ))
            return

        # RotoWire's "today"/"tomorrow" are relative to its own (US/Eastern)
        # clock, which drifts from our UTC server date overnight — asking for
        # "today" after midnight UTC can return the prior day's lineups. So we
        # fetch both pages but trust the real calendar date embedded in each
        # lineup, bucket by it, and only attach a lineup to a game date when the
        # dates actually match.
        lineups_by_date = {}  # "YYYY-MM-DD" -> {abbr: data}
        for when in ("today", "tomorrow"):
            for abbr, data in fetch_projected_lineups(when).items():
                day = data.get("date")
                if not day:
                    continue
                lineups_by_date.setdefault(day, {})[abbr] = data

        # Resolve names -> ids per date first (cache-first, roster only on
        # miss), then fetch each unique hitter's splits ONCE across both dates.
        resolved_by_date = {}  # date -> {team.id: (team, [resolved entries])}
        for target_date in (today, tomorrow):
            lineups = lineups_by_date.get(target_date.isoformat(), {})
            if not lineups:
                self.stdout.write(self.style.WARNING(
                    f"No RotoWire lineups matching {target_date}; skipping."
                ))
                resolved_by_date[target_date] = {}
                continue

            # Index lineups by MLBAM team id for matching against Game teams.
            by_id = {}
            for abbr, data in lineups.items():
                team_id = canon_to_team_id.get(_canon(abbr))
                if team_id:
                    by_id[team_id] = data
                else:
                    logger.warning(f"Unmatched RotoWire team abbreviation: {abbr}")

            self._fill_starters(target_date, by_id)
            resolved_by_date[target_date] = self._resolve_lineups(target_date, by_id)

        # Fetch splits once per unique hitter across both dates.
        all_ids = {
            e["mlb_id"]
            for teams in resolved_by_date.values()
            for (_, entries) in teams.values()
            for e in entries
        }
        details_by_id = {}
        if all_ids:
            with ThreadPoolExecutor(max_workers=30) as pool:
                futures = {pool.submit(get_hitter_details, hid): hid for hid in all_ids}
                for fut in as_completed(futures):
                    hid = futures[fut]
                    try:
                        details_by_id[hid] = fut.result()
                    except Exception as e:
                        logger.error(f"Failed to fetch splits for hitter {hid}: {e}")
                        details_by_id[hid] = {}

        for target_date, teams in resolved_by_date.items():
            self._write_hitters(target_date, teams, details_by_id)

    # ------------------------------------------------------------------
    # Starters: fill only games with no MLB-announced probable pitcher.
    # ------------------------------------------------------------------
    def _fill_starters(self, target_date, by_id):
        games = Game.objects.filter(date=target_date).select_related(
            "home_team", "away_team", "home_pitcher", "away_pitcher"
        )

        fills = []  # (game, side, team, starter_name)
        for game in games:
            for side in ("home", "away"):
                if getattr(game, f"{side}_pitcher_id"):
                    continue  # MLB already gave us a probable pitcher
                team = getattr(game, f"{side}_team")
                lineup = by_id.get(team.mlb_id)
                if lineup and lineup.get("starter"):
                    fills.append((game, side, team, lineup["starter"]))

        if not fills:
            return

        # Only pull the (bulk) Savant leaderboard if we actually have starters
        # to enrich, to match the advanced metrics fetch_games applies.
        try:
            advanced = get_savant_leaderboard(year=2026)
        except Exception as e:
            logger.error(f"Failed to fetch Savant leaderboard in fetch_lineups: {e}")
            advanced = {}

        filled = 0
        for game, side, team, starter_name in fills:
            mlb_id = resolve_player_id(starter_name, team)
            if not mlb_id:
                logger.warning(
                    f"Could not resolve RotoWire starter '{starter_name}' for {team.name}"
                )
                continue
            try:
                stats = get_pitcher_stats(mlb_id)
            except Exception as e:
                logger.error(f"Failed to fetch stats for fallback starter {mlb_id}: {e}")
                continue

            defaults = {
                "name": starter_name,
                "throws": stats.get("throws"),
                "era": stats["era"],
                "whip": stats["whip"],
                "strikeouts": stats["strikeouts"],
                "walks": stats["walks"],
                "innings_pitched": stats["innings_pitched"],
                "fip": stats.get("fip"),
                "k_bb_pct": stats.get("k_bb_pct"),
            }
            adv = advanced.get(mlb_id)
            if adv:
                defaults.update(adv)

            pitcher, _ = Pitcher.objects.update_or_create(mlb_id=mlb_id, defaults=defaults)
            setattr(game, f"{side}_pitcher", pitcher)
            game.save(update_fields=[f"{side}_pitcher"])
            filled += 1

        self.stdout.write(self.style.SUCCESS(
            f"[{target_date}] Filled {filled} missing starter(s) from RotoWire."
        ))

    # ------------------------------------------------------------------
    # Hitters: resolve the projected batting order (cache-first), then write.
    # ------------------------------------------------------------------
    def _resolve_lineups(self, target_date, by_id):
        """Return {team.id: (team, [resolved entries])} for this date's lineups."""
        games = Game.objects.filter(date=target_date).select_related("home_team", "away_team")

        # One entry per team (handles a team appearing in a doubleheader once).
        team_batters = {}  # team.id -> (team, [batter entries])
        for game in games:
            for team in (game.home_team, game.away_team):
                if team.id in team_batters:
                    continue
                lineup = by_id.get(team.mlb_id)
                if lineup and lineup.get("batters"):
                    team_batters[team.id] = (team, lineup["batters"])

        resolved_by_team = {}  # team.id -> (team, [entries with mlb_id])
        for team_id, (team, batters) in team_batters.items():
            resolved = [e for e in resolve_players(batters, team) if e["mlb_id"]]
            if len(resolved) < MIN_RESOLVED_BATTERS:
                logger.warning(
                    f"Only resolved {len(resolved)}/{len(batters)} batters for "
                    f"{team.name}; skipping lineup."
                )
                continue
            resolved_by_team[team_id] = (team, resolved)

        return resolved_by_team

    def _write_hitters(self, target_date, resolved_by_team, details_by_id):
        """Replace this date's hitters with the resolved projected lineups.

        Clears every playing team's hitters for the date first, so teams whose
        lineup didn't resolve are left with no hitters (no top-6 fallback).
        """
        team_ids_today = set()
        for home_id, away_id in Game.objects.filter(date=target_date).values_list(
            "home_team_id", "away_team_id"
        ):
            team_ids_today.add(home_id)
            team_ids_today.add(away_id)

        # Build all rows in memory, then write in one bulk insert per date —
        # individual creates are ~270 separate round-trips to the remote DB.
        rows = []
        for team, entries in resolved_by_team.values():
            for entry in entries:
                details = details_by_id.get(entry["mlb_id"], {})
                rows.append(Hitter(
                    mlb_id=entry["mlb_id"],
                    date=target_date,
                    name=entry["name"],
                    team=team,
                    rank=entry["order"],  # batting-order spot
                    position=entry.get("pos"),
                    bats=entry.get("bats") or details.get("bats"),
                    season_pa=details.get("season_pa"),
                    season_avg=details.get("season_avg"),
                    season_ops=details.get("season_ops"),
                    vs_l_pa=details.get("vs_l_pa"),
                    vs_l_avg=details.get("vs_l_avg"),
                    vs_l_ops=details.get("vs_l_ops"),
                    vs_r_pa=details.get("vs_r_pa"),
                    vs_r_avg=details.get("vs_r_avg"),
                    vs_r_ops=details.get("vs_r_ops"),
                ))

        with transaction.atomic():
            Hitter.objects.filter(team_id__in=team_ids_today, date=target_date).delete()
            Hitter.objects.bulk_create(rows)

        self.stdout.write(self.style.SUCCESS(
            f"[{target_date}] Wrote projected lineups for {len(resolved_by_team)} team(s)."
        ))
