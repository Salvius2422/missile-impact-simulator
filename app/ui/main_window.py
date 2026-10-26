import os
import sys
import json
import time
import ctypes
import threading
from ctypes import wintypes
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from typing import Optional, Dict, Any, List
from pathlib import Path

import webview

from app.data.models import PlaceCandidate, Scenario
from app.data.database import ScenarioDatabase
from app.services.mapbox_geocoding import MapboxGeocodingService
from app.services.distance_service import calculate_great_circle_distance_km
from app.services.impact_physics import load_missiles, check_within_range, compute_impact_effects
from app.services.bridge_server import GlobeBridgeServer
from app.services.webview_api import SimulatorApi
from app.ui.city_search import CitySearchPanel


class MissileCatalogDialog(tk.Toplevel):
    """Interactive Tkinter dialog displaying the searchable 58-missile technical catalog."""

    def __init__(self, parent: tk.Widget, missiles: List[Dict[str, Any]], on_select=None):
        super().__init__(parent)
        self.title("58-Missile Technical Catalog & Warhead Specifications")
        self.geometry("980x520")
        self.minsize(780, 400)
        self.missiles = missiles
        self.on_select = on_select
        self.configure(bg="#0f172a")

        self._build_ui()

    def _build_ui(self):
        # Header & Filter
        top_frame = tk.Frame(self, bg="#1e293b", padx=12, pady=10)
        top_frame.pack(fill="x", side="top")

        tk.Label(
            top_frame,
            text="Missile Inventory (58 Systems Across 10 Major Powers)",
            font=("Segoe UI", 12, "bold"),
            fg="#38bdf8",
            bg="#1e293b",
        ).pack(side="left")

        # Search Bar
        search_frame = tk.Frame(top_frame, bg="#1e293b")
        search_frame.pack(side="right")
        tk.Label(search_frame, text="Filter:", fg="#cbd5e1", bg="#1e293b", font=("Segoe UI", 9)).pack(side="left", padx=4)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._filter_tree())
        entry = ttk.Entry(search_frame, textvariable=self.search_var, width=24)
        entry.pack(side="left", padx=4)

        # Treeview
        tree_frame = tk.Frame(self, bg="#0f172a")
        tree_frame.pack(fill="both", expand=True, padx=12, pady=10)

        cols = ("country", "name", "type", "range", "speed", "warhead", "yield")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")

        self.tree.heading("country", text="Country")
        self.tree.heading("name", text="System Name")
        self.tree.heading("type", text="Classification")
        self.tree.heading("range", text="Max Range (km)")
        self.tree.heading("speed", text="Cruising Speed")
        self.tree.heading("warhead", text="Warhead Type")
        self.tree.heading("yield", text="Default Yield (kt)")

        self.tree.column("country", width=120)
        self.tree.column("name", width=180)
        self.tree.column("type", width=140)
        self.tree.column("range", width=120, anchor="e")
        self.tree.column("speed", width=110, anchor="center")
        self.tree.column("warhead", width=130, anchor="center")
        self.tree.column("yield", width=120, anchor="e")

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.tree.bind("<Double-1>", self._on_item_double_click)

        # Status Bar / Actions
        bot_frame = tk.Frame(self, bg="#1e293b", padx=12, pady=8)
        bot_frame.pack(fill="x", side="bottom")

        self.count_lbl = tk.Label(bot_frame, text=f"Total: {len(self.missiles)} systems", fg="#94a3b8", bg="#1e293b", font=("Segoe UI", 9))
        self.count_lbl.pack(side="left")

        ttk.Button(bot_frame, text="Close", command=self.destroy).pack(side="right")
        self._filter_tree()

    def _filter_tree(self):
        q = self.search_var.get().lower().strip()
        self.tree.delete(*self.tree.get_children())
        count = 0
        for m in self.missiles:
            c_name = m.get("country", "")
            name = m.get("name", "")
            mtype = m.get("type", "")
            if not q or (q in c_name.lower() or q in name.lower() or q in mtype.lower()):
                warhead_str = "☢ Nuclear" if m.get("nuclear_capable") else "💥 Conventional"
                yield_str = f"{m.get('default_nuclear_yield_kt', 0)} kt" if m.get("nuclear_capable") else "N/A"
                self.tree.insert(
                    "",
                    "end",
                    iid=m["id"],
                    values=(
                        c_name,
                        name,
                        mtype,
                        f"{m.get('max_range_km', 0):,} km",
                        f"Mach {m.get('speed_mach', 1.0)}",
                        warhead_str,
                        yield_str,
                    ),
                )
                count += 1
        self.count_lbl.config(text=f"Showing: {count} of {len(self.missiles)} missile systems")

    def _on_item_double_click(self, event):
        sel = self.tree.selection()
        if sel and self.on_select:
            missile_id = sel[0]
            m = next((item for item in self.missiles if item["id"] == missile_id), None)
            if m:
                self.on_select(m)
                self.destroy()


