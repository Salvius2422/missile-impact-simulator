import sqlite3
from pathlib import Path
from typing import List
from app.data.models import Scenario

DB_PATH = Path(__file__).resolve().parent.parent.parent / "scenarios.db"


class ScenarioDatabase:
    """Manages local SQLite persistence for saved missile simulation scenarios."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS scenarios (
                        scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        scenario_name TEXT NOT NULL,
                        origin_city_label TEXT NOT NULL,
                        origin_longitude REAL NOT NULL,
                        origin_latitude REAL NOT NULL,
                        destination_city_label TEXT NOT NULL,
                        destination_longitude REAL NOT NULL,
                        destination_latitude REAL NOT NULL,
                        map_provider TEXT,
                        provider_place_ids_or_source_metadata TEXT,
                        selected_reference_record_id TEXT,
                        hypothetical_assessment_zone_parameters TEXT,
                        population_data_source TEXT,
                        assumptions_and_uncertainty_notes TEXT,
                        created_at TEXT,
                        updated_at TEXT
                    )
                    """
                )
        finally:
            conn.close()

    def save_scenario(self, scenario: Scenario) -> int:
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                cur = conn.execute(
                    """
                    INSERT INTO scenarios (
                        scenario_name, origin_city_label, origin_longitude, origin_latitude,
                        destination_city_label, destination_longitude, destination_latitude,
                        map_provider, provider_place_ids_or_source_metadata,
                        selected_reference_record_id, hypothetical_assessment_zone_parameters,
                        population_data_source, assumptions_and_uncertainty_notes,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scenario.scenario_name,
                        scenario.origin_city_label,
                        scenario.origin_longitude,
                        scenario.origin_latitude,
                        scenario.destination_city_label,
                        scenario.destination_longitude,
                        scenario.destination_latitude,
                        scenario.map_provider,
                        scenario.provider_place_ids_or_source_metadata,
                        scenario.selected_reference_record_id,
                        scenario.hypothetical_assessment_zone_parameters,
                        scenario.population_data_source,
                        scenario.assumptions_and_uncertainty_notes,
                        scenario.created_at,
                        scenario.updated_at,
                    ),
                )
                return int(cur.lastrowid)
        finally:
            conn.close()

    def list_scenarios(self) -> List[Scenario]:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM scenarios ORDER BY scenario_id DESC").fetchall()
            return [Scenario(**dict(r)) for r in rows]
        finally:
            conn.close()
