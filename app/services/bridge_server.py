import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Dict, Any, Optional
import requests
from app.services.geocoding import GeocodingService, GeocodingError, PopulationService
from app.services.impact_physics import (
    calculate_great_circle_distance_km,
    load_missiles,
    check_within_range,
    compute_impact_effects,
)


# ---- simulator api (called directly by the tkinter window) ----
class SimulatorApi:
    """lookups and the launch simulation, run on the tkinter window's worker threads"""

    def __init__(self):
        self.geocoding_service = GeocodingService()
        self.population_service = PopulationService()
        self.missiles = load_missiles()
        self.missile_map = {m["id"]: m for m in self.missiles}

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
        except (GeocodingError, requests.RequestException, OSError) as err:
            print(f"reverse geocode fallback used: {err}")
            return {
                "label": f"Coordinates ({latitude:.3f}, {longitude:.3f})",
                "longitude": longitude,
                "latitude": latitude,
                "provider_place_id": "manual-pin",
                "attribution": "Manual Pin",
            }

    def get_population(self, longitude: float, latitude: float, label: str = "") -> Dict[str, Any]:
        return self.population_service.get_population_and_density(longitude, latitude, label)

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

        # resolve target population and density
        pop_info = self.population_service.get_population_and_density(
            dest["longitude"], dest["latitude"], dest.get("label", "")
        )
        density = float(pop_info["density_per_km2"]) if pop_density_per_km2 is None else float(pop_density_per_km2)

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

# ---- local http server ----
GLOBE_DIR = Path(__file__).resolve().parent.parent / "visualization" / "globe"


class GlobeBridgeServer:
    """local http server: serves the globe page, GET /api/state and POST /api/pick"""

    def __init__(self, on_globe_pick: Optional[Callable[[str, float, float], None]] = None, port: int = 0):
        self.port = port
        self.on_globe_pick = on_globe_pick
        self.api = SimulatorApi()
        self._lock = threading.Lock()
        self.state: Dict[str, Any] = {
            "version": 1,
            "origin": None,
            "destination": None,
            "missile": None,
            "in_range": True,
            "range_message": "",
            "launched": False,
            "impact": None,
            "pick_mode": "origin",
            "fly_to": None,
        }
        self._server: Optional[ThreadingHTTPServer] = None

    def update_state(self, **kwargs: Any) -> None:
        with self._lock:
            self.state.update(kwargs)
            self.state["version"] = int(self.state.get("version", 0)) + 1

    def get_state_json(self) -> bytes:
        with self._lock:
            return json.dumps(self.state).encode("utf-8")

    def start(self) -> str:
        bridge = self

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(GLOBE_DIR), **kwargs)

            def log_message(self, format: str, *args: Any) -> None:
                pass  # suppress request logs to keep terminal quiet

            def do_GET(self) -> None:
                if self.path.startswith("/api/state"):
                    payload = bridge.get_state_json()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                return super().do_GET()

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
                try:
                    data = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    data = {}

                if self.path.startswith("/api/pick"):
                    role = str(data.get("role", "destination"))
                    lon = float(data.get("longitude", 0.0))
                    lat = float(data.get("latitude", 0.0))
                    if bridge.on_globe_pick:
                        bridge.on_globe_pick(role, lon, lat)
                    self._send_json({"status": "ok"})
                    return

                self.send_response(404)
                self.end_headers()

            def _send_json(self, obj: Any) -> None:
                payload = json.dumps(obj).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(payload)

        class ReusableThreadingServer(ThreadingHTTPServer):
            allow_reuse_address = True

        self._server = ReusableThreadingServer(("127.0.0.1", self.port), Handler)
        # assign dynamic port allocated by the os
        self.port = int(self._server.server_address[1])
        thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        thread.start()
        return f"http://127.0.0.1:{self.port}/index.html"
