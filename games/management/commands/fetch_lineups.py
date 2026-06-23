"""Fill gaps from projected lineups (RotoWire), splits via the MLB Stats API.

Runs after fetch_games (which sets MLB-announced probable pitchers and the
top-6-by-OPS hitters) and before fetch_weather. For today + tomorrow:

  * Starters: MLB first. Only games still missing a probable pitcher get the
    RotoWire starter, resolved name -> MLBAM id and stored like any pitcher.
  * Hitters: when RotoWire has a full lineup for a team, replace that team's
    top-6 with the actual batting order (rank = lineup spot) and pull each
    hitter's season line + L/R splits from the MLB Stats API. Teams without a
    usable lineup keep the top-6 fetch_games produced (graceful fallback).
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction

from games.models import Team, Pitcher, Game, Hitter
from games.services.lineups import fetch_projected_lineups
from games.services.player_ids import resolve_player_id, resolve_players
from games.services.mlb_api import get_pitcher_stats, get_hitter_details, get_teams
from games.services.savant_stats import get_savant_leaderboard

import logging
logger = logging.getLogger(__name__)

# A RotoWire lineup must resolve at least this many batters to MLBAM ids before
# we trust it enough to replace the top-6. Below this we keep the top-6 rather
# than store a sparse/garbled lineup.
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
        today = date.today()
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

        for when, target_date in (("today", today), ("tomorrow", tomorrow)):
            lineups = fetch_projected_lineups(when)
            if not lineups:
                self.stdout.write(self.style.WARNING(
                    f"No RotoWire lineups available for {when} ({target_date}); skipping."
                ))
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
            self._replace_hitters(target_date, by_id)

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
    # Hitters: replace top-6 with the actual batting order where available.
    # ------------------------------------------------------------------
    def _replace_hitters(self, target_date, by_id):
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

        # Resolve names -> MLBAM ids (roster fetched at most once per team).
        resolved_by_team = {}  # team.id -> (team, [entries with mlb_id])
        for team_id, (team, batters) in team_batters.items():
            resolved = [e for e in resolve_players(batters, team) if e["mlb_id"]]
            if len(resolved) < MIN_RESOLVED_BATTERS:
                logger.warning(
                    f"Only resolved {len(resolved)}/{len(batters)} batters for "
                    f"{team.abbreviation}; keeping top-6."
                )
                continue
            resolved_by_team[team_id] = (team, resolved)

        if not resolved_by_team:
            self.stdout.write(self.style.WARNING(
                f"[{target_date}] No usable RotoWire lineups; kept top-6 hitters."
            ))
            return

        # Fetch each hitter's season line + L/R splits in parallel.
        all_ids = {e["mlb_id"] for (_, entries) in resolved_by_team.values() for e in entries}
        details_by_id = {}
        with ThreadPoolExecutor(max_workers=15) as pool:
            futures = {pool.submit(get_hitter_details, hid): hid for hid in all_ids}
            for fut in as_completed(futures):
                hid = futures[fut]
                try:
                    details_by_id[hid] = fut.result()
                except Exception as e:
                    logger.error(f"Failed to fetch splits for hitter {hid}: {e}")
                    details_by_id[hid] = {}

        with transaction.atomic():
            for team, entries in resolved_by_team.values():
                Hitter.objects.filter(team=team).delete()
                for entry in entries:
                    details = details_by_id.get(entry["mlb_id"], {})
                    Hitter.objects.update_or_create(
                        mlb_id=entry["mlb_id"],
                        defaults={
                            "name": entry["name"],
                            "team": team,
                            "rank": entry["order"],  # batting-order spot
                            "bats": entry.get("bats") or details.get("bats"),
                            "season_pa": details.get("season_pa"),
                            "season_avg": details.get("season_avg"),
                            "season_ops": details.get("season_ops"),
                            "vs_l_pa": details.get("vs_l_pa"),
                            "vs_l_avg": details.get("vs_l_avg"),
                            "vs_l_ops": details.get("vs_l_ops"),
                            "vs_r_pa": details.get("vs_r_pa"),
                            "vs_r_avg": details.get("vs_r_avg"),
                            "vs_r_ops": details.get("vs_r_ops"),
                        },
                    )

        self.stdout.write(self.style.SUCCESS(
            f"[{target_date}] Replaced hitters with actual lineups for "
            f"{len(resolved_by_team)} team(s)."
        ))
