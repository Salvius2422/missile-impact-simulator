import json
from typing import Dict, Any, List, Optional
from app.data.models import PlaceCandidate, Scenario
from app.data.database import ScenarioDatabase
from app.services.mapbox_geocoding import MapboxGeocodingService, GeocodingError
from app.services.distance_service import calculate_great_circle_distance_km
from app.services.impact_physics import load_missiles, check_within_range, compute_impact_effects
from app.services.population_service import PopulationService


class SimulatorApi:
    """Python API exposed directly to JavaScript in pywebview."""

    def __init__(self):
        self.geocoding_service = MapboxGeocodingService()
        self.population_service = PopulationService()
        self.db = ScenarioDatabase()
        self.missiles = load_missiles()
        self.missile_map = {m["id"]: m for m in self.missiles}

    def get_missiles(self) -> List[Dict[str, Any]]:
        return self.missiles

    def search_city(self, query: str) -> Dict[str, Any]:
        try:
            candidates = self.geocoding_service.search_city(query)
            return {
                "success": True,
                "candidates": [
                    {
                        "label": c.label,
                        "longitude": c.longitude,
                        "latitude": c.latitude,
                        "provider_place_id": c.provider_place_id,
                        "attribution": c.attribution,
                    }
                    for c in candidates
                ],
            }
        except GeocodingError as e:
            return {"success": False, "error": str(e), "candidates": []}
        except Exception as e:
            return {"success": False, "error": f"Search failed: {e}", "candidates": []}

    def reverse_geocode(self, longitude: float, latitude: float) -> Dict[str, Any]:
        try:
            c = self.geocoding_service.reverse_geocode(longitude, latitude)
            return {
                "label": c.label,
                "longitude": c.longitude,
                "latitude": c.latitude,
                "provider_place_id": c.provider_place_id,
                "attribution": c.attribution,
            }
        except Exception as e:
            return {
                "label": f"Coordinates ({latitude:.3f}°, {longitude:.3f}°)",
                "longitude": longitude,
                "latitude": latitude,
                "provider_place_id": "manual-pin",
                "attribution": "Manual Pin",
            }

    def get_population(self, longitude: float, latitude: float, label: str = "") -> Dict[str, Any]:
        return self.population_service.get_population_and_density(longitude, latitude, label)

    def calculate_distance(
        self, origin_lon: float, origin_lat: float, dest_lon: float, dest_lat: float
    ) -> float:
        return calculate_great_circle_distance_km(origin_lon, origin_lat, dest_lon, dest_lat)

    def check_range(self, distance_km: float, missile_id: str) -> Dict[str, Any]:
        missile = self.missile_map.get(missile_id, self.missiles[0])
        return check_within_range(distance_km, missile)

    def simulate_launch(
        self,
        origin: Dict[str, Any],
        dest: Dict[str, Any],
        missile_id: str,
        is_nuclear: bool,
        nuclear_yield_kt: float,
        pop_density_per_km2: Optional[float] = None,
    ) -> Dict[str, Any]:
        missile = self.missile_map.get(missile_id, self.missiles[0])
        dist_km = calculate_great_circle_distance_km(
            origin["longitude"], origin["latitude"], dest["longitude"], dest["latitude"]
        )
        range_check = check_within_range(dist_km, missile)

        if not range_check["in_range"]:
            return {
                "success": False,
                "in_range": False,
                "error": range_check["reason"],
                "distance_km": dist_km,
            }

        # Automatically look up real-world population and density via open database over Wi-Fi
        pop_info = self.population_service.get_population_and_density(
            dest["longitude"], dest["latitude"], dest.get("label", "")
        )
        density = float(pop_info["density_per_km2"])

        impact = compute_impact_effects(
            missile=missile,
            distance_km=dist_km,
            is_nuclear=is_nuclear,
            nuclear_yield_kt=float(nuclear_yield_kt),
            pop_density_per_km2=density,
        )

        return {
            "success": True,
            "in_range": True,
            "distance_km": dist_km,
            "missile": missile,
            "impact": impact,
            "population_info": pop_info,
        }

    def save_scenario(
        self,
        scenario_name: str,
        origin_label: str,
        origin_lon: float,
        origin_lat: float,
        dest_label: str,
        dest_lon: float,
        dest_lat: float,
        missile_id: str,
        is_nuclear: bool,
        yield_kt: float,
        density: Optional[float] = None,
    ) -> Dict[str, Any]:
        try:
            scenario = Scenario(
                scenario_name=scenario_name.strip(),
                origin_city_label=origin_label,
                origin_longitude=float(origin_lon),
                origin_latitude=float(origin_lat),
                destination_city_label=dest_label,
                destination_longitude=float(dest_lon),
                destination_latitude=float(dest_lat),
                selected_reference_record_id=missile_id,
                hypothetical_assessment_zone_parameters=json.dumps(
                    {"is_nuclear": is_nuclear, "yield_kt": yield_kt, "density": density or 0.0}
                ),
            )
            scenario_id = self.db.save_scenario(scenario)
            return {"success": True, "scenario_id": scenario_id, "message": f"Scenario '{scenario_name}' saved!"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_scenarios(self) -> List[Dict[str, Any]]:
        scenarios = self.db.list_scenarios()
        out = []
        for s in scenarios:
            out.append(
                {
                    "scenario_id": s.scenario_id,
                    "scenario_name": s.scenario_name,
                    "origin_city_label": s.origin_city_label,
                    "origin_longitude": s.origin_longitude,
                    "origin_latitude": s.origin_latitude,
                    "destination_city_label": s.destination_city_label,
                    "destination_longitude": s.destination_longitude,
                    "destination_latitude": s.destination_latitude,
                    "selected_reference_record_id": s.selected_reference_record_id,
                    "hypothetical_assessment_zone_parameters": s.hypothetical_assessment_zone_parameters,
                    "created_at": s.created_at,
                }
            )
        return out
