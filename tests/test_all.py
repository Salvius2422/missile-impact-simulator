import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.data.database import Scenario
from app.data.database import ScenarioDatabase
from app.services.geocoding import GeocodingService
from app.services.impact_physics import calculate_great_circle_distance_km
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

        nuclear_missiles = [m for m in missiles if m["nuclear_capable"]]
        conv_missiles = [m for m in missiles if not m["nuclear_capable"]]
        self.assertGreaterEqual(len(nuclear_missiles), 25)
        self.assertGreaterEqual(len(conv_missiles), 10)

    def test_distance_calculation(self):
        # new delhi to beijing distance check
        dist = calculate_great_circle_distance_km(77.2090, 28.6139, 116.4074, 39.9042)
        self.assertGreater(dist, 3700)
        self.assertLess(dist, 3900)

    def test_range_limit_lock(self):
        missiles = load_missiles()
        agni_v = next(m for m in missiles if m["id"] == "agni_v")
        hellfire = next(m for m in missiles if m["id"] == "hellfire")

        # 3790 km is in range for agni-v (max 5500 km)
        res_agni = check_within_range(3790, agni_v)
        self.assertTrue(res_agni["in_range"])

        # 3790 km is out of range for hellfire (max 11 km)
        res_hellfire = check_within_range(3790, hellfire)
        self.assertFalse(res_hellfire["in_range"])
        self.assertIn("out of range", res_hellfire["reason"].lower())

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

        # check speed and flight time calculations
        self.assertIn("top_speed_kmh", effects)
        self.assertIn("avg_speed_kmh", effects)
        self.assertIn("flight_time_top_min", effects)
        self.assertIn("flight_time_avg_min", effects)
        self.assertGreater(effects["flight_time_avg_min"], effects["flight_time_top_min"])

    def test_offline_geocoding_fallback(self):
        geo = GeocodingService()
        candidates = geo.search_city("Delhi")
        self.assertGreaterEqual(len(candidates), 1)
        self.assertIn("Delhi", candidates[0].label)

        rev = geo.reverse_geocode(77.2090, 28.6139)
        self.assertTrue("Delhi" in rev.label or "Coordinates" in rev.label or "Point" in rev.label)

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
            missile_id="agni_v",
        )
        row_id = db.save_scenario(scenario)
        self.assertGreater(row_id, 0)

        scenarios = db.list_scenarios()
        self.assertEqual(len(scenarios), 1)
        self.assertEqual(scenarios[0].scenario_name, "Test Scenario Agni-V")
        self.assertEqual(scenarios[0].origin_city_label, "New Delhi, India")
        self.assertEqual(scenarios[0].missile_id, "agni_v")

        # test delete scenario
        db.delete_scenario(row_id)
        scenarios_after = db.list_scenarios()
        self.assertEqual(len(scenarios_after), 0)

        db_path.unlink(missing_ok=True)

    def test_simulator_api(self):
        from app.services.bridge_server import SimulatorApi
        api = SimulatorApi()
        self.assertGreaterEqual(len(api.missiles), 50)

        rev = api.reverse_geocode(77.2090, 28.6139)
        self.assertIn("longitude", rev)

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


    def test_target_specific_realism(self):
        missiles = load_missiles()
        agni_v = next(m for m in missiles if m["id"] == "agni_v")
        
        # sonipat target
        eff_sonipat = compute_impact_effects(
            missile=agni_v,
            distance_km=46.1,
            is_nuclear=True,
            nuclear_yield_kt=250.0,
            pop_density_per_km2=2603.0,
        )
        
        # delhi target
        eff_delhi = compute_impact_effects(
            missile=agni_v,
            distance_km=5.9,
            is_nuclear=True,
            nuclear_yield_kt=250.0,
            pop_density_per_km2=11300.0,
        )
        
        # verify distinct values
        self.assertNotEqual(eff_sonipat["estimates"]["estimated_fatalities"], eff_delhi["estimates"]["estimated_fatalities"])
        self.assertNotEqual(eff_sonipat["estimates"]["structures_destroyed"], eff_delhi["estimates"]["structures_destroyed"])
        self.assertNotEqual(eff_sonipat["radii_km"]["heavy_blast_20psi_km"], eff_delhi["radii_km"]["heavy_blast_20psi_km"])
        self.assertNotEqual(eff_sonipat["flight_time_avg_min"], eff_delhi["flight_time_avg_min"])
        self.assertIn("blast_pattern", eff_sonipat)
        self.assertIn("blast_pattern", eff_delhi)


if __name__ == "__main__":
    unittest.main()
