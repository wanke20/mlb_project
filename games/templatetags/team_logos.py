from django import template

register = template.Library()

# Map MLB team IDs to the logo filename base in `static/logos/`.
# Keep these in sync with the actual filenames (lowercase, no extension).
TEAM_ID_TO_LOGO = {
    108: "laa",  # Los Angeles Angels
    109: "ari",  # Arizona Diamondbacks
    110: "bal",  # Baltimore Orioles
    111: "bos",  # Boston Red Sox
    112: "chc",  # Chicago Cubs
    113: "cin",  # Cincinnati Reds
    114: "cle",  # Cleveland Guardians
    115: "col",  # Colorado Rockies
    116: "det",  # Detroit Tigers
    117: "hou",  # Houston Astros
    118: "kc",   # Kansas City Royals
    119: "lad",  # Los Angeles Dodgers
    120: "was",  # Washington Nationals (matches `static/logos/was.png`)
    121: "nym",  # New York Mets
    133: "ath",  # Athletics (matches `static/logos/ath.png`)
    134: "pit",  # Pittsburgh Pirates
    135: "sd",   # San Diego Padres
    136: "sea",  # Seattle Mariners
    137: "sf",   # San Francisco Giants
    138: "stl",  # St. Louis Cardinals
    139: "tb",   # Tampa Bay Rays
    140: "tex",  # Texas Rangers
    141: "tor",  # Toronto Blue Jays
    142: "min",  # Minnesota Twins
    143: "phi",  # Philadelphia Phillies
    144: "atl",  # Atlanta Braves
    145: "cws",  # Chicago White Sox
    146: "mia",  # Miami Marlins
    147: "nyy",  # New York Yankees
    158: "mil",  # Milwaukee Brewers
}


@register.filter
def logo_abbr(team):
    """
    Returns the logo filename base for a Team, falling back to MLB team_id mapping.
    Intended usage: `{{ game.home_team|logo_abbr }}` -> `nyy`
    """
    if team is None:
        return ""

    abbr = getattr(team, "abbreviation", None) or ""
    abbr = abbr.strip().lower()
    if abbr:
        return abbr

    team_id = getattr(team, "mlb_id", None)
    if isinstance(team_id, int):
        return TEAM_ID_TO_LOGO.get(team_id, "")

    return ""

