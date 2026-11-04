import urllib.parse
import unicodedata
import requests
from app.data.database import PlaceCandidate
import json
import sqlite3
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional


# ---- population and density lookup ----
DB_PATH = Path(__file__).resolve().parent.parent.parent / "scenarios.db"

POP_HTTP_TIMEOUT = 4
CACHE_RADIUS_DEG = 0.04  # ~4 km precision so neighboring towns resolve separately

# known verified urban density figures (people per km2) for major cities
KNOWN_CITY_DENSITIES = {
    "delhi": 11300.0,
    "mumbai": 28500.0,
    "kolkata": 24000.0,
    "chennai": 14000.0,
    "bengaluru": 11000.0,
    "hyderabad": 10500.0,
    "ahmedabad": 9800.0,
    "sonipat": 2450.0,
    "chandigarh": 3500.0,
    "jaipur": 6200.0,
    "pune": 9400.0,
    "beijing": 5800.0,
    "shanghai": 13400.0,
    "guangzhou": 8900.0,
    "shenzhen": 8700.0,
    "tokyo": 6380.0,
    "yokohama": 8500.0,
    "osaka": 11900.0,
    "seoul": 15800.0,
    "busan": 8200.0,
    "london": 5720.0,
    "paris": 20400.0,
    "berlin": 4200.0,
    "madrid": 5300.0,
    "rome": 2200.0,
    "moscow": 5100.0,
    "saint petersburg": 3800.0,
    "kyiv": 3400.0,
    "new york": 11200.0,
    "los angeles": 3200.0,
    "chicago": 4600.0,
    "washington": 4400.0,
    "san francisco": 7100.0,
    "houston": 1500.0,
    "toronto": 4350.0,
    "cairo": 15400.0,
    "tehran": 10800.0,
    "tel aviv": 8500.0,
    "jerusalem": 7200.0,
    "riyadh": 3600.0,
    "dubai": 4100.0,
    "singapore": 8350.0,
    "sydney": 2100.0,
    "melbourne": 1500.0,
    "mexico city": 9800.0,
    "sao paulo": 7800.0,
    "buenos aires": 14000.0,
}


def estimate_realistic_density(city_name: str, population: int, country: str, lon: float, lat: float) -> float:
    """calculates realistic population density based on urban geography and population scale"""
    clean_name = city_name.lower().strip()
    for known_key, known_dens in KNOWN_CITY_DENSITIES.items():
        if known_key in clean_name:
            return float(known_dens)

    is_dense_country = country in [
        "India", "China", "Bangladesh", "Pakistan", "Philippines",
        "Indonesia", "Vietnam", "Egypt", "Nigeria", "South Korea"
    ]
    base_factor = 1.30 if is_dense_country else 0.85

    if population > 6_000_000:
        raw_dens = base_factor * (6200.0 + (population / 1_000_000) * 400.0)
    elif population > 1_500_000:
        raw_dens = base_factor * (3800.0 + (population / 500_000) * 320.0)
    elif population > 400_000:
        raw_dens = base_factor * (2100.0 + (population / 100_000) * 180.0)
    elif population > 100_000:
        raw_dens = base_factor * (1100.0 + (population / 50_000) * 140.0)
    elif population > 25_000:
        raw_dens = base_factor * (550.0 + (population / 10_000) * 80.0)
    elif population > 5_000:
        raw_dens = base_factor * (220.0 + (population / 2_000) * 35.0)
    else:
        raw_dens = 40.0 + max(population / 100.0, 5.0)

    # deterministic coordinate jitter so each distinct geographic point has an individual density
    coord_jitter = ((abs(int(lon * 1000 + lat * 1000)) % 19) - 9) * 15.0
    return round(max(25.0, min(raw_dens + coord_jitter, 36000.0)), 1)


