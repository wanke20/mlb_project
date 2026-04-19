import logging
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

_HEADERS = {"User-Agent": "mlb-predictions-app github.com/wanke20/mlb_project"}


def get_rain_probability(lat, lon, game_time_utc):
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
            return prob if prob is not None else 0

    logger.warning(f"No NWS period found for {game_time_utc} at ({lat}, {lon})")
    return None
