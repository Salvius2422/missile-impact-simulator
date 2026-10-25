import os
import urllib.parse
import unicodedata
from typing import List, Optional
import requests
from dotenv import load_dotenv
from app.data.models import PlaceCandidate

load_dotenv()


def clean_label(text: str) -> str:
    """Normalizes Unicode text and transliterates accented characters (e.g. Sonīpat -> Sonipat)."""
    if not text:
        return ""
    parts = []
    for ch in str(text):
        decomposed = unicodedata.normalize("NFKD", ch)
        if decomposed and decomposed[0].isascii():
            parts.append(decomposed[0])
        else:
            parts.append(ch)
    return "".join(parts).strip()


class GeocodingError(Exception):
    """Custom exception for geocoding and coordinate validation errors."""
    pass


def validate_lon_lat(longitude: float, latitude: float) -> None:
    """Validates that longitude is in [-180, 180] and latitude is in [-90, 90]."""
    if not isinstance(longitude, (int, float)) or not isinstance(latitude, (int, float)):
        raise GeocodingError("Coordinates must be numeric values.")
    if not (-180.0 <= float(longitude) <= 180.0):
        raise GeocodingError(f"Invalid longitude ({longitude}). Must be between -180 and 180.")
    if not (-90.0 <= float(latitude) <= 90.0):
        raise GeocodingError(f"Invalid latitude ({latitude}). Must be between -90 and 90.")


# Built-in offline fallback list for major world cities
FALLBACK_CITIES = [
    {"label": "New Delhi, India", "lon": 77.2090, "lat": 28.6139, "id": "fallback-delhi"},
    {"label": "Sonipat (Sonepat), Haryana, India", "lon": 77.0234, "lat": 28.9954, "id": "fallback-sonipat"},
    {"label": "Mumbai, Maharashtra, India", "lon": 72.8777, "lat": 19.0760, "id": "fallback-mumbai"},
    {"label": "Bengaluru, Karnataka, India", "lon": 77.5946, "lat": 12.9716, "id": "fallback-blr"},
    {"label": "Kolkata, West Bengal, India", "lon": 88.3639, "lat": 22.5726, "id": "fallback-kolkata"},
    {"label": "Chennai, Tamil Nadu, India", "lon": 80.2707, "lat": 13.0827, "id": "fallback-chennai"},
    {"label": "Hyderabad, Telangana, India", "lon": 78.4867, "lat": 17.3850, "id": "fallback-hyd"},
    {"label": "Washington, D.C., USA", "lon": -77.0369, "lat": 38.9072, "id": "fallback-wdc"},
    {"label": "New York, NY, USA", "lon": -74.0060, "lat": 40.7128, "id": "fallback-nyc"},
    {"label": "Los Angeles, CA, USA", "lon": -118.2437, "lat": 34.0522, "id": "fallback-la"},
    {"label": "London, United Kingdom", "lon": -0.1278, "lat": 51.5074, "id": "fallback-london"},
    {"label": "Paris, France", "lon": 2.3522, "lat": 48.8566, "id": "fallback-paris"},
    {"label": "Berlin, Germany", "lon": 13.4050, "lat": 52.5200, "id": "fallback-berlin"},
    {"label": "Moscow, Russia", "lon": 37.6173, "lat": 55.7558, "id": "fallback-moscow"},
    {"label": "Beijing, China", "lon": 116.4074, "lat": 39.9042, "id": "fallback-beijing"},
    {"label": "Tokyo, Japan", "lon": 139.6917, "lat": 35.6895, "id": "fallback-tokyo"},
    {"label": "Seoul, South Korea", "lon": 126.9780, "lat": 37.5665, "id": "fallback-seoul"},
]


