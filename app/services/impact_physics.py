import json
import math
from pathlib import Path
from typing import Dict, Any, List
from app.services.geocoding import validate_lon_lat


# ---- great-circle distance ----
EARTH_MEAN_RADIUS_KM = 6371.0088


def calculate_great_circle_distance_km(
    origin_lon: float,
    origin_lat: float,
    dest_lon: float,
    dest_lat: float,
) -> float:
    """calculates great-circle distance in kilometers using haversine"""
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


# ---- blast physics ----
DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "reference_data.json"

# glasstone & dolan (1977) blast scaling constants (yield Y in kt TNT)
FIREBALL_COEFF = 0.09
FIREBALL_EXP = 0.40
HEAVY_BLAST_20PSI_COEFF = 0.28
MODERATE_BLAST_5PSI_COEFF = 0.70
THERMAL_NUCLEAR_COEFF = 1.20
THERMAL_NUCLEAR_EXP = 0.41
THERMAL_CONV_COEFF = 0.35
LIGHT_BLAST_1PSI_COEFF = 1.90

# annular zone casualty & damage fractions
FATALITY_RATE_HEAVY = 0.98
FATALITY_RATE_MODERATE = 0.50
FATALITY_RATE_LIGHT = 0.05

INJURY_RATE_HEAVY = 0.02
INJURY_RATE_MODERATE = 0.45
INJURY_RATE_LIGHT = 0.35

STRUCTURES_PER_PERSON = 0.18  # ~180 buildings per 1,000 residents
STRUCT_DESTROY_HEAVY = 0.99
STRUCT_DESTROY_MODERATE = 0.75

MACH_TO_KMH = 1225.0  # standard sea-level speed of sound in km/h
BALLISTIC_AVG_RATIO = 0.65  # avg flight speed vs peak terminal mach for ballistic missiles
CRUISE_AVG_RATIO = 0.85     # avg flight speed vs peak mach for cruise/tactical missiles


def load_missiles() -> List[Dict[str, Any]]:
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f).get("missiles", [])


def check_within_range(distance_km: float, missile: Dict[str, Any]) -> Dict[str, Any]:
    max_range = float(missile["max_range_km"])
    min_range = float(missile.get("min_range_km", 0.0))

    if distance_km > max_range:
        return {
            "in_range": False,
            "reason": (
                f"Out of range: {distance_km:,.1f} km exceeds "
                f"{missile['name']} maximum range of {max_range:,.0f} km."
            ),
        }
    return {
        "in_range": True,
        "below_min_range_warning": distance_km < min_range,
        "reason": f"Target in range: {distance_km:,.1f} km / {max_range:,.0f} km ({missile['name']}).",
    }


def get_speed_stats(missile: Dict[str, Any], distance_km: float = 0.0) -> Dict[str, float]:
    """get top and average speed in mach/kmh plus flight times in minutes"""
    top_mach = float(missile.get("speed_mach", 1.0))
    ratio = BALLISTIC_AVG_RATIO if top_mach >= 5.0 else CRUISE_AVG_RATIO
    avg_mach = round(top_mach * ratio, 2)

    top_kmh = round(top_mach * MACH_TO_KMH, 1)
    avg_kmh = round(avg_mach * MACH_TO_KMH, 1)

    flight_top_min = round((distance_km / max(top_kmh, 1.0)) * 60.0, 1)
    flight_avg_min = round((distance_km / max(avg_kmh, 1.0)) * 60.0, 1)

    return {
        "top_speed_mach": top_mach,
        "top_speed_kmh": top_kmh,
        "avg_speed_mach": avg_mach,
        "avg_speed_kmh": avg_kmh,
        "flight_time_top_min": flight_top_min,
        "flight_time_avg_min": flight_avg_min,
        "flight_time_min": flight_avg_min,
    }


def get_target_environment_factors(density: float) -> Dict[str, Any]:
    """blast and thermal modifiers by urban density: buildings reflect blast and block heat"""
    if density >= 12000.0:
        urban_heavy = 1.04
        urban_mod = 0.94
        urban_light = 0.88
        thermal_scale = 0.76
        pattern = "Dense urban canyon reflection with structural thermal shielding"
    elif density >= 5000.0:
        urban_heavy = 1.02
        urban_mod = 0.97
        urban_light = 0.93
        thermal_scale = 0.85
        pattern = "Metropolitan mixed-structure reflection and partial shadowing"
    elif density >= 1500.0:
        urban_heavy = 1.00
        urban_mod = 0.99
        urban_light = 0.97
        thermal_scale = 0.92
        pattern = "Suburban distributed propagation with moderate line-of-sight"
    else:
        urban_heavy = 1.00
        urban_mod = 1.01
        urban_light = 1.04
        thermal_scale = 1.02
        pattern = "Open terrain planar expansion with unshielded thermal field"

    return {
        "heavy_factor": urban_heavy,
        "mod_factor": urban_mod,
        "light_factor": urban_light,
        "thermal_factor": thermal_scale,
        "blast_pattern": pattern,
    }


