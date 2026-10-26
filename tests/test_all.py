import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json
from app.data.models import PlaceCandidate, Scenario
from app.data.database import ScenarioDatabase
from app.services.mapbox_geocoding import MapboxGeocodingService, validate_lon_lat
from app.services.distance_service import calculate_great_circle_distance_km
from app.services.impact_physics import load_missiles, check_within_range, compute_impact_effects


class TestMissileSimulator(unittest.TestCase):

    def test_missiles_data(self):
        missiles = load_missiles()
        self.assertGreaterEqual(len(missiles), 50)
        countries = set(m["country"] for m in missiles)
        self.assertIn("India", countries)
        self.assertIn("United States", countries)
        self.assertIn("Russia", countries)
        self.assertIn("China", countries)
        self.assertIn("France", countries)
        self.assertIn("United Kingdom", countries)
        self.assertNotIn("Pakistan", countries)

        # Ensure both nuclear and conventional exist
        nuclear_missiles = [m for m in missiles if m["nuclear_capable"]]
        conv_missiles = [m for m in missiles if not m["nuclear_capable"]]
        self.assertGreaterEqual(len(nuclear_missiles), 25)
        self.assertGreaterEqual(len(conv_missiles), 10)

    def test_distance_calculation(self):
        # New Delhi (77.2090, 28.6139) to Beijing (116.4074, 39.9042)
        dist = calculate_great_circle_distance_km(77.2090, 28.6139, 116.4074, 39.9042)
        self.assertGreater(dist, 3700)
        self.assertLess(dist, 3900)

    def test_range_limit_lock(self):
        missiles = load_missiles()
        agni_v = next(m for m in missiles if m["id"] == "agni_v")
        hellfire = next(m for m in missiles if m["id"] == "hellfire")

        # 3790 km is in range for Agni-V (max 5500 km)
        res_agni = check_within_range(3790, agni_v)
        self.assertTrue(res_agni["in_range"])

        # 3790 km is OUT OF RANGE for Hellfire (max 11 km)
        res_hellfire = check_within_range(3790, hellfire)
        self.assertFalse(res_hellfire["in_range"])
        self.assertIn("OUT OF RANGE", res_hellfire["reason"])

    def test_nuclear_impact_effects(self):
        missiles = load_missiles()
        agni_v = next(m for m in missiles if m["id"] == "agni_v")
        effects = compute_impact_effects(
            missile=agni_v,
            distance_km=3790,
            is_nuclear=True,
            nuclear_yield_kt=250.0,
            pop_density_per_km2=5000.0,
        )
        self.assertIn("Nuclear (250 kt)", effects["warhead_mode"])
        radii = effects["radii_km"]
        self.assertGreater(radii["fireball_km"], 0)
        self.assertGreater(radii["heavy_blast_20psi_km"], radii["fireball_km"])
        self.assertGreater(radii["moderate_blast_5psi_km"], radii["heavy_blast_20psi_km"])
        self.assertGreater(radii["light_blast_1psi_km"], radii["moderate_blast_5psi_km"])

        est = effects["estimates"]
        self.assertGreater(est["estimated_fatalities"], 0)
        self.assertGreater(est["structures_destroyed"], 0)

    def test_offline_geocoding_fallback(self):
        geo = MapboxGeocodingService()
        candidates = geo.search_city("Delhi")
        self.assertGreaterEqual(len(candidates), 1)
        self.assertIn("Delhi", candidates[0].label)

        # Reverse geocoding resolves to real location name via OSM over Wi-Fi, or Point if completely offline
        rev = geo.reverse_geocode(77.2090, 28.6139)
        self.assertTrue("Delhi" in rev.label or "Point" in rev.label)

    def test_database_scenario_save_load(self):
        db_path = Path("test_scenarios.db")
        if db_path.exists():
            db_path.unlink()

        db = ScenarioDatabase(db_path=db_path)
        scenario = Scenario(
            scenario_name="Test Scenario Agni-V",
            origin_city_label="New Delhi, India",
            origin_longitude=77.2090,
            origin_latitude=28.6139,
            destination_city_label="Beijing, China",
            destination_longitude=116.4074,
            destination_latitude=39.9042,
            selected_reference_record_id="agni_v",
        )
        row_id = db.save_scenario(scenario)
        self.assertGreater(row_id, 0)

        scenarios = db.list_scenarios()
        self.assertEqual(len(scenarios), 1)
        self.assertEqual(scenarios[0].scenario_name, "Test Scenario Agni-V")
        self.assertEqual(scenarios[0].origin_city_label, "New Delhi, India")

        # Cleanup
        db_path.unlink(missing_ok=True)

    def test_simulator_api(self):
        from app.services.webview_api import SimulatorApi
        api = SimulatorApi()
        missiles = api.get_missiles()
        self.assertGreaterEqual(len(missiles), 50)

        # Test search
        res = api.search_city("Delhi")
        self.assertTrue(res["success"])
        self.assertGreater(len(res["candidates"]), 0)

        # Test reverse geocode
        rev = api.reverse_geocode(77.2090, 28.6139)
        self.assertIn("longitude", rev)

        # Test simulation with automatic population
        sim = api.simulate_launch(
            origin={"longitude": 77.2090, "latitude": 28.6139},
            dest={"longitude": 116.4074, "latitude": 39.9042, "label": "Beijing, China"},
            missile_id="agni_v",
            is_nuclear=True,
            nuclear_yield_kt=250.0,
        )
        self.assertTrue(sim["success"])
        self.assertTrue(sim["in_range"])
        self.assertIn("impact", sim)
        self.assertIn("population_info", sim)
        self.assertGreater(sim["population_info"]["population"], 0)

    def test_tkinter_components(self):
        """Verifies that mandatory Tkinter UI components and dialogs initialize properly."""
        import tkinter as tk
        from app.ui.main_window import MissileCatalogDialog, PhysicsInfoDialog

        root = tk.Tk()
        root.withdraw()
        try:
            missiles = load_missiles()
            catalog = MissileCatalogDialog(root, missiles)
            self.assertEqual(len(catalog.tree.get_children()), len(missiles))
            catalog.destroy()

            physics_dlg = PhysicsInfoDialog(root)
            self.assertIsNotNone(physics_dlg)
            physics_dlg.destroy()
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