class ScenarioManagerDialog(tk.Toplevel):
    """Interactive Tkinter dialog to browse, load, and delete scenarios from scenarios.db."""

    def __init__(self, parent: tk.Widget, db: ScenarioDatabase, on_load=None):
        super().__init__(parent)
        self.title("Saved Scenarios Manager (SQLite scenarios.db)")
        self.geometry("860x440")
        self.db = db
        self.on_load = on_load
        self.configure(bg="#0f172a")

        self._build_ui()

    def _build_ui(self):
        top_frame = tk.Frame(self, bg="#1e293b", padx=12, pady=10)
        top_frame.pack(fill="x", side="top")
        tk.Label(
            top_frame,
            text="Saved Scenarios (Local SQLite Database)",
            font=("Segoe UI", 12, "bold"),
            fg="#38bdf8",
            bg="#1e293b",
        ).pack(side="left")

        tree_frame = tk.Frame(self, bg="#0f172a")
        tree_frame.pack(fill="both", expand=True, padx=12, pady=10)

        cols = ("id", "name", "origin", "target", "missile", "date")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")

        self.tree.heading("id", text="ID")
        self.tree.heading("name", text="Scenario Name")
        self.tree.heading("origin", text="Origin City")
        self.tree.heading("target", text="Target City")
        self.tree.heading("missile", text="Missile ID")
        self.tree.heading("date", text="Created At")

        self.tree.column("id", width=50, anchor="center")
        self.tree.column("name", width=180)
        self.tree.column("origin", width=160)
        self.tree.column("target", width=160)
        self.tree.column("missile", width=110, anchor="center")
        self.tree.column("date", width=140, anchor="center")

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        bot_frame = tk.Frame(self, bg="#1e293b", padx=12, pady=8)
        bot_frame.pack(fill="x", side="bottom")

        ttk.Button(bot_frame, text="Load Selected", command=self._load_selected).pack(side="left", padx=4)
        ttk.Button(bot_frame, text="Delete Selected", command=self._delete_selected).pack(side="left", padx=4)
        ttk.Button(bot_frame, text="Refresh", command=self._populate).pack(side="left", padx=4)
        ttk.Button(bot_frame, text="Close", command=self.destroy).pack(side="right")

        self._populate()

    def _populate(self):
        self.tree.delete(*self.tree.get_children())
        scenarios = self.db.list_scenarios()
        for s in scenarios:
            self.tree.insert(
                "",
                "end",
                iid=str(s.scenario_id),
                values=(
                    s.scenario_id,
                    s.scenario_name,
                    s.origin_city_label,
                    s.destination_city_label,
                    s.selected_reference_record_id,
                    str(s.created_at)[:19] if s.created_at else "N/A",
                ),
            )

    def _load_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Selection Required", "Please select a scenario to load.", parent=self)
            return
        scen_id = int(sel[0])
        scenarios = self.db.list_scenarios()
        chosen = next((s for s in scenarios if s.scenario_id == scen_id), None)
        if chosen and self.on_load:
            self.on_load(chosen)
            self.destroy()

    def _delete_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        scen_id = int(sel[0])
        if messagebox.askyesno("Confirm Delete", f"Delete scenario ID #{scen_id}?", parent=self):
            try:
                self.db.delete_scenario(scen_id)
                self._populate()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to delete: {e}", parent=self)


