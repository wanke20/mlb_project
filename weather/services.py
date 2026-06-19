import logging
import re
import requests
from datetime import datetime

logger = logging.getLogger(__name__)

# mlb_id: (lat, lon, has_roof)
STADIUM_COORDS = {
    108: (33.8003, -117.8827, False),  # LAA
    109: (33.4453, -112.0667, True),   # ARI
    110: (39.2838, -76.6216,  False),  # BAL
    111: (42.3467, -71.0972,  False),  # BOS
    112: (41.9484, -87.6553,  False),  # CHC
    113: (39.0979, -84.5082,  False),  # CIN
    114: (41.4962, -81.6852,  False),  # CLE
    115: (39.7559, -104.9942, False),  # COL
    116: (42.3390, -83.0485,  False),  # DET
    117: (29.7573, -95.3555,  True),   # HOU
    118: (39.0514, -94.4803,  False),  # KC
    119: (34.0739, -118.2400, False),  # LAD
    120: (38.8730, -77.0074,  False),  # WSH
    121: (40.7571, -73.8458,  False),  # NYM
    133: (38.5802, -121.5009, False),  # OAK (Sacramento)
    134: (40.4469, -80.0057,  False),  # PIT
    135: (32.7076, -117.1570, False),  # SD
    136: (47.5914, -122.3325, True),   # SEA
    137: (37.7786, -122.3893, False),  # SF
    138: (38.6226, -90.1928,  False),  # STL
    139: (27.7683, -82.6534,  True),   # TB
    140: (32.7512, -97.0832,  True),   # TEX
    141: (43.6414, -79.3894,  True),   # TOR
    142: (44.9817, -93.2781,  False),  # MIN
    143: (39.9057, -75.1665,  False),  # PHI
    144: (33.8908, -84.4678,  False),  # ATL
    145: (41.8300, -87.6338,  False),  # CWS
    146: (25.7781, -80.2197,  True),   # MIA
    147: (40.8296, -73.9262,  False),  # NYY
    158: (43.0280, -87.9712,  True),   # MIL
}

# mlb_id: compass bearing in degrees from home plate toward center field
# (0 = N, 90 = E, 180 = S, 270 = W) — i.e. the direction the batter faces.
# Sourced from ballparks.com / Baseball Almanac orientation diagrams; the four
# relocated/rebuilt parks (ATL, OAK-Sacramento, MIA, TEX) are noted inline.
# Roofed parks (see has_roof above) never surface wind, so their values are
# informational only.
PARK_CF_BEARING = {
    108: 45,   # LAA  Angel Stadium
    109: 0,    # ARI  Chase Field (roof)
    110: 30,   # BAL  Oriole Park at Camden Yards
    111: 45,   # BOS  Fenway Park
    112: 30,   # CHC  Wrigley Field
    113: 120,  # CIN  Great American Ball Park
    114: 0,    # CLE  Progressive Field
    115: 0,    # COL  Coors Field
    116: 150,  # DET  Comerica Park
    117: 345,  # HOU  Minute Maid Park (roof)
    118: 45,   # KC   Kauffman Stadium
    119: 30,   # LAD  Dodger Stadium
    120: 30,   # WSH  Nationals Park
    121: 30,   # NYM  Citi Field
    133: 30,   # OAK  Sutter Health Park, Sacramento — approx (CF ~NNE toward downtown)
    134: 120,  # PIT  PNC Park
    135: 0,    # SD   Petco Park
    136: 45,   # SEA  T-Mobile Park (roof)
    137: 90,   # SF   Oracle Park
    138: 60,   # STL  Busch Stadium
    139: 45,   # TB   Tropicana Field (roof)
    140: 60,   # TEX  Globe Life Field (roof) — new park, ENE orientation
    141: 0,    # TOR  Rogers Centre (roof)
    142: 90,   # MIN  Target Field
    143: 15,   # PHI  Citizens Bank Park
    144: 135,  # ATL  Truist Park — southeast orientation
    145: 135,  # CWS  Guaranteed Rate Field
    146: 40,   # MIA  loanDepot park (roof) — new park, approx
    147: 75,   # NYY  Yankee Stadium
    158: 135,  # MIL  American Family Field (roof)
}