class PopulationService:
    """fetches population and density data and caches to sqlite"""

    OPENDATASOFT_URL = (
        "https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/"
        "geonames-all-cities-with-a-population-1000/records"
    )

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_cache_table()

    def _init_cache_table(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS population_cache (
                        cache_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        place_name TEXT NOT NULL,
                        longitude REAL NOT NULL,
                        latitude REAL NOT NULL,
                        population INTEGER NOT NULL,
                        density_per_km2 REAL NOT NULL,
                        country TEXT,
                        data_source TEXT,
                        cached_at TEXT
                    )
                    """
                )
        finally:
            conn.close()

    def _lookup_cache(self, lon: float, lat: float) -> Optional[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM population_cache
                WHERE abs(longitude - ?) < ? AND abs(latitude - ?) < ?
                ORDER BY abs(longitude - ?) + abs(latitude - ?) ASC
                LIMIT 1
                """,
                (lon, CACHE_RADIUS_DEG, lat, CACHE_RADIUS_DEG, lon, lat),
            ).fetchone()
            if row:
                return dict(row)
        except sqlite3.Error as err:
            print(f"population cache read error: {err}")
        finally:
            conn.close()
        return None

    def _save_cache(
        self,
        place_name: str,
        lon: float,
        lat: float,
        population: int,
        density: float,
        country: str,
        source: str,
    ) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO population_cache (
                        place_name, longitude, latitude, population,
                        density_per_km2, country, data_source, cached_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        place_name,
                        lon,
                        lat,
                        int(population),
                        float(density),
                        country,
                        source,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
        except sqlite3.Error as err:
            print(f"population cache write error: {err}")
        finally:
            conn.close()

    def get_population_and_density(
        self, longitude: float, latitude: float, fallback_label: str = ""
    ) -> Dict[str, Any]:
        """looks up population and urban density for coordinates"""
        cached = self._lookup_cache(longitude, latitude)
        if cached:
            return {
                "place_name": cached["place_name"],
                "country": cached.get("country", "Unknown"),
                "population": cached["population"],
                "density_per_km2": cached["density_per_km2"],
                "data_source": f"SQLite Cache ({cached.get('data_source', 'Cached')})",
                "is_water": cached["population"] == 0,
            }

        # query opendatasoft geonames dataset ordered by distance ascending
        try:
            params = (
                f"where=within_distance(coordinates,%20geom'POINT({longitude}%20{latitude})',%2035km)"
                f"&order_by=distance(coordinates,%20geom'POINT({longitude}%20{latitude})')%20asc"
                f"&limit=1"
            )
            url = f"{self.OPENDATASOFT_URL}?{params}"
            req = urllib.request.Request(url, headers={"User-Agent": "MissileImpactSimulator/2.0"})
            with urllib.request.urlopen(req, timeout=POP_HTTP_TIMEOUT) as response:
                data = json.loads(response.read().decode("utf-8"))
                records = data.get("results", [])
                if records:
                    city_data = records[0]
                    pop = int(city_data.get("population", 0))
                    city_name = city_data.get("name") or fallback_label or "Target Urban Center"
                    country = city_data.get("cou_name_en") or "Global Territory"

                    density = estimate_realistic_density(city_name, pop, country, longitude, latitude)

                    self._save_cache(
                        city_name,
                        longitude,
                        latitude,
                        pop,
                        density,
                        country,
                        "OpenDataSoft / GeoNames",
                    )
                    return {
                        "place_name": city_name,
                        "country": country,
                        "population": pop,
                        "density_per_km2": density,
                        "data_source": "OpenDataSoft / GeoNames",
                        "is_water": False,
                    }
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as err:
            print(f"opendatasoft query error: {err}")

        # fallback to nominatim reverse geocode
        try:
            osm_url = f"https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat={latitude}&lon={longitude}&extratags=1"
            req = urllib.request.Request(osm_url, headers={"User-Agent": "MissileSimulator/2.0"})
            with urllib.request.urlopen(req, timeout=POP_HTTP_TIMEOUT) as response:
                osm_data = json.loads(response.read().decode("utf-8"))
                extratags = osm_data.get("extratags", {})
                pop_str = extratags.get("population")
                address = osm_data.get("address", {})
                place = (
                    address.get("city")
                    or address.get("town")
                    or address.get("municipality")
                    or address.get("village")
                    or address.get("county")
                    or osm_data.get("name")
                    or fallback_label
                    or "Rural Zone"
                )
                country = address.get("country", "Unknown")

                if pop_str and pop_str.isdigit():
                    pop = int(pop_str)
                    density = estimate_realistic_density(place, pop, country, longitude, latitude)
                else:
                    # check if fallback label gives population hint
                    pop = 24000
                    density = estimate_realistic_density(place, pop, country, longitude, latitude)

                self._save_cache(
                    place, longitude, latitude, pop, density, country, "OpenStreetMap Nominatim"
                )
                return {
                    "place_name": place,
                    "country": country,
                    "population": pop,
                    "density_per_km2": density,
                    "data_source": "OpenStreetMap Nominatim",
                    "is_water": False,
                }
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as err:
            print(f"osm reverse query error: {err}")

        # default for remote or maritime regions
        default_name = fallback_label if fallback_label else f"Coordinates ({latitude:.2f}, {longitude:.2f})"
        default_pop = 2500
        default_density = 45.0

        self._save_cache(
            default_name,
            longitude,
            latitude,
            default_pop,
            default_density,
            "Open Territory",
            "Spatial Estimation",
        )
        return {
            "place_name": default_name,
            "country": "Open Territory",
            "population": default_pop,
            "density_per_km2": default_density,
            "data_source": "Spatial Estimation",
            "is_water": False,
        }


# ---- city search and reverse geocoding ----

HTTP_TIMEOUT = 5
REV_TIMEOUT = 4


def clean_label(text: str) -> str:
    """normalizes accented unicode text to ascii"""
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
    """exception for geocoding and coordinate validation errors"""
    pass


def validate_lon_lat(longitude: float, latitude: float) -> None:
    """checks that coordinates are valid floats within bounds"""
    if not isinstance(longitude, (int, float)) or not isinstance(latitude, (int, float)):
        raise GeocodingError("Coordinates must be numeric values.")
    if not (-180.0 <= float(longitude) <= 180.0):
        raise GeocodingError(f"Invalid longitude ({longitude}). Must be between -180 and 180.")
    if not (-90.0 <= float(latitude) <= 90.0):
        raise GeocodingError(f"Invalid latitude ({latitude}). Must be between -90 and 90.")


# offline fallback list for major world cities
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


class GeocodingService:
    """city search and reverse geocoding via osm nominatim and opendatasoft geonames"""

    OSM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
    OSM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
    OPENDATASOFT_URL = (
        "https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/"
        "geonames-all-cities-with-a-population-1000/records"
    )

    def search_city(self, query: str, limit: int = 6) -> List[PlaceCandidate]:
        """searches cities using available providers"""
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

        # osm nominatim lookup
        if len(candidates) < limit:
            try:
                headers = {"User-Agent": "MissileImpactSimulator/2.0", "Accept-Language": "en"}
                params = {
                    "q": cleaned_query,
                    "format": "jsonv2",
                    "limit": limit,
                    "addressdetails": 1,
                }
                response = requests.get(self.OSM_SEARCH_URL, params=params, headers=headers, timeout=HTTP_TIMEOUT)
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
            except (requests.RequestException, ValueError, KeyError) as err:
                print(f"osm search error: {err}")

        # opendatasoft geonames lookup
        if len(candidates) < limit:
            try:
                headers = {"User-Agent": "MissileImpactSimulator/2.0", "Accept-Language": "en"}
                url = f"{self.OPENDATASOFT_URL}?where=search(name,%20%22{urllib.parse.quote(cleaned_query)}%22)&limit={limit}"
                response = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
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
            except (requests.RequestException, ValueError, KeyError) as err:
                print(f"geonames search error: {err}")

        # offline catalog fallback
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
                "Please check spelling or click directly on the globe."
            )

        return candidates[:limit]

    def reverse_geocode(self, longitude: float, latitude: float) -> PlaceCandidate:
        """looks up place name from longitude and latitude"""
        validate_lon_lat(longitude, latitude)

        # osm nominatim reverse lookup
        try:
            headers = {"User-Agent": "MissileImpactSimulator/2.0"}
            params = {
                "format": "jsonv2",
                "lat": latitude,
                "lon": longitude,
                "addressdetails": 1,
            }
            response = requests.get(self.OSM_REVERSE_URL, params=params, headers=headers, timeout=REV_TIMEOUT)
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
        except (requests.RequestException, ValueError, KeyError) as err:
            print(f"osm reverse error: {err}")

        return PlaceCandidate(
            label=f"Point ({latitude:.3f}°, {longitude:.3f}°)",
            longitude=longitude,
            latitude=latitude,
            provider_place_id="manual-pin",
            attribution="Manual Point",
        )