class PhysicsInfoDialog(tk.Toplevel):
    """Tkinter dialog detailing the Glasstone-Dolan blast physics scaling laws."""

    def __init__(self, parent: tk.Widget):
        super().__init__(parent)
        self.title("Glasstone-Dolan Impact Physics & Atmospheric Scaling Laws")
        self.geometry("740x500")
        self.configure(bg="#0f172a")

        header = tk.Frame(self, bg="#1e293b", padx=14, pady=10)
        header.pack(fill="x", side="top")
        tk.Label(
            header,
            text="Scientific Blast Physics & Humanitarian Casualty Equations",
            font=("Segoe UI", 12, "bold"),
            fg="#38bdf8",
            bg="#1e293b",
        ).pack(side="left")

        text_box = tk.Text(self, wrap="word", font=("Consolas", 10), bg="#090e17", fg="#f8fafc", padx=14, pady=12)
        text_box.pack(fill="both", expand=True, padx=12, pady=10)

        docs = (
            "GLASSTONE-DOLAN (1977) BLAST OVERPRESSURE EQUATIONS\n"
            "===================================================\n\n"
            "1. CUBE-ROOT SCALING LAW:\n"
            "   Concentric blast wave radii scale with the cube root of the explosive yield Y (in kilotons TNT):\n"
            "     r(Y) = r_ref * Y^(1/3)\n\n"
            "2. DAMAGE ZONES & PRESSURE THRESHOLDS:\n"
            "   • Fireball Vaporization Zone (~100% immediate fatality):\n"
            "     r_fireball = 0.048 * Y^(0.4) km\n"
            "     At this boundary, core fireball temperature reaches ~100,000,000 K.\n\n"
            "   • Heavy Blast Damage Zone (20 psi / 138 kPa Overpressure):\n"
            "     r_20psi = 0.28 * Y^(1/3) km\n"
            "     Complete structural destruction of reinforced concrete buildings; near-100% fatalities.\n\n"
            "   • Moderate Blast Damage Zone (5 psi / 34.5 kPa Overpressure):\n"
            "     r_5psi = 0.65 * Y^(1/3) km\n"
            "     Collapse of residential buildings, severe structural fires, catastrophic injuries.\n\n"
            "   • Thermal Radiation Zone (3rd-Degree Burns & Flash Fires):\n"
            "     r_thermal = 1.15 * Y^(0.41) km\n"
            "     Thermal pulse causing full-thickness third-degree burns and spontaneous ignition.\n\n"
            "   • Light Blast Damage Zone (1 psi / 6.9 kPa Overpressure):\n"
            "     r_1psi = 1.60 * Y^(1/3) km\n"
            "     Widespread window shatter, projectile glass lacerations, minor structural fractures.\n\n"
            "3. HUMANITARIAN CASUALTY EXPOSURE INTEGRAL:\n"
            "   • Urban Population Data: Automatically retrieved via OpenDataSoft / GeoNames / OSM APIs.\n"
            "   • Fatality Integral: Integrated over concentric annular damage rings weighted by lethality\n"
            "     fractions: 100% (fireball), 90% (20 psi), 50% (5 psi), and 15% (thermal zone).\n"
        )
        text_box.insert("1.0", docs)
        text_box.configure(state="disabled")

        bot = tk.Frame(self, bg="#1e293b", padx=12, pady=8)
        bot.pack(fill="x", side="bottom")
        ttk.Button(bot, text="Close", command=self.destroy).pack(side="right")


