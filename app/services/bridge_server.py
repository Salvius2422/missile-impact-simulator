import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Dict, Any, Optional
from app.services.webview_api import SimulatorApi

GLOBE_DIR = Path(__file__).resolve().parent.parent / "visualization" / "globe"


class GlobeBridgeServer:
    """Provides HTTP serving for the 3D Globe and REST endpoints for Python API interaction."""

    def __init__(self, on_globe_pick: Optional[Callable[[str, float, float], None]] = None, port: int = 8765):
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
                pass  # Keep console clean

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
                except Exception:
                    data = {}

                # REST API fallback endpoints
                if self.path.startswith("/api/get_missiles"):
                    res = bridge.api.get_missiles()
                    self._send_json(res)
                    return

                if self.path.startswith("/api/search_city"):
                    # data is args list [query]
                    q = data[0] if isinstance(data, list) and data else str(data.get("query", ""))
                    res = bridge.api.search_city(q)
                    self._send_json(res)
                    return

                if self.path.startswith("/api/reverse_geocode"):
                    if isinstance(data, list) and len(data) >= 2:
                        lon, lat = float(data[0]), float(data[1])
                    else:
                        lon = float(data.get("longitude", 0.0))
                        lat = float(data.get("latitude", 0.0))
                    res = bridge.api.reverse_geocode(lon, lat)
                    self._send_json(res)
                    return

                if self.path.startswith("/api/get_population"):
                    if isinstance(data, list) and len(data) >= 2:
                        lon, lat = float(data[0]), float(data[1])
                        lbl = str(data[2]) if len(data) > 2 else ""
                    else:
                        lon = float(data.get("longitude", 0.0))
                        lat = float(data.get("latitude", 0.0))
                        lbl = str(data.get("label", ""))
                    res = bridge.api.get_population(lon, lat, lbl)
                    self._send_json(res)
                    return

                if self.path.startswith("/api/simulate_launch"):
                    if isinstance(data, list) and len(data) >= 5:
                        orig = data[0]
                        dest = data[1]
                        m_id = data[2]
                        nuke = data[3]
                        y_kt = data[4]
                        dens = data[5] if len(data) > 5 else None
                    else:
                        orig = data.get("origin", {})
                        dest = data.get("destination", {})
                        m_id = str(data.get("missile_id", "agni_v"))
                        nuke = bool(data.get("is_nuclear", True))
                        y_kt = float(data.get("yield_kt", 250))
                        dens = data.get("density")
                    res = bridge.api.simulate_launch(orig, dest, m_id, nuke, y_kt, dens)
                    self._send_json(res)
                    return

                if self.path.startswith("/api/save_scenario"):
                    if isinstance(data, list) and len(data) >= 11:
                        res = bridge.api.save_scenario(*data)
                    else:
                        res = bridge.api.save_scenario(
                            data.get("name", "Scenario"),
                            data.get("origin_label", ""),
                            data.get("origin_lon", 0.0),
                            data.get("origin_lat", 0.0),
                            data.get("dest_label", ""),
                            data.get("dest_lon", 0.0),
                            data.get("dest_lat", 0.0),
                            data.get("missile_id", "agni_v"),
                            data.get("is_nuclear", True),
                            data.get("yield_kt", 250),
                            data.get("density", 5000),
                        )
                    self._send_json(res)
                    return

                if self.path.startswith("/api/list_scenarios"):
                    res = bridge.api.list_scenarios()
                    self._send_json(res)
                    return

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
        thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        thread.start()
        return f"http://127.0.0.1:{self.port}/index.html"
