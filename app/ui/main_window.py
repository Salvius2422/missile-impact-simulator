import json
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from typing import Optional, Dict, Any
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from app.data.models import PlaceCandidate, Scenario
from app.data.database import ScenarioDatabase
from app.services.mapbox_geocoding import MapboxGeocodingService
from app.services.distance_service import calculate_great_circle_distance_km
from app.services.impact_physics import load_missiles, check_within_range, compute_impact_effects
from app.services.bridge_server import GlobeBridgeServer
from app.ui.city_search import CitySearchPanel


class MainWindow(tk.Tk):
    """Complete Tkinter Control Panel synced live with the 3D CesiumJS Globe."""

    def __init__(self):
        super().__init__()
        self.title("Real-World Missile Impact Simulator — 3D Globe & Impact Assessment")
        self.geometry("1240x820")
        self.minsize(1080, 740)

        self.geocoding_service = MapboxGeocodingService()
        self.db = ScenarioDatabase()
        self.missiles = load_missiles()
        self.selected_missile: Dict[str, Any] = self.missiles[0]
        self.in_range: bool = True

        self.bridge = GlobeBridgeServer(on_globe_pick=self._handle_globe_pick_threadsafe)
        self.globe_url = self.bridge.start()

        self._configure_styles()
        self._build_layout()
        self._on_missile_selected()

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=5)
        self.columnconfigure(1, weight=6)
        self.rowconfigure(1, weight=1)

        # Top Bar
        top_bar = ttk.Frame(self, padding=(12, 8))
        top_bar.grid(row=0, column=0, columnspan=2, sticky="ew")

        ttk.Label(
            top_bar,
            text="Real-World Missile Impact Simulator",
            font=("Segoe UI", 14, "bold"),
        ).pack(side="left")

        ttk.Button(top_bar, text="🌐 Open Interactive 3D Globe", command=self.open_globe).pack(
            side="right", padx=4
        )
        ttk.Button(top_bar, text="📂 Load Scenario", command=self._load_scenario_dialog).pack(
            side="right", padx=4
        )
        ttk.Button(top_bar, text="💾 Save Scenario", command=self._save_scenario_dialog).pack(
            side="right", padx=4
        )

        # Left Column - Control Panel
        left_col = ttk.Frame(self, padding=(12, 4))
        left_col.grid(row=1, column=0, sticky="nsew")
        left_col.columnconfigure(0, weight=1)

        self.origin_panel = CitySearchPanel(
            left_col,
            title="1. Origin City (Click/Drag on 3D Globe OR Search Below)",
            geocoding_service=self.geocoding_service,
            on_selection_changed=lambda _c: self._recalculate_range_and_sync(launched=False),
        )
        self.origin_panel.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        self.destination_panel = CitySearchPanel(
            left_col,
            title="2. Destination City (Click/Drag Inside Range Circle OR Search Below)",
            geocoding_service=self.geocoding_service,
            on_selection_changed=lambda _c: self._recalculate_range_and_sync(launched=False),
        )
        self.destination_panel.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        # Missile & Warhead Config
        missile_frame = ttk.LabelFrame(left_col, text="3. Missile System & Warhead Configuration", padding=10)
        missile_frame.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        missile_frame.columnconfigure(1, weight=1)

        ttk.Label(missile_frame, text="Select Missile:").grid(row=0, column=0, sticky="w", pady=4)
        self.missile_combo = ttk.Combobox(
            missile_frame,
            state="readonly",
            values=[f"[{m['country']}] {m['name']} — {m['max_range_km']:,} km ({'☢ Nuke' if m['nuclear_capable'] else '💥 Conv'})" for m in self.missiles],
        )
        self.missile_combo.current(0)
        self.missile_combo.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=4)
        self.missile_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_missile_selected())

        self.missile_specs_var = tk.StringVar()
        ttk.Label(missile_frame, textvariable=self.missile_specs_var, foreground="#1e40af").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(2, 6)
        )

        self.nuclear_var = tk.BooleanVar(value=True)
        self.nuclear_check = ttk.Checkbutton(
            missile_frame,
            text="Equip Nuclear Warhead",
            variable=self.nuclear_var,
            command=self._on_warhead_toggled,
        )
        self.nuclear_check.grid(row=2, column=0, sticky="w", pady=4)

        yield_box = ttk.Frame(missile_frame)
        yield_box.grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=4)
        ttk.Label(yield_box, text="Yield (kt):").pack(side="left")
        self.yield_var = tk.StringVar(value="250")
        self.yield_combo = ttk.Combobox(
            yield_box,
            textvariable=self.yield_var,
            values=["1", "10", "15", "40", "100", "250", "335", "500", "1000"],
            width=10,
        )
        self.yield_combo.pack(side="left", padx=6)

        ttk.Label(missile_frame, text="Target Urban Density:").grid(row=3, column=0, sticky="w", pady=4)
        self.density_combo = ttk.Combobox(
            missile_frame,
            state="readonly",
            values=[
                "Dense Metropolis (12,000 people / km²)",
                "Major Urban City (5,000 people / km²)",
                "Suburban / Town (1,500 people / km²)",
                "Rural / Sparse (250 people / km²)",
            ],
        )
        self.density_combo.current(0)
        self.density_combo.grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=4)

        # Range Check & Launch Control
        launch_frame = ttk.LabelFrame(left_col, text="4. Range Limit Check & Launch Control", padding=10)
        launch_frame.grid(row=3, column=0, sticky="ew", pady=(0, 8))

        self.range_status_var = tk.StringVar(value="Select Origin and Destination on the 3D Globe or via search.")
        self.range_label = ttk.Label(
            launch_frame, textvariable=self.range_status_var, font=("Segoe UI", 10, "bold"), wraplength=480
        )
        self.range_label.pack(anchor="w", pady=(0, 8))

        btn_row = ttk.Frame(launch_frame)
        btn_row.pack(fill="x")

        self.launch_btn = tk.Button(
            btn_row,
            text="🚀 SIMULATE LAUNCH & IMPACT",
            bg="#dc2626",
            fg="white",
            font=("Segoe UI", 11, "bold"),
            padx=14,
            pady=6,
            command=self.simulate_launch,
        )
        self.launch_btn.pack(side="left")

        ttk.Button(btn_row, text="Reset All", command=self._reset_all).pack(side="right")

        # Right Column - Output & Charts
        right_col = ttk.Frame(self, padding=(6, 4, 12, 4))
        right_col.grid(row=1, column=1, sticky="nsew")
        right_col.columnconfigure(0, weight=1)
        right_col.rowconfigure(0, weight=3)
        right_col.rowconfigure(1, weight=2)

        report_frame = ttk.LabelFrame(
            right_col,
            text="Post-Impact Assessment: Blast Radii, Estimated Casualties, Destruction & Missile Facts",
            padding=10,
        )
        report_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 8))

        self.report_text = tk.Text(
            report_frame, wrap="word", font=("Consolas", 10), bg="#0f172a", fg="#f8fafc", padx=10, pady=10
        )
        self.report_text.pack(fill="both", expand=True)

        chart_frame = ttk.LabelFrame(right_col, text="Blast Radii & Humanitarian Exposure Breakdown", padding=6)
        chart_frame.grid(row=1, column=0, sticky="nsew")

        self.figure = Figure(figsize=(5.5, 2.4), dpi=96)
        self.ax = self.figure.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.figure, master=chart_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        self._write_report(
            "READY FOR SIMULATION\n"
            "====================\n"
            "1. Click '🌐 Open Interactive 3D Globe' (top right) to view the 3D Earth.\n"
            "2. Click or drag the markers directly on the 3D Globe (or search by city name on the left).\n"
            "3. A cyan circle around your Origin City shows the selected missile's Maximum Range.\n"
            "4. If you pick a city outside that circle, the simulator will block the launch!\n"
            "5. Choose your missile & warhead yield, then click '🚀 SIMULATE LAUNCH & IMPACT'."
        )

    def open_globe(self) -> None:
        webbrowser.open(self.globe_url)

    def _handle_globe_pick_threadsafe(self, role: str, lon: float, lat: float) -> None:
        self.after(0, lambda: self._apply_globe_pick(role, lon, lat))

    def _apply_globe_pick(self, role: str, lon: float, lat: float) -> None:
        candidate = self.geocoding_service.reverse_geocode(lon, lat)

        if role == "destination" and self.origin_panel.selected_candidate:
            origin = self.origin_panel.selected_candidate
            dist_km = calculate_great_circle_distance_km(
                origin.longitude, origin.latitude, candidate.longitude, candidate.latitude
            )
            check = check_within_range(dist_km, self.selected_missile)
            if not check["in_range"]:
                self._apply_candidate_to_panel(self.destination_panel, candidate)
                self._recalculate_range_and_sync(launched=False)
                messagebox.showerror(
                    "Target Outside Missile Range",
                    f"{check['reason']}\n\n"
                    f"Please drag the target pin inside the cyan Range Circle on the globe, "
                    f"or switch to a longer-range missile (such as Agni-V or Minuteman III).",
                    parent=self,
                )
                return

        target_panel = self.origin_panel if role == "origin" else self.destination_panel
        self._apply_candidate_to_panel(target_panel, candidate)
        self._recalculate_range_and_sync(launched=False)

    @staticmethod
    def _apply_candidate_to_panel(panel: CitySearchPanel, candidate: PlaceCandidate) -> None:
        panel.candidates = [candidate]
        panel.selected_candidate = candidate
        panel.query_var.set(candidate.label)
        panel.candidate_combo["values"] = [
            f"{candidate.label}  [{candidate.longitude:.4f}, {candidate.latitude:.4f}]"
        ]
        panel.candidate_combo.current(0)
        panel.summary_var.set(f"Selected: {candidate.label}")
        panel.coords_var.set(
            f"Longitude: {candidate.longitude:.5f}°  |  Latitude: {candidate.latitude:.5f}°  ({candidate.attribution})"
        )

    def _on_missile_selected(self) -> None:
        idx = self.missile_combo.current()
        if 0 <= idx < len(self.missiles):
            self.selected_missile = self.missiles[idx]
            m = self.selected_missile
            self.missile_specs_var.set(
                f"Type: {m['type']}  |  Max Range: {m['max_range_km']:,} km  |  Speed: Mach {m['speed_mach']}"
            )
            self.yield_var.set(str(m["default_nuclear_yield_kt"]))
            if not m["nuclear_capable"]:
                self.nuclear_var.set(False)
                self.nuclear_check.configure(state="disabled")
            else:
                self.nuclear_check.configure(state="normal")
                self.nuclear_var.set(True)
            self._on_warhead_toggled()
            self._recalculate_range_and_sync(launched=False)

    def _on_warhead_toggled(self) -> None:
        state = "normal" if self.nuclear_var.get() else "disabled"
        self.yield_combo.configure(state=state)

    def _get_selected_density(self) -> float:
        mapping = [12000.0, 5000.0, 1500.0, 250.0]
        idx = self.density_combo.current()
        return mapping[idx] if 0 <= idx < len(mapping) else 5000.0

    def _recalculate_range_and_sync(self, launched: bool = False, impact: Optional[Dict[str, Any]] = None) -> None:
        origin = self.origin_panel.selected_candidate
        dest = self.destination_panel.selected_candidate
        m = self.selected_missile
        range_msg = f"Max Range Limit: {m['max_range_km']:,} km ({m['name']})"
        self.in_range = True

        if origin and dest:
            dist_km = calculate_great_circle_distance_km(
                origin.longitude, origin.latitude, dest.longitude, dest.latitude
            )
            check = check_within_range(dist_km, m)
            self.in_range = check["in_range"]
            range_msg = check["reason"]

            if self.in_range:
                self.range_label.configure(foreground="#15803d")
                self.launch_btn.configure(state="normal", bg="#dc2626")
            else:
                self.range_label.configure(foreground="#b91c1c")
                self.launch_btn.configure(state="disabled", bg="#9ca3af")
        else:
            self.range_label.configure(foreground="#334155")
            self.launch_btn.configure(state="normal", bg="#dc2626")

        self.range_status_var.set(range_msg)
        self.bridge.update_state(
            origin=vars(origin) if origin else None,
            destination=vars(dest) if dest else None,
            missile=m,
            in_range=self.in_range,
            range_message=range_msg,
            launched=launched,
            impact=impact,
        )

    def simulate_launch(self) -> None:
        origin = self.origin_panel.selected_candidate
        dest = self.destination_panel.selected_candidate
        if not origin or not dest:
            messagebox.showwarning(
                "Locations Required",
                "Please select both an Origin City and a Destination City (on the 3D Globe or via search).",
                parent=self,
            )
            return

        dist_km = calculate_great_circle_distance_km(
            origin.longitude, origin.latitude, dest.longitude, dest.latitude
        )
        check = check_within_range(dist_km, self.selected_missile)
        if not check["in_range"]:
            messagebox.showerror("Launch Prohibited — Out of Range", check["reason"], parent=self)
            return

        try:
            yield_kt = float(self.yield_var.get())
        except ValueError:
            yield_kt = float(self.selected_missile["default_nuclear_yield_kt"])

        density = self._get_selected_density()
        impact = compute_impact_effects(
            missile=self.selected_missile,
            distance_km=dist_km,
            is_nuclear=self.nuclear_var.get(),
            nuclear_yield_kt=yield_kt,
            pop_density_per_km2=density,
        )

        self._recalculate_range_and_sync(launched=True, impact=impact)
        self._display_impact_report(origin, dest, dist_km, impact)
        self._update_chart(impact)

    def _display_impact_report(
        self,
        origin: PlaceCandidate,
        dest: PlaceCandidate,
        dist_km: float,
        impact: Dict[str, Any],
    ) -> None:
        m = self.selected_missile
        r = impact["radii_km"]
        est = impact["estimates"]

        facts_str = "\n".join(f"  • {fact}" for fact in m.get("facts", []))

        report = (
            f"=== POST-IMPACT SIMULATION REPORT ===\n"
            f"Missile System       : {m['name']} ({m['type']})\n"
            f"Warhead Configured   : {impact['warhead_mode']}\n"
            f"Origin Location      : {origin.label} [{origin.longitude:.3f}°, {origin.latitude:.3f}°]\n"
            f"Target Location      : {dest.label} [{dest.longitude:.3f}°, {dest.latitude:.3f}°]\n"
            f"Distance vs Max Range: {dist_km:,.2f} km / {m['max_range_km']:,} km\n"
            f"Est. Flight Time     : ~{impact['flight_time_min']} minutes (at Mach {m['speed_mach']})\n\n"
            f"--- CONCENTRIC BLAST & THERMAL RADII ---\n"
            f"  • Fireball Radius (Vaporization)          : {r['fireball_km']:,.3f} km ({r['fireball_km']*1000:,.0f} m)\n"
            f"  • Heavy Blast Radius (20 psi Destruction) : {r['heavy_blast_20psi_km']:,.3f} km\n"
            f"  • Moderate Blast Radius (5 psi Collapse)  : {r['moderate_blast_5psi_km']:,.3f} km\n"
            f"  • Thermal Radiation (3rd-Degree Burns)    : {r['thermal_3rd_deg_km']:,.3f} km\n"
            f"  • Light Blast Radius (1 psi Glass Break)  : {r['light_blast_1psi_km']:,.3f} km\n\n"
            f"--- ESTIMATED CASUALTIES & STRUCTURAL DESTRUCTION ---\n"
            f"  • Estimated Fatalities                    : {est['estimated_fatalities']:,} people\n"
            f"  • Estimated Injuries                      : {est['estimated_injuries']:,} people\n"
            f"  • Total Population Inside Hazard Rings    : {est['total_exposed']:,} people\n"
            f"  • Estimated Buildings/Structures Destroyed: {est['structures_destroyed']:,} structures\n"
            f"    (Modeled at {est['pop_density_used']:,.0f} people/km² using Glasstone-Dolan scaling laws)\n\n"
            f"--- MISSILE SYSTEM FACTS & REFERENCE ---\n"
            f"{facts_str}\n"
            f"  • Public Reference Source: {m['source_url']}\n"
        )
        self._write_report(report)

    def _update_chart(self, impact: Dict[str, Any]) -> None:
        self.ax.clear()
        est = impact["estimates"]
        categories = ["Fatalities", "Injuries", "Structures\nDestroyed"]
        values = [
            est["estimated_fatalities"],
            est["estimated_injuries"],
            est["structures_destroyed"],
        ]
        colors = ["#dc2626", "#f59e0b", "#475569"]
        bars = self.ax.barh(categories, values, color=colors)
        self.ax.set_title("Estimated Humanitarian & Structural Impact", fontsize=10, fontweight="bold")
        self.ax.grid(axis="x", linestyle="--", alpha=0.4)
        for bar in bars:
            w = bar.get_width()
            self.ax.text(w, bar.get_y() + bar.get_height() / 2, f" {int(w):,}", va="center", fontsize=9)
        self.figure.tight_layout()
        self.canvas.draw()

    def _save_scenario_dialog(self) -> None:
        origin = self.origin_panel.selected_candidate
        dest = self.destination_panel.selected_candidate
        if not origin or not dest:
            messagebox.showwarning("Cannot Save", "Select both Origin and Destination first.", parent=self)
            return

        name = simpledialog.askstring("Save Scenario", "Enter a name for this scenario:", parent=self)
        if not name:
            return

        scenario = Scenario(
            scenario_name=name.strip(),
            origin_city_label=origin.label,
            origin_longitude=origin.longitude,
            origin_latitude=origin.latitude,
            destination_city_label=dest.label,
            destination_longitude=dest.longitude,
            destination_latitude=dest.latitude,
            selected_reference_record_id=self.selected_missile["id"],
            hypothetical_assessment_zone_parameters=json.dumps(
                {
                    "is_nuclear": self.nuclear_var.get(),
                    "yield_kt": self.yield_var.get(),
                    "density": self._get_selected_density(),
                }
            ),
        )
        self.db.save_scenario(scenario)
        messagebox.showinfo("Saved", f"Scenario '{name}' saved to SQLite database.", parent=self)

    def _load_scenario_dialog(self) -> None:
        scenarios = self.db.list_scenarios()
        if not scenarios:
            messagebox.showinfo("No Saved Scenarios", "No saved scenarios found in SQLite yet.", parent=self)
            return

        latest = scenarios[0]
        origin = PlaceCandidate(
            label=latest.origin_city_label,
            longitude=latest.origin_longitude,
            latitude=latest.origin_latitude,
            provider_place_id="loaded-origin",
        )
        dest = PlaceCandidate(
            label=latest.destination_city_label,
            longitude=latest.destination_longitude,
            latitude=latest.destination_latitude,
            provider_place_id="loaded-dest",
        )
        self._apply_candidate_to_panel(self.origin_panel, origin)
        self._apply_candidate_to_panel(self.destination_panel, dest)

        for i, m in enumerate(self.missiles):
            if m["id"] == latest.selected_reference_record_id:
                self.missile_combo.current(i)
                self._on_missile_selected()
                break

        if latest.hypothetical_assessment_zone_parameters:
            try:
                params = json.loads(latest.hypothetical_assessment_zone_parameters)
                if "is_nuclear" in params:
                    self.nuclear_var.set(params["is_nuclear"])
                if "yield_kt" in params:
                    self.yield_var.set(str(params["yield_kt"]))
                self._on_warhead_toggled()
            except Exception:
                pass

        self._recalculate_range_and_sync(launched=False)
        messagebox.showinfo("Scenario Loaded", f"Loaded most recent scenario: '{latest.scenario_name}'", parent=self)

    def _reset_all(self) -> None:
        self.origin_panel.clear_selection()
        self.destination_panel.clear_selection()
        self.ax.clear()
        self.canvas.draw()
        self._recalculate_range_and_sync(launched=False)
        self._write_report("Reset complete. Click on the 3D Globe or search a city to begin.")

    def _write_report(self, text: str) -> None:
        self.report_text.configure(state="normal")
        self.report_text.delete("1.0", tk.END)
        self.report_text.insert(tk.END, text)
        self.report_text.configure(state="disabled")