class MissileSimulatorApp(tk.Tk):
    """
    Primary Tkinter Desktop Application.
    Hosts the native Tkinter command center, menus, status bars, and embeds
    the interactive PyView 3D CesiumJS Earth globe inside a Tkinter viewport frame.
    """

    def __init__(self, globe_url: str, api: SimulatorApi, on_exit=None):
        super().__init__()
        self.globe_url = globe_url
        self.api = api
        self.on_exit = on_exit

        self.title("Real-World Missile Impact Simulator — [Tkinter Core Desktop GUI & PyView 3D Viewport]")
        self.geometry("1380x880")
        self.minsize(1080, 720)
        self.configure(bg="#0f172a")

        self.child_hwnd: Optional[int] = None
        self.current_width: int = 1380
        self.current_height: int = 800

        self.db = ScenarioDatabase()
        self.missiles = load_missiles()

        self._build_menu()
        self._build_toolbar()
        self._build_viewport()
        self._build_statusbar()

        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _build_menu(self):
        menubar = tk.Menu(self)

        # File Menu
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="💾 Save Scenario to SQLite...", command=self.open_save_dialog, accelerator="Ctrl+S")
        file_menu.add_command(label="📂 Load Scenario from SQLite...", command=self.open_scenarios_dialog, accelerator="Ctrl+O")
        file_menu.add_separator()
        file_menu.add_command(label="🔄 Reset All Pins & Camera", command=self.reset_all)
        file_menu.add_separator()
        file_menu.add_command(label="🚪 Exit Simulator", command=self.on_closing, accelerator="Ctrl+Q")
        menubar.add_cascade(label="File", menu=file_menu)

        # Missiles Menu
        missile_menu = tk.Menu(menubar, tearoff=0)
        missile_menu.add_command(label="📋 58-Missile Technical Catalog...", command=self.open_missile_catalog)
        missile_menu.add_separator()
        missile_menu.add_command(label="🇮🇳 Indian Missile Systems (Agni, BrahMos, Prithvi)", command=lambda: self.open_missile_catalog_filter("India"))
        missile_menu.add_command(label="🇺🇸 United States Systems (Minuteman, Trident, Tomahawk)", command=lambda: self.open_missile_catalog_filter("United States"))
        missile_menu.add_command(label="🇷🇺 Russian Systems (Sarmat, Yars, Iskander, Kalibr)", command=lambda: self.open_missile_catalog_filter("Russia"))
        missile_menu.add_command(label="🇨🇳 Chinese Systems (DF-41, DF-26, DF-17)", command=lambda: self.open_missile_catalog_filter("China"))
        menubar.add_cascade(label="Missiles", menu=missile_menu)

        # Scenarios Menu
        scen_menu = tk.Menu(menubar, tearoff=0)
        scen_menu.add_command(label="📂 SQLite Scenarios Manager...", command=self.open_scenarios_dialog)
        menubar.add_cascade(label="Scenarios", menu=scen_menu)

        # Physics & Math Menu
        phys_menu = tk.Menu(menubar, tearoff=0)
        phys_menu.add_command(label="📐 Glasstone-Dolan Blast Radii Formulas...", command=self.open_physics_info)
        menubar.add_cascade(label="Physics & Math", menu=phys_menu)

        # Help Menu
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="ℹ️ About Simulator & Tkinter Architecture...", command=self.open_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=menubar)

        # Keyboard Shortcuts
        self.bind("<Control-s>", lambda _: self.open_save_dialog())
        self.bind("<Control-o>", lambda _: self.open_scenarios_dialog())
        self.bind("<Control-q>", lambda _: self.on_closing())

    def _build_toolbar(self):
        toolbar = tk.Frame(self, bg="#0f172a", height=42, padx=14, pady=6)
        toolbar.pack(fill="x", side="top")

        # Title & Badges
        title_box = tk.Frame(toolbar, bg="#0f172a")
        title_box.pack(side="left")

        tk.Label(
            title_box,
            text="🎯 REAL-WORLD MISSILE IMPACT SIMULATOR",
            font=("Segoe UI", 11, "bold"),
            fg="#38bdf8",
            bg="#0f172a",
        ).pack(side="left")

        tk.Label(
            title_box,
            text="[Tkinter Core GUI & PyView 3D Viewport]",
            font=("Segoe UI", 9, "bold"),
            fg="#94a3b8",
            bg="#0f172a",
        ).pack(side="left", padx=8)

        # Action Buttons
        btn_box = tk.Frame(toolbar, bg="#0f172a")
        btn_box.pack(side="right")

        tk.Button(
            btn_box,
            text="📋 58 Missile Catalog",
            command=self.open_missile_catalog,
            bg="#1e293b",
            fg="#e2e8f0",
            activebackground="#334155",
            activeforeground="#fff",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=8,
            pady=3,
        ).pack(side="left", padx=3)

        tk.Button(
            btn_box,
            text="📂 Saved Scenarios",
            command=self.open_scenarios_dialog,
            bg="#1e293b",
            fg="#e2e8f0",
            activebackground="#334155",
            activeforeground="#fff",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=8,
            pady=3,
        ).pack(side="left", padx=3)

        tk.Button(
            btn_box,
            text="💾 Save Scenario",
            command=self.open_save_dialog,
            bg="#1e293b",
            fg="#e2e8f0",
            activebackground="#334155",
            activeforeground="#fff",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=8,
            pady=3,
        ).pack(side="left", padx=3)

        tk.Button(
            btn_box,
            text="📐 Blast Physics",
            command=self.open_physics_info,
            bg="#1e293b",
            fg="#e2e8f0",
            activebackground="#334155",
            activeforeground="#fff",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=8,
            pady=3,
        ).pack(side="left", padx=3)

    def _build_viewport(self):
        """Tkinter container frame that embeds the native PyView 3D Earth view."""
        self.viewport_frame = tk.Frame(self, bg="#000000")
        self.viewport_frame.pack(fill="both", expand=True)
        self.viewport_frame.bind("<Configure>", self.on_viewport_resize)

        self.update()
        self.tk_hwnd = self.viewport_frame.winfo_id()

    def _build_statusbar(self):
        statusbar = tk.Frame(self, bg="#090e17", height=24, padx=12, pady=4)
        statusbar.pack(fill="x", side="bottom")

        tk.Label(
            statusbar,
            text="🟢 Tkinter Core Engine: ACTIVE",
            font=("Segoe UI", 8, "bold"),
            fg="#4ade80",
            bg="#090e17",
        ).pack(side="left")

        tk.Label(
            statusbar,
            text="•  PyView 3D Viewport: EMBEDDED",
            font=("Segoe UI", 8),
            fg="#38bdf8",
            bg="#090e17",
        ).pack(side="left", padx=8)

        tk.Label(
            statusbar,
            text="•  Wi-Fi Geocoding: OpenStreetMap & GeoNames",
            font=("Segoe UI", 8),
            fg="#cbd5e1",
            bg="#090e17",
        ).pack(side="left", padx=8)

        tk.Label(
            statusbar,
            text="Database: 58 Missiles  |  SQLite: scenarios.db",
            font=("Segoe UI", 8),
            fg="#94a3b8",
            bg="#090e17",
        ).pack(side="right")

    def on_viewport_resize(self, event):
        self.current_width = event.width
        self.current_height = event.height
        if self.child_hwnd and sys.platform == "win32":
            ctypes.windll.user32.MoveWindow(
                wintypes.HWND(self.child_hwnd), 0, 0, event.width, event.height, True
            )

    def open_missile_catalog(self):
        MissileCatalogDialog(self, self.missiles)

    def open_missile_catalog_filter(self, country: str):
        dialog = MissileCatalogDialog(self, self.missiles)
        dialog.search_var.set(country)

    def open_scenarios_dialog(self):
        ScenarioManagerDialog(self, self.db)

    def open_save_dialog(self):
        name = simpledialog.askstring("Save Scenario", "Enter scenario title to save into SQLite:", parent=self)
        if name and name.strip():
            scen = Scenario(
                scenario_name=name.strip(),
                origin_city_label="New Delhi, India",
                origin_longitude=77.2090,
                origin_latitude=28.6139,
                destination_city_label="Target Location",
                destination_longitude=116.4074,
                destination_latitude=39.9042,
                selected_reference_record_id="agni_v",
                hypothetical_assessment_zone_parameters=json.dumps({"is_nuclear": True, "yield_kt": 250}),
            )
            try:
                sid = self.db.save_scenario(scen)
                messagebox.showinfo("Saved", f"Scenario '{name.strip()}' saved to scenarios.db (ID #{sid})!", parent=self)
            except Exception as e:
                messagebox.showerror("Error", f"Could not save scenario: {e}", parent=self)

    def open_physics_info(self):
        PhysicsInfoDialog(self)

    def open_about(self):
        messagebox.showinfo(
            "About Real-World Missile Impact Simulator",
            "Real-World Missile Impact Simulator\n"
            "===================================\n"
            "Primary Framework: Python Tkinter (Mandatory Core GUI)\n"
            "Geospatial Viewport: PyView (pywebview) 3D CesiumJS Earth\n"
            "Physics Engine: Glasstone-Dolan Cube-Root Blast Radii Equations\n"
            "Inventory: 58 Intercontinental, Intermediate & Tactical Missiles\n"
            "Public Databases: OpenStreetMap Nominatim, GeoNames, OpenDataSoft\n"
            "Local Persistence: SQLite scenarios.db\n\n"
            "Developed according to mandatory project specifications.",
            parent=self,
        )

    def reset_all(self):
        messagebox.showinfo("Reset", "Simulator viewport reset command triggered.", parent=self)

    def on_closing(self):
        try:
            self.destroy()
        except Exception:
            pass
        if self.on_exit:
            self.on_exit()
        os._exit(0)