def compute_impact_effects(
    missile: Dict[str, Any],
    distance_km: float,
    is_nuclear: bool,
    nuclear_yield_kt: float,
    pop_density_per_km2: float,
) -> Dict[str, Any]:
    yield_kt = float(nuclear_yield_kt) if is_nuclear else float(missile.get("conventional_yield_kt", 0.001))
    yield_kt = max(yield_kt, 0.000001)

    y_cbrt = yield_kt ** (1.0 / 3.0)
    env = get_target_environment_factors(pop_density_per_km2)

    # blast and thermal radii in km with target environmental effects
    fireball_km = round(FIREBALL_COEFF * (yield_kt ** FIREBALL_EXP), 3)
    heavy_blast_20psi_km = round(HEAVY_BLAST_20PSI_COEFF * y_cbrt * env["heavy_factor"], 3)
    heavy_blast_20psi_km = max(heavy_blast_20psi_km, round(fireball_km + 0.001, 3))

    moderate_blast_5psi_km = round(MODERATE_BLAST_5PSI_COEFF * y_cbrt * env["mod_factor"], 3)
    moderate_blast_5psi_km = max(moderate_blast_5psi_km, round(heavy_blast_20psi_km + 0.001, 3))

    thermal_base = (
        THERMAL_NUCLEAR_COEFF * (yield_kt ** THERMAL_NUCLEAR_EXP)
        if is_nuclear
        else THERMAL_CONV_COEFF * y_cbrt
    )
    thermal_3rd_deg_km = round(thermal_base * env["thermal_factor"], 3)

    light_blast_1psi_km = round(LIGHT_BLAST_1PSI_COEFF * y_cbrt * env["light_factor"], 3)
    light_blast_1psi_km = max(light_blast_1psi_km, round(moderate_blast_5psi_km + 0.001, 3))

    area_heavy = math.pi * (heavy_blast_20psi_km ** 2)
    area_moderate_ring = max(0.0, math.pi * (moderate_blast_5psi_km ** 2) - area_heavy)
    outer_radius = max(light_blast_1psi_km, thermal_3rd_deg_km)
    area_light_ring = max(0.0, math.pi * (outer_radius ** 2) - (area_heavy + area_moderate_ring))

    raw_heavy = area_heavy * pop_density_per_km2
    raw_moderate = area_moderate_ring * pop_density_per_km2
    raw_light = area_light_ring * pop_density_per_km2
    # exposure is density x area for each ring; not capped by the nearest town's population,
    # because blast rings often reach well beyond that town.
    pop_heavy = raw_heavy
    pop_moderate = raw_moderate
    pop_light = raw_light

    est_fatalities = int(round(
        pop_heavy * FATALITY_RATE_HEAVY
        + pop_moderate * FATALITY_RATE_MODERATE
        + pop_light * FATALITY_RATE_LIGHT
    ))
    est_injuries = int(round(
        pop_heavy * INJURY_RATE_HEAVY
        + pop_moderate * INJURY_RATE_MODERATE
        + pop_light * INJURY_RATE_LIGHT
    ))
    total_exposed = int(round(pop_heavy + pop_moderate + pop_light))

    structures_per_km2 = pop_density_per_km2 * STRUCTURES_PER_PERSON
    raw_destroyed = (area_heavy * STRUCT_DESTROY_HEAVY + area_moderate_ring * STRUCT_DESTROY_MODERATE) * structures_per_km2
    est_structures_destroyed = int(round(raw_destroyed))

    speed_stats = get_speed_stats(missile, distance_km)

    return {
        "warhead_mode": (
            f"Nuclear ({yield_kt:g} kt)"
            if is_nuclear
            else f"Conventional ({yield_kt * 1000:,.1f} tons TNT eq.)"
        ),
        "yield_kt": yield_kt,
        "blast_pattern": env["blast_pattern"],
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
        **speed_stats,
    }
