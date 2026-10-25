import json
import math
from pathlib import Path
from typing import Dict, Any, List

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "reference_data.json"


def load_missiles() -> List[Dict[str, Any]]:
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f).get("missiles", [])


def check_within_range(distance_km: float, missile: Dict[str, Any]) -> Dict[str, Any]:
    """Verifies whether the target distance is within the missile's operational range envelope."""
    max_range = float(missile["max_range_km"])
    min_range = float(missile.get("min_range_km", 0.0))

    if distance_km > max_range:
        return {
            "in_range": False,
            "reason": (
                f"OUT OF RANGE: Destination is {distance_km:,.1f} km away, which exceeds "
                f"{missile['name']}'s maximum range of {max_range:,.0f} km."
            ),
        }
    return {
        "in_range": True,
        "below_min_range_warning": distance_km < min_range,
        "reason": f"Target is within {missile['name']} maximum range ({distance_km:,.1f} / {max_range:,.0f} km).",
    }


def compute_impact_effects(
    missile: Dict[str, Any],
    distance_km: float,
    is_nuclear: bool,
    nuclear_yield_kt: float,
    pop_density_per_km2: float,
) -> Dict[str, Any]:
    """
    Calculates textbook blast/thermal radii (Glasstone & Dolan cube-root scaling),
    estimated flight duration, affected population, casualties, and structures destroyed.
    """
    yield_kt = float(nuclear_yield_kt) if is_nuclear else float(missile["conventional_yield_kt"])
    yield_kt = max(yield_kt, 0.000001)

    y_cbrt = yield_kt ** (1.0 / 3.0)

    # Standard scaling radii in km for surface/low-airburst detonation
    fireball_km = round(0.09 * (yield_kt ** 0.4), 3)
    heavy_blast_20psi_km = round(0.28 * y_cbrt, 3)      # Complete destruction of reinforced structures
    moderate_blast_5psi_km = round(0.70 * y_cbrt, 3)    # Collapse of most residential/commercial buildings
    thermal_3rd_deg_km = round(1.20 * (yield_kt ** 0.41), 3) if is_nuclear else round(0.35 * y_cbrt, 3)
    light_blast_1psi_km = round(1.90 * y_cbrt, 3)       # Window breakage & light structural damage

    # Ring areas (km^2)
    area_heavy = math.pi * (heavy_blast_20psi_km ** 2)
    area_moderate_ring = max(0.0, math.pi * (moderate_blast_5psi_km ** 2) - area_heavy)
    outer_radius = max(light_blast_1psi_km, thermal_3rd_deg_km)
    area_light_ring = max(0.0, math.pi * (outer_radius ** 2) - (area_heavy + area_moderate_ring))

    # Population exposure & casualty estimation by zone
    pop_heavy = area_heavy * pop_density_per_km2
    pop_moderate = area_moderate_ring * pop_density_per_km2
    pop_light = area_light_ring * pop_density_per_km2

    est_fatalities = int(round(pop_heavy * 0.98 + pop_moderate * 0.50 + pop_light * 0.05))
    est_injuries = int(round(pop_heavy * 0.02 + pop_moderate * 0.45 + pop_light * 0.35))
    total_exposed = int(round(pop_heavy + pop_moderate + pop_light))

    # Approximate structures/buildings destroyed (~180 structures per 1,000 urban residents in 20psi/5psi zones)
    structures_per_km2 = pop_density_per_km2 * 0.18
    est_structures_destroyed = int(round((area_heavy * 0.99 + area_moderate_ring * 0.75) * structures_per_km2))

    # Flight time estimate based on average Mach speed (1 Mach ≈ 1,225 km/h)
    speed_kmh = float(missile["speed_mach"]) * 1225.0
    flight_minutes = round((distance_km / max(speed_kmh, 1.0)) * 60.0, 1)

    return {
        "warhead_mode": f"Nuclear ({yield_kt:g} kt)" if is_nuclear else f"Conventional ({yield_kt * 1000:,.1f} tons TNT eq.)",
        "yield_kt": yield_kt,
        "flight_time_min": flight_minutes,
        "radii_km": {
            "fireball_km": fireball_km,
            "heavy_blast_20psi_km": heavy_blast_20psi_km,
            "moderate_blast_5psi_km": moderate_blast_5psi_km,
            "thermal_3rd_deg_km": thermal_3rd_deg_km,
            "light_blast_1psi_km": light_blast_1psi_km,
        },
        "estimates": {
            "total_exposed": total_exposed,
            "estimated_fatalities": est_fatalities,
            "estimated_injuries": est_injuries,
            "structures_destroyed": est_structures_destroyed,
            "pop_density_used": pop_density_per_km2,
        },
    }