# 16-point compass -> degrees (where the wind blows FROM, per NWS convention)
_CARDINAL_DEGREES = {
    "N": 0, "NNE": 22.5, "NE": 45, "ENE": 67.5,
    "E": 90, "ESE": 112.5, "SE": 135, "SSE": 157.5,
    "S": 180, "SSW": 202.5, "SW": 225, "WSW": 247.5,
    "W": 270, "WNW": 292.5, "NW": 315, "NNW": 337.5,
}

# Relative-wind buckets, clockwise from the center-field axis (each 45° wide,
# centered on the listed angle). 0° = wind blowing straight out to CF.
_WIND_BUCKETS = [
    (0,   "Out to CF"),
    (45,  "Out to RF"),
    (90,  "Across L→R"),
    (135, "In from RF"),
    (180, "In from CF"),
    (225, "In from LF"),
    (270, "Across R→L"),
    (315, "Out to LF"),
]

_HEADERS = {"User-Agent": "mlb-predictions-app github.com/wanke20/mlb_project"}


def cardinal_to_degrees(card):
    """16-point compass string ('N', 'NNE', ... 'NW') -> degrees. None if unknown."""
    if not card:
        return None
    return _CARDINAL_DEGREES.get(card.strip().upper())


def parse_wind_mph(s):
    """'10 mph' / '5 to 10 mph' -> int (high end). None if unparseable."""
    if not s:
        return None
    nums = re.findall(r"\d+", str(s))
    return int(nums[-1]) if nums else None


def wind_relative_to_park(cf_bearing, wind_from_cardinal):
    """Classify wind relative to the park's home-plate->CF axis.

    NWS reports the direction wind comes FROM, so flip 180° to get the
    direction it blows TOWARD, then measure clockwise from the CF bearing.
    Returns a label like 'Out to CF' / 'In from CF' / 'Across L->R', or None.
    """
    from_deg = cardinal_to_degrees(wind_from_cardinal)
    if from_deg is None or cf_bearing is None:
        return None
    toward_deg = (from_deg + 180) % 360
    rel = (toward_deg - cf_bearing) % 360
    # Snap to the nearest 45° bucket (wraps 337.5-360 back to the 0° bucket).
    idx = int((rel + 22.5) % 360 // 45)
    return _WIND_BUCKETS[idx][1]


def get_forecast(lat, lon, game_time_utc):
    """Fetch the NWS hourly forecast period covering game time.

    Returns a dict {rain_pct, wind_mph, wind_from} (any value may be None on a
    missing field), or None if the API lookup fails entirely.
    """
    # Step 1: resolve NWS grid point
    try:
        resp = requests.get(
            f"https://api.weather.gov/points/{lat},{lon}",
            headers=_HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        forecast_hourly_url = resp.json()["properties"]["forecastHourly"]
    except Exception as e:
        logger.error(f"NWS points lookup failed for ({lat}, {lon}): {e}")
        return None

    # Step 2: get hourly forecast
    try:
        resp = requests.get(
            forecast_hourly_url,
            headers=_HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        periods = resp.json()["properties"]["periods"]
    except Exception as e:
        logger.error(f"NWS hourly forecast failed for ({lat}, {lon}): {e}")
        return None

    # Find the period containing game_time_utc
    for period in periods:
        start = datetime.fromisoformat(period["startTime"])
        end = datetime.fromisoformat(period["endTime"])
        if start <= game_time_utc <= end:
            prob = period["probabilityOfPrecipitation"]["value"]
            return {
                "rain_pct": prob if prob is not None else 0,
                "wind_mph": parse_wind_mph(period.get("windSpeed")),
                "wind_from": (period.get("windDirection") or None),
            }

    logger.warning(f"No NWS period found for {game_time_utc} at ({lat}, {lon})")
    return None
