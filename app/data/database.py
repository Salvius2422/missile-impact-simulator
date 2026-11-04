import sqlite3
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional


# ---- data models ----
@dataclass
class PlaceCandidate:
    """geocoding search result candidate"""
    label: str
    longitude: float
    latitude: float
    provider_place_id: str
    attribution: str = "OpenStreetMap"


@dataclass
class Scenario:
    """saved simulation scenario row"""
    scenario_name: str
    origin_city_label: str
    origin_longitude: float
    origin_latitude: float
    destination_city_label: str
    destination_longitude: float
    destination_latitude: float
    map_provider: str = "OpenStreetMap"
    source_info: str = ""
    missile_id: Optional[str] = None
    params: str = '{"is_nuclear": true, "yield_kt": 250.0}'
    population_data_source: str = "GeoNames / OpenStreetMap"
    notes: str = "Blast estimation using Glasstone-Dolan scaling."
    scenario_id: Optional[int] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---- scenario storage ----
DB_PATH = Path(__file__).resolve().parent.parent.parent / "scenarios.db"


class ScenarioDatabase:
    """sqlite storage for simulation scenarios"""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                # drop old schema if column names were from an earlier version
                cols = [row[1] for row in conn.execute("PRAGMA table_info(scenarios)").fetchall()]
                if cols and "missile_id" not in cols:
                    conn.execute("DROP TABLE scenarios")

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
                        source_info TEXT,
                        missile_id TEXT,
                        params TEXT,
                        population_data_source TEXT,
                        notes TEXT,
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
                        map_provider, source_info, missile_id, params,
                        population_data_source, notes, created_at, updated_at
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
                        scenario.source_info,
                        scenario.missile_id,
                        scenario.params,
                        scenario.population_data_source,
                        scenario.notes,
                        scenario.created_at,
                        scenario.updated_at,
                    ),
                )
                return int(cur.lastrowid)
        finally:
            conn.close()

    def delete_scenario(self, scenario_id: int) -> None:
        """deletes a saved scenario by id"""
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                conn.execute("DELETE FROM scenarios WHERE scenario_id = ?", (scenario_id,))
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
