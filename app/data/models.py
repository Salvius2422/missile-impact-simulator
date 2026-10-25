from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class PlaceCandidate:
    """Represents a validated city result returned by the Mapbox Geocoding API."""
    label: str
    longitude: float
    latitude: float
    provider_place_id: str
    attribution: str = "© Mapbox © OpenStreetMap"


@dataclass
class Scenario:
    """Data model for a saved missile simulation scenario."""
    scenario_name: str
    origin_city_label: str
    origin_longitude: float
    origin_latitude: float
    destination_city_label: str
    destination_longitude: float
    destination_latitude: float
    map_provider: str = "Mapbox"
    provider_place_ids_or_source_metadata: str = ""
    selected_reference_record_id: Optional[str] = None
    hypothetical_assessment_zone_parameters: str = '{"radius_km": 10.0}'
    population_data_source: str = "UN/GHSL Urban Density Benchmark"
    assumptions_and_uncertainty_notes: str = (
        "Educational impact simulation using Glasstone-Dolan cube-root scaling laws."
    )
    scenario_id: Optional[int] = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