class MapboxGeocodingService:
    """
    Robust global geocoding engine supporting:
    1. Mapbox v6 API (if access token configured)
    2. OpenStreetMap Nominatim Public API (free, open, global coverage of all towns & cities)
    3. OpenDataSoft / GeoNames Global Cities Dataset
    4. Offline city catalog fallback
    """

    MAPBOX_FORWARD_URL = "https://api.mapbox.com/search/geocode/v6/forward"
    MAPBOX_REVERSE_URL = "https://api.mapbox.com/search/geocode/v6/reverse"
    OSM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
    OSM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
    OPENDATASOFT_URL = (
        "https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/"
        "geonames-all-cities-with-a-population-1000/records"
    )

    def __init__(self, access_token: Optional[str] = None):
        self.access_token = (access_token or os.getenv("MAPBOX_ACCESS_TOKEN", "")).strip()

    def _has_valid_token(self) -> bool:
        return bool(self.access_token and self.access_token != "pk.your_mapbox_token_here")

    def search_city(self, query: str, limit: int = 6) -> List[PlaceCandidate]:
        """
        Searches for cities/towns matching the given query globally over Wi-Fi.
        Returns a list of validated PlaceCandidate objects for dropdown selection.
        """
        cleaned_query = query.strip()
        if not cleaned_query:
            raise GeocodingError("Please enter a city name before searching.")

        candidates: List[PlaceCandidate] = []
        seen_coords = set()
        seen_labels = set()

        def add_candidate(c: PlaceCandidate) -> None:
            coord_key = (round(c.longitude, 2), round(c.latitude, 2))
            label_key = c.label.lower().strip()
            if coord_key not in seen_coords and label_key not in seen_labels:
                seen_coords.add(coord_key)
                seen_labels.add(label_key)
                candidates.append(c)

        # 1. Try Mapbox if valid token is provided
        if self._has_valid_token():
            try:
                params = {
                    "q": cleaned_query,
                    "types": "place,locality,region",
                    "limit": limit,
                    "access_token": self.access_token,
                }
                response = requests.get(self.MAPBOX_FORWARD_URL, params=params, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    for feature in data.get("features", []):
                        coords = feature.get("geometry", {}).get("coordinates", [])
                        if len(coords) >= 2:
                            lon, lat = float(coords[0]), float(coords[1])
                            validate_lon_lat(lon, lat)
                            props = feature.get("properties", {})
                            label = clean_label(
                                props.get("full_address")
                                or props.get("place_formatted")
                                or props.get("name")
                                or cleaned_query
                            )
                            place_id = str(props.get("mapbox_id") or feature.get("id") or "")
                            add_candidate(
                                PlaceCandidate(
                                    label=label,
                                    longitude=lon,
                                    latitude=lat,
                                    provider_place_id=place_id,
                                    attribution="Mapbox",
                                )
                            )
            except Exception:
                pass

        # 2. Query OpenStreetMap Nominatim (Free, Open, global coverage of every town/district)
        if len(candidates) < limit:
            try:
                headers = {"User-Agent": "MissileImpactSimulator/2.0", "Accept-Language": "en"}
                params = {
                    "q": cleaned_query,
                    "format": "jsonv2",
                    "limit": limit,
                    "addressdetails": 1,
                }
                response = requests.get(self.OSM_SEARCH_URL, params=params, headers=headers, timeout=5)
                if response.status_code == 200:
                    osm_list = response.json()
                    for item in osm_list:
                        lon = float(item["lon"])
                        lat = float(item["lat"])
                        validate_lon_lat(lon, lat)

                        addr = item.get("address", {})
                        name = (
                            item.get("name")
                            or addr.get("city")
                            or addr.get("town")
                            or addr.get("municipality")
                            or addr.get("village")
                            or addr.get("county")
                            or item.get("display_name", "").split(",")[0]
                        )
                        state = addr.get("state") or addr.get("region") or addr.get("county", "")
                        country = addr.get("country", "")

                        parts = [clean_label(p) for p in [name, state, country] if p and clean_label(p).strip()]
                        # Deduplicate contiguous identical parts (e.g., ['Tokyo', 'Tokyo', 'Japan'] -> ['Tokyo', 'Japan'])
                        deduped = []
                        for part in parts:
                            if not deduped or deduped[-1].lower() != part.lower():
                                deduped.append(part)
                        
                        raw_label = ", ".join(deduped) if len(deduped) >= 2 else clean_label(item.get("display_name", cleaned_query))
                        label = clean_label(raw_label).strip(", ")
                        if not label:
                            label = clean_label(item.get("display_name", cleaned_query))
                        place_id = str(item.get("place_id", ""))

                        add_candidate(
                            PlaceCandidate(
                                label=label,
                                longitude=lon,
                                latitude=lat,
                                provider_place_id=f"osm-{place_id}",
                                attribution="OpenStreetMap",
                            )
                        )
            except Exception:
                pass

        # 3. Query OpenDataSoft / GeoNames Global Cities Dataset (population >= 1,000)
        if len(candidates) < limit:
            try:
                headers = {"User-Agent": "MissileImpactSimulator/2.0", "Accept-Language": "en"}
                url = f"{self.OPENDATASOFT_URL}?where=search(name,%20%22{urllib.parse.quote(cleaned_query)}%22)&limit={limit}"
                response = requests.get(url, headers=headers, timeout=4)
                if response.status_code == 200:
                    records = response.json().get("results", [])
                    for rec in records:
                        coords = rec.get("coordinates", {})
                        if "lon" in coords and "lat" in coords:
                            lon = float(coords["lon"])
                            lat = float(coords["lat"])
                            validate_lon_lat(lon, lat)
                            c_name = rec.get("name", cleaned_query)
                            country = rec.get("cou_name_en", "")
                            admin = rec.get("admin1_code", "")
                            raw_label = f"{c_name}, {admin}, {country}" if admin else f"{c_name}, {country}"
                            label = clean_label(raw_label)
                            add_candidate(
                                PlaceCandidate(
                                    label=label,
                                    longitude=lon,
                                    latitude=lat,
                                    provider_place_id=f"geonames-{rec.get('geoname_id', '')}",
                                    attribution="GeoNames",
                                )
                            )
            except Exception:
                pass

        # 4. Check built-in offline list
        if not candidates:
            for c in FALLBACK_CITIES:
                if cleaned_query.lower() in c["label"].lower():
                    add_candidate(
                        PlaceCandidate(
                            label=c["label"],
                            longitude=c["lon"],
                            latitude=c["lat"],
                            provider_place_id=c["id"],
                            attribution="Offline Catalog",
                        )
                    )

        if not candidates:
            raise GeocodingError(
                f"No locations found matching '{cleaned_query}'.\n"
                "Please verify the city spelling or click directly on the 3D globe."
            )

        return candidates[:limit]

    def reverse_geocode(self, longitude: float, latitude: float) -> PlaceCandidate:
        """Resolves clicked/dragged [longitude, latitude] into a real city/town label."""
        validate_lon_lat(longitude, latitude)

        # 1. Try Mapbox if valid token is provided
        if self._has_valid_token():
            try:
                params = {
                    "longitude": longitude,
                    "latitude": latitude,
                    "types": "place,region,country",
                    "limit": 1,
                    "access_token": self.access_token,
                }
                response = requests.get(self.MAPBOX_REVERSE_URL, params=params, timeout=4)
                if response.status_code == 200:
                    features = response.json().get("features", [])
                    if features:
                        props = features[0].get("properties", {})
                        label = (
                            props.get("full_address")
                            or props.get("place_formatted")
                            or props.get("name")
                        )
                        if label:
                            place_id = str(props.get("mapbox_id") or features[0].get("id") or "reverse-pin")
                            return PlaceCandidate(
                                label=label,
                                longitude=longitude,
                                latitude=latitude,
                                provider_place_id=place_id,
                                attribution="Mapbox",
                            )
            except Exception:
                pass

        # 2. Query OpenStreetMap Nominatim reverse geocode over Wi-Fi
        try:
            headers = {"User-Agent": "MissileImpactSimulator/2.0"}
            params = {
                "format": "jsonv2",
                "lat": latitude,
                "lon": longitude,
                "addressdetails": 1,
            }
            response = requests.get(self.OSM_REVERSE_URL, params=params, headers=headers, timeout=4)
            if response.status_code == 200:
                item = response.json()
                addr = item.get("address", {})
                name = (
                    addr.get("city")
                    or addr.get("town")
                    or addr.get("municipality")
                    or addr.get("village")
                    or addr.get("county")
                    or item.get("name")
                )
                state = addr.get("state") or addr.get("region") or ""
                country = addr.get("country", "")

                parts = [clean_label(p) for p in [name, state, country] if p and clean_label(p).strip()]
                deduped = []
                for p in parts:
                    if not deduped or deduped[-1].lower() != p.lower():
                        deduped.append(p)
                clean_res = ", ".join(deduped) if len(deduped) >= 2 else clean_label(item.get("display_name", ""))
                clean_res = clean_res.strip(", ")
                if clean_res:
                    return PlaceCandidate(
                        label=clean_res,
                        longitude=longitude,
                        latitude=latitude,
                        provider_place_id=f"osm-{item.get('place_id', 'pin')}",
                        attribution="OpenStreetMap",
                    )
        except Exception:
            pass

        return PlaceCandidate(
            label=f"Point ({latitude:.3f}°, {longitude:.3f}°)",
            longitude=longitude,
            latitude=latitude,
            provider_place_id="manual-pin",
            attribution="Manual Point",
        )
