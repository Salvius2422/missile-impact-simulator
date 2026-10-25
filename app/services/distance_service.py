import math
from app.services.mapbox_geocoding import validate_lon_lat

EARTH_MEAN_RADIUS_KM = 6371.0088


def calculate_great_circle_distance_km(
    origin_lon: float,
    origin_lat: float,
    dest_lon: float,
    dest_lat: float,
) -> float:
    """
    Calculates the great-circle surface distance in kilometers
    between two [longitude, latitude] coordinates using the Haversine formula.
    """
    validate_lon_lat(origin_lon, origin_lat)
    validate_lon_lat(dest_lon, dest_lat)

    lat1_rad = math.radians(origin_lat)
    lat2_rad = math.radians(dest_lat)
    delta_lat = math.radians(dest_lat - origin_lat)
    delta_lon = math.radians(dest_lon - origin_lon)

    a = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return round(EARTH_MEAN_RADIUS_KM * c, 2)