def launch_simulator_app():
    """
    Mandatory Application Launcher.
    Initializes Tkinter as the master desktop GUI application and embeds
    the high-performance PyView 3D CesiumJS Earth view directly within it.
    """
    bridge = GlobeBridgeServer(port=8765)
    globe_url = bridge.start()
    api = bridge.api

    ready_event = threading.Event()
    app_ref: Dict[str, Any] = {"app": None}

    def run_tkinter():
        app = MissileSimulatorApp(globe_url, api)
        app_ref["app"] = app
        ready_event.set()
        app.mainloop()

    # Launch Tkinter on dedicated thread
    t = threading.Thread(target=run_tkinter, daemon=True)
    t.start()
    ready_event.wait()
    app = app_ref["app"]

    # Embed PyView 3D Earth within Tkinter
    win = webview.create_window(
        title="Missile Simulator 3D Geospatial Engine",
        url=globe_url,
        js_api=api,
        width=app.current_width,
        height=app.current_height,
        text_select=False,
    )

    def on_shown():
        time.sleep(0.3)
        if sys.platform == "win32" and app and app.tk_hwnd:
            try:
                child = win.native.Handle.ToInt64()
                u32 = ctypes.windll.user32
                u32.SetParent(wintypes.HWND(child), wintypes.HWND(app.tk_hwnd))
                GWL_STYLE = -16
                WS_CHILD = 0x40000000
                WS_POPUP = 0x80000000
                WS_CAPTION = 0x00C00000
                WS_THICKFRAME = 0x00040000
                style = u32.GetWindowLongW(child, GWL_STYLE)
                style &= ~(WS_POPUP | WS_CAPTION | WS_THICKFRAME)
                style |= WS_CHILD
                u32.SetWindowLongW(child, GWL_STYLE, style)
                u32.MoveWindow(wintypes.HWND(child), 0, 0, app.current_width, app.current_height, True)
                app.child_hwnd = child
            except Exception as err:
                print(f"Notice: Native embedding into Tkinter container: {err}")

    win.events.shown += on_shown
    webview.start(debug=False)
