import os
import re
import sys
import json
import ctypes
import threading
from ctypes import wintypes
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from typing import Optional, Dict, Any, List

import webview

from app.data.database import PlaceCandidate, Scenario
from app.data.database import ScenarioDatabase
from app.services.geocoding import GeocodingService
from app.services.impact_physics import calculate_great_circle_distance_km
from app.services.impact_physics import (
    load_missiles,
    check_within_range,
    get_speed_stats,
    compute_impact_effects,
    FIREBALL_COEFF,
    FIREBALL_EXP,
    HEAVY_BLAST_20PSI_COEFF,
    MODERATE_BLAST_5PSI_COEFF,
    THERMAL_NUCLEAR_COEFF,
    THERMAL_NUCLEAR_EXP,
    THERMAL_CONV_COEFF,
    LIGHT_BLAST_1PSI_COEFF,
    FATALITY_RATE_HEAVY,
    FATALITY_RATE_MODERATE,
    FATALITY_RATE_LIGHT,
    INJURY_RATE_HEAVY,
    INJURY_RATE_MODERATE,
    INJURY_RATE_LIGHT,
    STRUCTURES_PER_PERSON,
    STRUCT_DESTROY_HEAVY,
    STRUCT_DESTROY_MODERATE,
    MACH_TO_KMH,
    BALLISTIC_AVG_RATIO,
    CRUISE_AVG_RATIO,
)
from app.services.bridge_server import GlobeBridgeServer
from app.services.bridge_server import SimulatorApi
from app.ui.city_search import CitySearchPanel

# simple black palette: neutral greys only, color reserved for meaning (red/green/amber)
COLOR_MAIN_BG = "#000000"
COLOR_PANEL_BG = "#0a0a0a"
COLOR_INPUT_BG = "#141414"
COLOR_BORDER = "#262626"
COLOR_HOVER = "#333333"
COLOR_TEXT = "#ededed"
COLOR_MUTED = "#8a8a8a"
COLOR_DISABLED_FG = "#555555"
COLOR_ACCENT = "#ededed"
COLOR_GREEN = "#22c55e"
COLOR_RED = "#dc2626"
COLOR_AMBER = "#f59e0b"

FONT_MAIN_TITLE = ("Segoe UI", 11, "bold")
FONT_CARD_TITLE = ("Segoe UI", 10, "bold")
FONT_BOLD = ("Segoe UI", 9, "bold")
FONT_NORMAL = ("Segoe UI", 9)
FONT_SMALL = ("Segoe UI", 8)
FONT_MONO = ("Consolas", 9)
FONT_BUTTON = ("Segoe UI Semibold", 9)
FONT_BUTTON_LARGE = ("Segoe UI Semibold", 10)

# button roles: rest / hover / pressed colours. one role per kind of action, so the
# red launch button is the only loud thing in the panel.
BUTTON_STYLES = {
    # the one main action
    "primary": {"bg": "#dc2626", "hover": "#ef4444", "press": "#b91c1c", "fg": "#ffffff"},
    # everyday actions
    "secondary": {"bg": "#262626", "hover": "#333333", "press": "#404040", "fg": COLOR_TEXT},
    # toolbar: text until hovered
    "ghost": {"bg": "#000000", "hover": "#1a1a1a", "press": "#262626", "fg": COLOR_TEXT},
    # active map-click mode (darker shades so white text stays readable)
    "selected-origin": {"bg": "#15803d", "hover": "#16a34a", "press": "#166534", "fg": "#ffffff"},
    "selected-target": {"bg": "#b91c1c", "hover": "#dc2626", "press": "#991b1b", "fg": "#ffffff"},
}
BUTTON_DISABLED = {"bg": "#141414", "fg": "#555555"}

# display scale (1.0 at 100%, 1.5 at 150%). set by enable_dpi_awareness() before tk starts.
UI_SCALE = 1.0


def px(n: float) -> int:
    """scale a layout size in logical pixels to physical pixels"""
    return int(round(n * UI_SCALE))


def enable_dpi_awareness() -> None:
    """make tkinter dpi-aware so it uses the same physical pixels as the embedded webview.

    pywebview switches the process to dpi-aware inside webview.start(). if tkinter was
    created before that while dpi-unaware, its sizes are in scaled pixels and the globe
    gets positioned/sized wrong on displays above 100% scaling.
    """
    global UI_SCALE
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # system dpi aware
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            return
    try:
        UI_SCALE = ctypes.windll.user32.GetDpiForSystem() / 96.0
    except (AttributeError, OSError):
        UI_SCALE = 1.0


# ---- missile search ----
ROMAN_NUMERALS = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6", "vii": "7", "viii": "8", "ix": "9", "x": "10"}
COUNTRY_ALIASES = {
    "United States": "usa us america",
    "United Kingdom": "uk britain england",
    "Russia": "russian federation",
    "North Korea": "dprk",
    "South Korea": "rok",
}


def _squash(text: str) -> str:
    """lowercase letters and digits only, so 'Agni-V', 'agni v' and 'agniv' compare equal"""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _arabic_numerals(text: str) -> str:
    """'Agni-V' -> 'Agni-5', 'Minuteman III' -> 'Minuteman 3'"""
    return re.sub(r"\b([ivx]+)\b", lambda m: ROMAN_NUMERALS.get(m.group(1), m.group(1)), text.lower())


def missile_search_text(m: Dict[str, Any]) -> str:
    """everything a missile can be found by, each squashed: name (also with arabic numerals), id, type, country"""
    country = m.get("country", "")
    parts = [m.get("name", ""), _arabic_numerals(m.get("name", "")), m.get("id", ""), m.get("type", ""), country]
    parts += COUNTRY_ALIASES.get(country, "").split()
    return " ".join(_squash(p) for p in parts)


def missile_matches(m: Dict[str, Any], query: str) -> bool:
    """'agni 5', 'agni-v', 'df41', 'india', 'usa icbm' all work.

    the whole query is compared first with spaces and hyphens ignored; failing that, every
    word of 2+ characters must appear somewhere (so 'india icbm' finds Agni-V).
    """
    haystack = missile_search_text(m)
    whole, whole_arabic = _squash(query), _squash(_arabic_numerals(query))
    if not whole or whole in haystack or whole_arabic in haystack:
        return True
    words = [w for w in query.split() if len(_squash(w)) >= 2]
    return len(words) > 1 and all(
        _squash(w) in haystack or _squash(_arabic_numerals(w)) in haystack for w in words
    )


class FlatButton(tk.Button):
    """flat button with hover, pressed and disabled states for the black theme.

    tk.Button has no hover state of its own, so <Enter>/<Leave> swap the colour.
    setting state="disabled" through config() repaints it, so callers need nothing special.
    """

    def __init__(self, master: tk.Widget, kind: str = "secondary", large: bool = False, **kw: Any):
        kw.setdefault("font", FONT_BUTTON_LARGE if large else FONT_BUTTON)
        kw.setdefault("padx", px(14))
        kw.setdefault("pady", px(6) if large else px(4))
        super().__init__(master, relief="flat", bd=0, highlightthickness=0, **kw)
        self._kind = kind
        self._hovered = False
        self.bind("<Enter>", lambda _e: self._set_hover(True), add="+")
        self.bind("<Leave>", lambda _e: self._set_hover(False), add="+")
        self._paint()

    def set_kind(self, kind: str) -> None:
        self._kind = kind
        self._paint()

    def configure(self, cnf=None, **kw: Any):
        result = super().configure(cnf, **kw)
        if "state" in kw or (isinstance(cnf, dict) and "state" in cnf):
            self._paint()
        return result

    config = configure

    def _set_hover(self, hovered: bool) -> None:
        self._hovered = hovered
        self._paint()

    def _paint(self) -> None:
        style = BUTTON_STYLES[self._kind]
        if str(self.cget("state")) == "disabled":
            super().configure(
                bg=BUTTON_DISABLED["bg"], fg=BUTTON_DISABLED["fg"],
                disabledforeground=BUTTON_DISABLED["fg"], cursor="arrow",
            )
        else:
            super().configure(
                bg=style["hover"] if self._hovered else style["bg"], fg=style["fg"],
                activebackground=style["press"], activeforeground=style["fg"], cursor="hand2",
            )


class MissileCatalogDialog(tk.Toplevel):
    """searchable catalog dialog displaying all 58 missile systems"""

    def __init__(self, parent: tk.Widget, missiles: List[Dict[str, Any]], on_select=None):
        super().__init__(parent)
        self.title("Missile Technical Catalog")
        self.geometry(f"{px(960)}x{px(520)}")
        self.minsize(760, 400)
        self.missiles = missiles
        self.on_select = on_select
        self.configure(bg=COLOR_MAIN_BG)

        self._build_ui()

    def _build_ui(self) -> None:
        top_frame = tk.Frame(self, bg=COLOR_PANEL_BG, padx=12, pady=10)
        top_frame.pack(fill="x", side="top")

        tk.Label(
            top_frame,
            text="Missile Inventory (58 Systems Across 10 Countries)",
            font=FONT_MAIN_TITLE,
            fg=COLOR_ACCENT,
            bg=COLOR_PANEL_BG,
        ).pack(side="left")

        search_frame = tk.Frame(top_frame, bg=COLOR_PANEL_BG)
        search_frame.pack(side="right")
        tk.Label(search_frame, text="Filter:", fg=COLOR_MUTED, bg=COLOR_PANEL_BG, font=FONT_NORMAL).pack(
            side="left", padx=4
        )
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._filter_tree())
        entry = ttk.Entry(search_frame, textvariable=self.search_var, width=22)
        entry.pack(side="left", padx=4)

        tree_frame = tk.Frame(self, bg=COLOR_MAIN_BG)
        tree_frame.pack(fill="both", expand=True, padx=12, pady=10)

        cols = ("country", "name", "type", "range", "speed", "warhead", "yield")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")

        self.tree.heading("country", text="Country")
        self.tree.heading("name", text="System Name")
        self.tree.heading("type", text="Classification")
        self.tree.heading("range", text="Max Range (km)")
        self.tree.heading("speed", text="Speed")
        self.tree.heading("warhead", text="Warhead Type")
        self.tree.heading("yield", text="Default Yield (kt)")

        self.tree.column("country", width=px(120))
        self.tree.column("name", width=px(180))
        self.tree.column("type", width=px(140))
        self.tree.column("range", width=px(110), anchor="e")
        self.tree.column("speed", width=px(110), anchor="center")
        self.tree.column("warhead", width=px(120), anchor="center")
        self.tree.column("yield", width=px(110), anchor="e")

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.tree.bind("<Double-1>", self._on_item_double_click)

        bot_frame = tk.Frame(self, bg=COLOR_PANEL_BG, padx=12, pady=8)
        bot_frame.pack(fill="x", side="bottom")

        self.count_lbl = tk.Label(
            bot_frame, text=f"Total: {len(self.missiles)} systems", fg=COLOR_MUTED, bg=COLOR_PANEL_BG, font=FONT_NORMAL
        )
        self.count_lbl.pack(side="left")

        ttk.Button(bot_frame, text="Close", command=self.destroy).pack(side="right")
        self._filter_tree()

    def _filter_tree(self) -> None:
        q = self.search_var.get().lower().strip()
        self.tree.delete(*self.tree.get_children())
        count = 0
        for m in self.missiles:
            c_name = m.get("country", "")
            name = m.get("name", "")
            mtype = m.get("type", "")
            if not q or (q in c_name.lower() or q in name.lower() or q in mtype.lower()):
                warhead_str = "Nuclear" if m.get("nuclear_capable") else "Conventional"
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

    def _on_item_double_click(self, _event: tk.Event) -> None:
        sel = self.tree.selection()
        if sel and self.on_select:
            missile_id = sel[0]
            m = next((item for item in self.missiles if item["id"] == missile_id), None)
            if m:
                self.on_select(m)
                self.destroy()


class ScenarioManagerDialog(tk.Toplevel):
    """dialog to view, load, and delete scenarios from sqlite"""

    def __init__(self, parent: tk.Widget, db: ScenarioDatabase, on_load=None):
        super().__init__(parent)
        self.title("Saved Scenarios")
        self.geometry(f"{px(860)}x{px(440)}")
        self.db = db
        self.on_load = on_load
        self.configure(bg=COLOR_MAIN_BG)

        self._build_ui()

    def _build_ui(self) -> None:
        top_frame = tk.Frame(self, bg=COLOR_PANEL_BG, padx=12, pady=10)
        top_frame.pack(fill="x", side="top")
        tk.Label(
            top_frame,
            text="Saved Scenarios (SQLite scenarios.db)",
            font=FONT_MAIN_TITLE,
            fg=COLOR_ACCENT,
            bg=COLOR_PANEL_BG,
        ).pack(side="left")

        tree_frame = tk.Frame(self, bg=COLOR_MAIN_BG)
        tree_frame.pack(fill="both", expand=True, padx=12, pady=10)

        cols = ("id", "name", "origin", "target", "missile", "date")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")

        self.tree.heading("id", text="ID")
        self.tree.heading("name", text="Scenario Name")
        self.tree.heading("origin", text="Origin City")
        self.tree.heading("target", text="Target City")
        self.tree.heading("missile", text="Missile ID")
        self.tree.heading("date", text="Created At")

        self.tree.column("id", width=px(50), anchor="center")
        self.tree.column("name", width=px(180))
        self.tree.column("origin", width=px(160))
        self.tree.column("target", width=px(160))
        self.tree.column("missile", width=px(110), anchor="center")
        self.tree.column("date", width=px(140), anchor="center")

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.tree.bind("<Double-1>", lambda _e: self._load_selected())

        bot_frame = tk.Frame(self, bg=COLOR_PANEL_BG, padx=12, pady=8)
        bot_frame.pack(fill="x", side="bottom")

        ttk.Button(bot_frame, text="Load Selected", command=self._load_selected).pack(side="left", padx=4)
        ttk.Button(bot_frame, text="Delete Selected", command=self._delete_selected).pack(side="left", padx=4)
        ttk.Button(bot_frame, text="Refresh", command=self._populate).pack(side="left", padx=4)
        ttk.Button(bot_frame, text="Close", command=self.destroy).pack(side="right")

        self._populate()

    def _populate(self) -> None:
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
                    s.missile_id,
                    str(s.created_at)[:19] if s.created_at else "N/A",
                ),
            )

    def _load_selected(self) -> None:
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

    def _delete_selected(self) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        scen_id = int(sel[0])
        if messagebox.askyesno("Confirm Delete", f"Delete scenario ID #{scen_id}?", parent=self):
            try:
                self.db.delete_scenario(scen_id)
                self._populate()
            except Exception as err:
                messagebox.showerror("Error", f"Failed to delete: {err}", parent=self)


class PhysicsInfoDialog(tk.Toplevel):
    """dialog detailing the glasstone-dolan blast physics equations"""

    def __init__(self, parent: tk.Widget):
        super().__init__(parent)
        self.title("Glasstone-Dolan Impact Physics Scaling Laws")
        self.geometry(f"{px(760)}x{px(520)}")
        self.configure(bg=COLOR_MAIN_BG)

        header = tk.Frame(self, bg=COLOR_PANEL_BG, padx=14, pady=10)
        header.pack(fill="x", side="top")
        tk.Label(
            header,
            text="Blast Physics and Casualty Scaling Equations",
            font=FONT_MAIN_TITLE,
            fg=COLOR_ACCENT,
            bg=COLOR_PANEL_BG,
        ).pack(side="left")

        text_box = tk.Text(self, wrap="word", font=FONT_MONO, bg=COLOR_INPUT_BG, fg=COLOR_TEXT, padx=14, pady=12)
        text_box.pack(fill="both", expand=True, padx=12, pady=10)

        docs = (
            "GLASSTONE-DOLAN (1977) BLAST SCALING LAWS\n"
            "=========================================\n\n"
            "1. CUBE-ROOT YIELD SCALING:\n"
            "   Concentric blast wave radii scale with explosive yield Y (in kilotons TNT eq.):\n"
            "     r(Y) = coefficient * Y^(1/3)\n\n"
            "2. DAMAGE RADII FORMULAS:\n"
            f"   - Fireball vaporization radius:       r_fireball = {FIREBALL_COEFF:.2f} * Y^{FIREBALL_EXP:.2f} km\n"
            f"   - Heavy blast (20 psi / 138 kPa):      r_20psi = {HEAVY_BLAST_20PSI_COEFF:.2f} * Y^(1/3) km\n"
            f"   - Moderate blast (5 psi / 34.5 kPa):   r_5psi = {MODERATE_BLAST_5PSI_COEFF:.2f} * Y^(1/3) km\n"
            f"   - Thermal radiation (3rd-deg burns):  r_thermal = {THERMAL_NUCLEAR_COEFF:.2f} * Y^{THERMAL_NUCLEAR_EXP:.2f} km (nuclear)\n"
            f"                                         r_thermal = {THERMAL_CONV_COEFF:.2f} * Y^(1/3) km (conventional)\n"
            f"   - Light blast (1 psi / 6.9 kPa):       r_1psi = {LIGHT_BLAST_1PSI_COEFF:.2f} * Y^(1/3) km\n\n"
            "3. CASUALTY FRACTIONS BY ZONE:\n"
            f"   - Heavy zone (0 to r_20psi):\n"
            f"       Fatalities: {int(FATALITY_RATE_HEAVY * 100)}% | Injuries: {int(INJURY_RATE_HEAVY * 100)}% | Structures destroyed: {int(STRUCT_DESTROY_HEAVY * 100)}%\n"
            f"   - Moderate ring (r_20psi to r_5psi):\n"
            f"       Fatalities: {int(FATALITY_RATE_MODERATE * 100)}% | Injuries: {int(INJURY_RATE_MODERATE * 100)}% | Structures destroyed: {int(STRUCT_DESTROY_MODERATE * 100)}%\n"
            f"   - Light / outer ring (r_5psi to max(r_1psi, r_thermal)):\n"
            f"       Fatalities: {int(FATALITY_RATE_LIGHT * 100)}% | Injuries: {int(INJURY_RATE_LIGHT * 100)}%\n\n"
            "4. STRUCTURAL EXPOSURE RATIO:\n"
            f"   - Estimated buildings per km2: {STRUCTURES_PER_PERSON:.2f} * population_density\n\n"
            "5. FLIGHT DYNAMICS:\n"
            f"   - Speed conversion: Mach * {MACH_TO_KMH:.1f} km/h\n"
            f"   - Ballistic missiles (Mach >= 5): average speed = {int(BALLISTIC_AVG_RATIO * 100)}% of peak terminal Mach\n"
            f"   - Cruise / tactical missiles (Mach < 5): average speed = {int(CRUISE_AVG_RATIO * 100)}% of cruise Mach\n"
        )
        text_box.insert("1.0", docs)
        text_box.configure(state="disabled")

        bot = tk.Frame(self, bg=COLOR_PANEL_BG, padx=12, pady=8)
        bot.pack(fill="x", side="bottom")
        ttk.Button(bot, text="Close", command=self.destroy).pack(side="right")


class MissileSimulatorApp(tk.Tk):
    """main application window coordinating controls, 3d globe, and simulation results"""

    def __init__(self, globe_url: str, api: SimulatorApi, bridge: Optional[GlobeBridgeServer] = None, on_exit=None):
        super().__init__()
        self.globe_url = globe_url
        self.api = api
        self.bridge = bridge
        self.on_exit = on_exit

        self.title("Missile Impact Simulator")
        self.geometry(f"{px(1440)}x{px(880)}")
        self.minsize(px(1120), px(720))
        self.configure(bg=COLOR_MAIN_BG)

        self.child_hwnd: Optional[int] = None
        self.current_width: int = 700
        self.current_height: int = 800

        self.db = ScenarioDatabase()
        self.missiles = load_missiles()
        self.geocoding_service = GeocodingService()

        # application state
        self.origin_candidate: Optional[PlaceCandidate] = None
        self.dest_candidate: Optional[PlaceCandidate] = None
        self.selected_missile: Optional[Dict[str, Any]] = None
        self.current_pop_info: Optional[Dict[str, Any]] = None
        self.current_distance_km: float = 0.0
        self.is_in_range: bool = False
        self.active_pick_mode: str = "origin"  # place the launch site first, then the target
        self._fly_seq: int = 0

        self._configure_styles()
        self._build_menu()
        self._build_toolbar()
        self._build_layout()
        self._build_statusbar()

        self._init_defaults()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # flat look: border, light and dark bevel colors all set to one subtle grey
        flat = dict(bordercolor=COLOR_BORDER, lightcolor=COLOR_BORDER, darkcolor=COLOR_BORDER)
        style.configure(".", background=COLOR_PANEL_BG, foreground=COLOR_TEXT, **flat)
        style.configure("TLabel", background=COLOR_PANEL_BG, foreground=COLOR_TEXT, font=FONT_NORMAL)
        style.configure("TLabelframe", background=COLOR_PANEL_BG, foreground=COLOR_TEXT, **flat)
        style.configure("TLabelframe.Label", background=COLOR_PANEL_BG, foreground=COLOR_TEXT, font=FONT_CARD_TITLE)
        style.configure("TEntry", fieldbackground=COLOR_INPUT_BG, foreground=COLOR_TEXT, insertcolor=COLOR_TEXT, **flat)
        style.map("TEntry", bordercolor=[("focus", COLOR_MUTED)], lightcolor=[("focus", COLOR_MUTED)])
        style.configure(
            "TCombobox", fieldbackground=COLOR_INPUT_BG, background=COLOR_INPUT_BG, foreground=COLOR_TEXT,
            arrowcolor=COLOR_MUTED, insertcolor=COLOR_TEXT, selectbackground=COLOR_HOVER, selectforeground=COLOR_TEXT, **flat,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", COLOR_INPUT_BG)],
            background=[("active", COLOR_HOVER), ("readonly", COLOR_INPUT_BG)],
            selectbackground=[("readonly", COLOR_INPUT_BG)],
            selectforeground=[("readonly", COLOR_TEXT)],
            foreground=[("readonly", COLOR_TEXT)],
        )
        # dropdown list of comboboxes
        self.option_add("*TCombobox*Listbox.background", COLOR_INPUT_BG)
        self.option_add("*TCombobox*Listbox.foreground", COLOR_TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", COLOR_HOVER)
        self.option_add("*TCombobox*Listbox.selectForeground", COLOR_TEXT)
        sec = BUTTON_STYLES["secondary"]
        style.configure(
            "TButton", background=sec["bg"], foreground=sec["fg"], font=FONT_BUTTON,
            padding=(px(12), px(4)), relief="flat", focuscolor=sec["bg"],
            bordercolor=sec["bg"], lightcolor=sec["bg"], darkcolor=sec["bg"],
        )
        style.map(
            "TButton",
            background=[("disabled", BUTTON_DISABLED["bg"]), ("pressed", sec["press"]), ("active", sec["hover"])],
            bordercolor=[("disabled", BUTTON_DISABLED["bg"]), ("pressed", sec["press"]), ("active", sec["hover"])],
            lightcolor=[("pressed", sec["press"]), ("active", sec["hover"])],
            darkcolor=[("pressed", sec["press"]), ("active", sec["hover"])],
            foreground=[("disabled", BUTTON_DISABLED["fg"])],
            relief=[("pressed", "flat")],
        )
        self.option_add("*TButton.cursor", "hand2")
        style.configure(
            "Vertical.TScrollbar", background=COLOR_BORDER, troughcolor=COLOR_MAIN_BG, arrowcolor=COLOR_MUTED,
            gripcount=0, **flat,
        )
        style.map("Vertical.TScrollbar", background=[("active", COLOR_HOVER)])
        style.map("TCheckbutton", background=[("active", COLOR_PANEL_BG)])
        style.configure("TCheckbutton", indicatorbackground=COLOR_INPUT_BG, indicatorforeground=COLOR_TEXT)
        style.configure("Treeview", background=COLOR_INPUT_BG, foreground=COLOR_TEXT, fieldbackground=COLOR_INPUT_BG)
        style.map("Treeview", background=[("selected", COLOR_BORDER)], foreground=[("selected", COLOR_ACCENT)])
        style.configure("Treeview.Heading", background=COLOR_PANEL_BG, foreground=COLOR_ACCENT, font=FONT_BOLD)
        style.configure("TCheckbutton", background=COLOR_PANEL_BG, foreground=COLOR_TEXT, font=FONT_NORMAL)

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Save Scenario...", command=self.open_save_dialog, accelerator="Ctrl+S")
        file_menu.add_command(label="Load Scenario...", command=self.open_scenarios_dialog, accelerator="Ctrl+O")
        file_menu.add_separator()
        file_menu.add_command(label="Clear All", command=self.reset_all)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_closing, accelerator="Ctrl+Q")
        menubar.add_cascade(label="File", menu=file_menu)

        missile_menu = tk.Menu(menubar, tearoff=0)
        missile_menu.add_command(label="Technical Catalog...", command=self.open_missile_catalog)
        missile_menu.add_separator()
        for country in ["India", "United States", "Russia", "China", "France", "United Kingdom"]:
            missile_menu.add_command(label=f"{country} Missiles", command=lambda c=country: self.open_missile_catalog_filter(c))
        menubar.add_cascade(label="Missiles", menu=missile_menu)

        scen_menu = tk.Menu(menubar, tearoff=0)
        scen_menu.add_command(label="Saved Scenarios...", command=self.open_scenarios_dialog)
        menubar.add_cascade(label="Scenarios", menu=scen_menu)

        phys_menu = tk.Menu(menubar, tearoff=0)
        phys_menu.add_command(label="Blast Physics Formulas...", command=self.open_physics_info)
        menubar.add_cascade(label="Physics", menu=phys_menu)

        self.config(menu=menubar)
        self.bind("<Control-s>", lambda _: self.open_save_dialog())
        self.bind("<Control-o>", lambda _: self.open_scenarios_dialog())
        self.bind("<Control-q>", lambda _: self.on_closing())

    def _build_toolbar(self) -> None:
        toolbar = tk.Frame(self, bg=COLOR_MAIN_BG, height=40, padx=12, pady=6)
        toolbar.pack(fill="x", side="top")

        title_box = tk.Frame(toolbar, bg=COLOR_MAIN_BG)
        title_box.pack(side="left")

        tk.Label(
            title_box,
            text="MISSILE IMPACT SIMULATOR",
            font=FONT_MAIN_TITLE,
            fg=COLOR_ACCENT,
            bg=COLOR_MAIN_BG,
        ).pack(side="left")

        btn_box = tk.Frame(toolbar, bg=COLOR_MAIN_BG)
        btn_box.pack(side="right")

        buttons = [
            ("Missile Catalog", self.open_missile_catalog),
            ("Saved Scenarios", self.open_scenarios_dialog),
            ("Save Scenario", self.open_save_dialog),
            ("Blast Physics", self.open_physics_info),
        ]
        for label, cmd in buttons:
            FlatButton(btn_box, kind="ghost", text=label, command=cmd).pack(side="left", padx=(px(2), 0))

    def _build_layout(self) -> None:
        # main 3-column body
        body = tk.Frame(self, bg=COLOR_MAIN_BG)
        body.pack(fill="both", expand=True, padx=6, pady=4)

        # left column: mission controls
        self.left_col = tk.Frame(body, bg=COLOR_MAIN_BG, width=px(360))
        self.left_col.pack(side="left", fill="y", padx=(0, 4))
        self.left_col.pack_propagate(False)
        self._build_left_controls()

        # center column: 3d globe container
        self.viewport_frame = tk.Frame(body, bg=COLOR_MAIN_BG)
        self.viewport_frame.pack(side="left", fill="both", expand=True)
        self.viewport_frame.bind("<Configure>", self.on_viewport_resize)

        self.update()
        self.tk_hwnd = self.viewport_frame.winfo_id()

        # right column: post-impact results panel
        self.right_col = tk.Frame(body, bg=COLOR_MAIN_BG, width=px(380))
        self.right_col.pack(side="right", fill="y", padx=(4, 0))
        self.right_col.pack_propagate(False)
        self._build_right_results()

    def _build_left_controls(self) -> None:
        # scrollable container for left column
        canvas = tk.Canvas(self.left_col, bg=COLOR_MAIN_BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.left_col, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=COLOR_MAIN_BG)

        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_win = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_win, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # 1. origin section
        self.origin_panel = CitySearchPanel(inner, "1. Origin (Launch Site)", self.geocoding_service, self._on_origin_selected)
        self.origin_panel.pack(fill="x", padx=4, pady=(2, 6))

        orig_btn_row = tk.Frame(self.origin_panel, bg=COLOR_PANEL_BG)
        orig_btn_row.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        self.pick_orig_btn = FlatButton(
            orig_btn_row,
            text="Pick Origin on Map",
            command=lambda: self._set_pick_mode("origin"),
        )
        self.pick_orig_btn.pack(side="left", fill="x", expand=True)

        # 2. target section
        self.dest_panel = CitySearchPanel(inner, "2. Target (Detonation Site)", self.geocoding_service, self._on_dest_selected)
        self.dest_panel.pack(fill="x", padx=4, pady=6)

        dest_btn_row = tk.Frame(self.dest_panel, bg=COLOR_PANEL_BG)
        dest_btn_row.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(4, 2))
        self.pick_dest_btn = FlatButton(
            dest_btn_row,
            text="Pick Target on Map",
            command=lambda: self._set_pick_mode("destination"),
        )
        self.pick_dest_btn.pack(side="left", fill="x", expand=True)

        self.target_pop_var = tk.StringVar(value="Population: -- | Density: --")
        tk.Label(
            self.dest_panel,
            textvariable=self.target_pop_var,
            fg=COLOR_MUTED,
            bg=COLOR_PANEL_BG,
            font=FONT_SMALL,
            anchor="w",
        ).grid(row=5, column=0, columnspan=3, sticky="w", pady=(2, 0))

        # 3. missile and warhead configuration
        m_frame = ttk.LabelFrame(inner, text="3. Missile & Warhead", padding=8)
        m_frame.pack(fill="x", padx=4, pady=6)

        # filters
        f_grid = tk.Frame(m_frame, bg=COLOR_PANEL_BG)
        f_grid.pack(fill="x", pady=(0, 4))
        f_grid.columnconfigure(0, weight=1)
        f_grid.columnconfigure(1, weight=1)

        tk.Label(f_grid, text="Country:", fg=COLOR_MUTED, bg=COLOR_PANEL_BG, font=FONT_SMALL).grid(row=0, column=0, sticky="w")
        tk.Label(f_grid, text="Warhead:", fg=COLOR_MUTED, bg=COLOR_PANEL_BG, font=FONT_SMALL).grid(row=0, column=1, sticky="w")

        countries = ["All Countries"] + sorted(list(set(m["country"] for m in self.missiles)))
        self.country_filter_var = tk.StringVar(value="All Countries")
        self.country_combo = ttk.Combobox(f_grid, textvariable=self.country_filter_var, values=countries, state="readonly", width=14)
        self.country_combo.grid(row=1, column=0, sticky="ew", padx=(0, 2))
        self.country_combo.bind("<<ComboboxSelected>>", lambda _: self._filter_missiles())

        self.warhead_filter_var = tk.StringVar(value="All Types")
        self.warhead_combo = ttk.Combobox(
            f_grid,
            textvariable=self.warhead_filter_var,
            values=["All Types", "Nuclear-Capable", "Conventional-Only"],
            state="readonly",
            width=14,
        )
        self.warhead_combo.grid(row=1, column=1, sticky="ew", padx=(2, 0))
        self.warhead_combo.bind("<<ComboboxSelected>>", lambda _: self._filter_missiles())

        # missile box: type in it to search, pick from the dropdown
        tk.Label(m_frame, text="Missile (type to search):", fg=COLOR_TEXT, bg=COLOR_PANEL_BG, font=FONT_BOLD).pack(
            anchor="w", pady=(4, 2)
        )
        self.missile_combo = ttk.Combobox(m_frame)
        self.missile_combo.pack(fill="x", pady=2)
        self.missile_combo.bind("<<ComboboxSelected>>", self._on_missile_selected)
        self.missile_combo.bind("<KeyRelease>", self._on_missile_typed)
        self.missile_combo.bind("<Return>", lambda _e: self._pick_top_missile_match())
        self.missile_combo.bind("<FocusOut>", lambda _e: self.after(50, self._restore_if_left_missile_box))

        # match count, so typing always shows what happened
        self.missile_match_var = tk.StringVar(value="")
        self.missile_match_lbl = tk.Label(m_frame, textvariable=self.missile_match_var, fg=COLOR_MUTED,
                                          bg=COLOR_PANEL_BG, font=FONT_SMALL, anchor="w")
        self.missile_match_lbl.pack(fill="x")

        # specs card
        self.spec_frame = tk.Frame(m_frame, bg=COLOR_INPUT_BG, padx=8, pady=6, highlightthickness=1, highlightbackground=COLOR_BORDER)
        self.spec_frame.pack(fill="x", pady=6)
        self.spec_lbl_country = tk.Label(self.spec_frame, text="Country: --", fg=COLOR_MUTED, bg=COLOR_INPUT_BG, font=FONT_SMALL, anchor="w")
        self.spec_lbl_country.pack(fill="x")
        self.spec_lbl_range = tk.Label(self.spec_frame, text="Range: --", fg=COLOR_MUTED, bg=COLOR_INPUT_BG, font=FONT_SMALL, anchor="w")
        self.spec_lbl_range.pack(fill="x")
        self.spec_lbl_speed = tk.Label(self.spec_frame, text="Speed: --", fg=COLOR_MUTED, bg=COLOR_INPUT_BG, font=FONT_SMALL, anchor="w")
        self.spec_lbl_speed.pack(fill="x")

        # warhead & yield options
        w_row = tk.Frame(m_frame, bg=COLOR_PANEL_BG)
        w_row.pack(fill="x", pady=4)

        self.is_nuclear_var = tk.BooleanVar(value=True)
        self.nuke_check = ttk.Checkbutton(
            w_row, text="Nuclear Warhead", variable=self.is_nuclear_var, command=self._on_warhead_mode_changed
        )
        self.nuke_check.pack(side="left")

        self.conv_note_lbl = tk.Label(w_row, text="", fg=COLOR_AMBER, bg=COLOR_PANEL_BG, font=FONT_SMALL)
        self.conv_note_lbl.pack(side="left", padx=6)

        yield_row = tk.Frame(m_frame, bg=COLOR_PANEL_BG)
        yield_row.pack(fill="x", pady=2)
        tk.Label(yield_row, text="Yield (kt):", fg=COLOR_MUTED, bg=COLOR_PANEL_BG, font=FONT_NORMAL).pack(side="left")
        self.yield_var = tk.StringVar(value="250")
        self.yield_combo = ttk.Combobox(
            yield_row,
            textvariable=self.yield_var,
            values=["1", "10", "15", "40", "100", "250", "335", "500", "1000"],
            state="readonly",
            width=8,
        )
        self.yield_combo.pack(side="left", padx=6)
        self.yield_combo.bind("<<ComboboxSelected>>", lambda _: self._on_yield_changed())

        # 4. range check & launch button
        launch_frame = ttk.LabelFrame(inner, text="4. Range & Simulation", padding=8)
        launch_frame.pack(fill="x", padx=4, pady=(6, 8))

        self.range_status_var = tk.StringVar(value="Select origin and target to calculate range")
        self.range_status_lbl = tk.Label(
            launch_frame,
            textvariable=self.range_status_var,
            fg=COLOR_MUTED,
            bg=COLOR_PANEL_BG,
            font=FONT_BOLD,
            wraplength=px(320),
            justify="left",
        )
        self.range_status_lbl.pack(fill="x", pady=(2, 6))

        btn_row = tk.Frame(launch_frame, bg=COLOR_PANEL_BG)
        btn_row.pack(fill="x")

        self.launch_btn = FlatButton(
            btn_row,
            kind="primary",
            large=True,
            text="Simulate Launch",
            command=self.simulate_launch,
            state="disabled",
        )
        self.launch_btn.pack(side="left", fill="x", expand=True)

        # secondary action: neutral so it never competes with the red launch button
        self.clear_btn = FlatButton(btn_row, large=True, text="Clear", command=self.reset_all)
        self.clear_btn.pack(side="left", padx=(px(6), 0))

    def _build_right_results(self) -> None:
        canvas = tk.Canvas(self.right_col, bg=COLOR_MAIN_BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.right_col, orient="vertical", command=canvas.yview)
        self.right_inner = tk.Frame(canvas, bg=COLOR_MAIN_BG)

        self.right_inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_win = canvas.create_window((0, 0), window=self.right_inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_win, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        header_frame = tk.Frame(self.right_inner, bg=COLOR_PANEL_BG, padx=10, pady=8)
        header_frame.pack(fill="x", padx=4, pady=(2, 6))
        tk.Label(header_frame, text="Post-Impact Assessment", font=FONT_MAIN_TITLE, fg=COLOR_ACCENT, bg=COLOR_PANEL_BG).pack(
            side="left"
        )

        self.results_container = tk.Frame(self.right_inner, bg=COLOR_MAIN_BG)
        self.results_container.pack(fill="both", expand=True, padx=4)

        # placeholder waiting message
        self.placeholder_lbl = tk.Label(
            self.results_container,
            text="Select an origin, target, and missile on the left, then click Simulate Launch to view blast radii and casualty estimates.",
            fg=COLOR_MUTED,
            bg=COLOR_MAIN_BG,
            font=FONT_NORMAL,
            wraplength=px(340),
            justify="center",
            padx=12,
            pady=40,
        )
        self.placeholder_lbl.pack(fill="both", expand=True)

    def _build_statusbar(self) -> None:
        statusbar = tk.Frame(self, bg=COLOR_INPUT_BG, height=24, padx=12, pady=4)
        statusbar.pack(fill="x", side="bottom")

        self.status_var = tk.StringVar(value="Ready")
        tk.Label(statusbar, textvariable=self.status_var, font=FONT_SMALL, fg=COLOR_MUTED, bg=COLOR_INPUT_BG).pack(
            side="left"
        )

        tk.Label(
            statusbar,
            text="3D Viewport: Active | Geocoding: OpenStreetMap & GeoNames",
            font=FONT_SMALL,
            fg=COLOR_MUTED,
            bg=COLOR_INPUT_BG,
        ).pack(side="left", padx=16)

        tk.Label(
            statusbar,
            text=f"Inventory: {len(self.missiles)} Missiles | SQLite: scenarios.db",
            font=FONT_SMALL,
            fg=COLOR_MUTED,
            bg=COLOR_INPUT_BG,
        ).pack(side="right")

    def _init_defaults(self) -> None:
        self._filter_missiles()
        # select agni_v by default if present
        self._select_missile_by_id("agni_v")
        if self.bridge and self.selected_missile:
            self.bridge.update_state(missile=self.selected_missile)
        self._set_pick_mode("origin")

    def _next_fly_id(self) -> int:
        """unique id per camera move, so the globe never skips a repeated move"""
        self._fly_seq += 1
        return self._fly_seq

    def _advance_to_target_mode(self) -> None:
        """after the launch site is placed, map clicks place the target next"""
        if self.origin_candidate and not self.dest_candidate and self.active_pick_mode == "origin":
            self._set_pick_mode("destination")

    @staticmethod
    def _missile_label(m: Dict[str, Any]) -> str:
        return f"{m['name']} ({m.get('country', '')})"

    def _filter_missiles(self, query: str = "") -> None:
        """narrow the missile list by the country and warhead filters and the typed query.

        with a query (the user is typing) the list narrows but nothing is selected yet;
        without one (a filter changed) the current missile stays if it still fits.
        """
        c_filter = self.country_filter_var.get()
        w_filter = self.warhead_filter_var.get()
        q = query.strip()

        matched = []
        for m in self.missiles:
            if c_filter != "All Countries" and m.get("country") != c_filter:
                continue
            if w_filter == "Nuclear-Capable" and not m.get("nuclear_capable"):
                continue
            if w_filter == "Conventional-Only" and m.get("nuclear_capable"):
                continue
            if q and not missile_matches(m, q):
                continue
            matched.append(m)

        if not matched:
            # keep the current missile selected, and say why nothing is listed
            self.missile_match_var.set(f"No missiles match “{q}”" if q else "No missiles match these filters")
            self.missile_match_lbl.config(fg=COLOR_AMBER)
            if q:
                self.filtered_missiles = []
                self.missile_combo["values"] = []
            return

        self.filtered_missiles = matched
        self.missile_combo["values"] = [self._missile_label(m) for m in matched]
        self.missile_match_lbl.config(fg=COLOR_MUTED)

        if q:
            count = f"{len(matched)} match" if len(matched) == 1 else f"{len(matched)} matches"
            self.missile_match_var.set(f"{count} · Enter picks the first, ↓ shows all")
            return

        filtered = c_filter != "All Countries" or w_filter != "All Types"
        self.missile_match_var.set(f"{len(matched)} missiles match the filters" if filtered else "")
        # keep the current missile if it still fits the filters; otherwise take the first
        current = self.selected_missile
        if current in matched:
            self.missile_combo.current(matched.index(current))
        else:
            self.missile_combo.current(0)
            self._apply_missile(matched[0])

    def _on_missile_typed(self, event: tk.Event) -> None:
        if event.keysym in ("Up", "Down", "Return", "Escape", "Tab", "Shift_L", "Shift_R", "Control_L", "Control_R"):
            return
        text = self.missile_combo.get()
        if self.selected_missile and text == self._missile_label(self.selected_missile):
            return
        self._filter_missiles(query=text)

    def _pick_top_missile_match(self) -> None:
        """enter: take the first match of what was typed"""
        text = self.missile_combo.get().strip()
        if self.selected_missile and text == self._missile_label(self.selected_missile):
            return
        if text and self.filtered_missiles and all(missile_matches(m, text) for m in self.filtered_missiles):
            self._choose_missile(self.filtered_missiles[0])
        else:
            self._restore_missile_text()

    def _choose_missile(self, m: Dict[str, Any]) -> None:
        """select a missile and reset the list to the filters, so the next search starts fresh"""
        self._apply_missile(m)
        self._filter_missiles()
        self.missile_combo.icursor("end")
        self.missile_combo.selection_clear()

    def _restore_if_left_missile_box(self) -> None:
        """focus also leaves the box when its dropdown opens; only restore if it really left"""
        try:
            widget = self.focus_get()
        except (KeyError, tk.TclError):
            return  # focus is inside the dropdown list (an internal ttk widget)
        if widget is self.missile_combo or (widget is not None and "popdown" in str(widget)):
            return
        self._restore_missile_text()

    def _restore_missile_text(self) -> None:
        """leaving the box without choosing puts the current missile back"""
        if self.selected_missile and self.missile_combo.get() != self._missile_label(self.selected_missile):
            self._filter_missiles()

    def _select_missile_by_id(self, missile_id: str) -> None:
        for idx, m in enumerate(self.missiles):
            if m["id"] == missile_id:
                self.selected_missile = m
                self.country_filter_var.set("All Countries")
                self.warhead_filter_var.set("All Types")
                self._filter_missiles()
                try:
                    target_idx = [item["id"] for item in self.filtered_missiles].index(missile_id)
                    self.missile_combo.current(target_idx)
                except ValueError:
                    pass
                self._apply_missile(m)
                break

    def _on_missile_selected(self, _event: tk.Event) -> None:
        idx = self.missile_combo.current()
        if 0 <= idx < len(self.filtered_missiles):
            self._choose_missile(self.filtered_missiles[idx])

    def _apply_missile(self, m: Dict[str, Any]) -> None:
        self.selected_missile = m
        if m.get("nuclear_capable"):
            def_y = m.get("default_nuclear_yield_kt", 250)
            self.yield_var.set(str(int(def_y) if def_y == int(def_y) else def_y))
        self._update_spec_card()
        self._update_warhead_ui_state()
        self._update_range_and_pins()
        self._update_assessment_preview()

    def _update_spec_card(self) -> None:
        if not self.selected_missile:
            self.spec_lbl_country.config(text="Country: --")
            self.spec_lbl_range.config(text="Range: --")
            self.spec_lbl_speed.config(text="Speed: --")
            return

        m = self.selected_missile
        c_text = f"{m.get('country', '')} - {m.get('type', '')}"
        r_text = f"Range: {m.get('min_range_km', 0):,} - {m.get('max_range_km', 0):,} km"

        speeds = get_speed_stats(m, self.current_distance_km)
        s_text = (
            f"Top: Mach {speeds['top_speed_mach']} ({speeds['top_speed_kmh']:,.0f} km/h) | "
            f"Avg: Mach {speeds['avg_speed_mach']} ({speeds['avg_speed_kmh']:,.0f} km/h)"
        )

        self.spec_lbl_country.config(text=c_text)
        self.spec_lbl_range.config(text=r_text)
        self.spec_lbl_speed.config(text=s_text)

    def _update_warhead_ui_state(self) -> None:
        if not self.selected_missile:
            return

        is_nuke_capable = bool(self.selected_missile.get("nuclear_capable", False))
        if not is_nuke_capable:
            self.is_nuclear_var.set(False)
            self.nuke_check.config(state="disabled")
            self.conv_note_lbl.config(text="Conventional-only missile")
            self.yield_combo.config(state="disabled")
        else:
            self.nuke_check.config(state="normal")
            self.conv_note_lbl.config(text="")
            if self.is_nuclear_var.get():
                self.yield_combo.config(state="readonly")
            else:
                self.yield_combo.config(state="disabled")

    def _on_warhead_mode_changed(self) -> None:
        self._update_warhead_ui_state()
        self._update_range_and_pins()
        self._update_assessment_preview()

    def _on_yield_changed(self) -> None:
        self._update_range_and_pins()
        self._update_assessment_preview()

    def _set_pick_mode(self, mode: str) -> None:
        self.active_pick_mode = mode
        if self.bridge:
            self.bridge.update_state(pick_mode=mode)
        if mode == "origin":
            self.pick_orig_btn.set_kind("selected-origin")
            self.pick_dest_btn.set_kind("secondary")
            self.status_var.set("Click the globe to place the launch site")
        else:
            self.pick_dest_btn.set_kind("selected-target")
            self.pick_orig_btn.set_kind("secondary")
            self.status_var.set("Click the globe to place the target")

    def _on_origin_selected(self, cand: Optional[PlaceCandidate]) -> None:
        self.origin_candidate = cand
        self._update_range_and_pins()
        self._update_assessment_preview()
        if cand and self.bridge:
            self.bridge.update_state(
                origin={"label": cand.label, "longitude": cand.longitude, "latitude": cand.latitude},
                missile=self.selected_missile,
                fly_to={"lon": cand.longitude, "lat": cand.latitude, "height": 450000.0, "fly_id": self._next_fly_id()},
            )
        self._advance_to_target_mode()

    def _on_dest_selected(self, cand: Optional[PlaceCandidate]) -> None:
        self.dest_candidate = cand
        # drop the previous target's population so it isn't shown for the new target
        self.current_pop_info = None
        if cand:
            # fetch population on daemon thread
            def _worker():
                pop = self.api.get_population(cand.longitude, cand.latitude, cand.label)
                self.after(0, lambda: self._apply_population_update(pop))

            threading.Thread(target=_worker, daemon=True).start()

            if self.bridge:
                self.bridge.update_state(
                    destination={"label": cand.label, "longitude": cand.longitude, "latitude": cand.latitude},
                    missile=self.selected_missile,
                    fly_to={"lon": cand.longitude, "lat": cand.latitude, "height": 350000.0, "fly_id": self._next_fly_id()},
                )
        else:
            self.target_pop_var.set("Population: -- | Density: --")
            self.current_pop_info = None

        self._update_range_and_pins()
        self._update_assessment_preview()

    def _apply_population_update(self, pop: Dict[str, Any]) -> None:
        self.current_pop_info = pop
        pop_num = pop.get("population", 0)
        dens_num = pop.get("density_per_km2", 0.0)
        self.target_pop_var.set(f"Pop: {pop_num:,} | Density: {dens_num:,.0f}/km2")
        self._update_assessment_preview()

    def on_globe_pick(self, role: str, lon: float, lat: float) -> None:
        """callback invoked from bridge server when user clicks or drags pin on globe"""
        def _worker():
            try:
                cand_data = self.api.reverse_geocode(lon, lat)
                cand = PlaceCandidate(
                    label=cand_data["label"],
                    longitude=cand_data["longitude"],
                    latitude=cand_data["latitude"],
                    provider_place_id=cand_data.get("provider_place_id", "pin"),
                    attribution=cand_data.get("attribution", "OpenStreetMap"),
                )
            except Exception:
                cand = PlaceCandidate(
                    label=f"Coordinates ({lat:.3f}, {lon:.3f})",
                    longitude=lon,
                    latitude=lat,
                    provider_place_id="manual-pin",
                )

            pop_data = None
            if role == "destination":
                pop_data = self.api.get_population(lon, lat, cand.label)

            self.after(0, lambda: self._apply_globe_pick(role, cand, pop_data))

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_globe_pick(self, role: str, cand: PlaceCandidate, pop_data: Optional[Dict[str, Any]]) -> None:
        if role == "origin":
            self.origin_candidate = cand
            self.origin_panel.set_place(cand)
            self._advance_to_target_mode()
        else:
            self.dest_candidate = cand
            self.dest_panel.set_place(cand)
            if pop_data:
                self._apply_population_update(pop_data)

        self._update_range_and_pins()
        self._update_assessment_preview()

    def _update_range_and_pins(self) -> None:
        # inputs changed, so any blast rings on the globe belong to an old launch
        if self.bridge:
            self.bridge.update_state(launched=False, impact=None)

        o_data = (
            {"label": self.origin_candidate.label, "longitude": self.origin_candidate.longitude, "latitude": self.origin_candidate.latitude}
            if self.origin_candidate
            else None
        )
        d_data = (
            {"label": self.dest_candidate.label, "longitude": self.dest_candidate.longitude, "latitude": self.dest_candidate.latitude}
            if self.dest_candidate
            else None
        )

        if not self.origin_candidate or not self.dest_candidate:
            self.current_distance_km = 0.0
            self.is_in_range = False
            if not self.origin_candidate and not self.dest_candidate:
                self.range_status_var.set("Select origin and target to calculate range")
            elif not self.origin_candidate:
                self.range_status_var.set("Select an origin point to calculate range")
            else:
                self.range_status_var.set("Select a target point to calculate range")
            self.range_status_lbl.config(fg=COLOR_MUTED)
            self.launch_btn.config(state="disabled")
            self._update_spec_card()
            if self.bridge:
                self.bridge.update_state(
                    origin=o_data,
                    destination=d_data,
                    missile=self.selected_missile,
                    in_range=False,
                    range_message=self.range_status_var.get(),
                )
            return

        o_lon, o_lat = self.origin_candidate.longitude, self.origin_candidate.latitude
        d_lon, d_lat = self.dest_candidate.longitude, self.dest_candidate.latitude
        self.current_distance_km = calculate_great_circle_distance_km(o_lon, o_lat, d_lon, d_lat)

        self._update_spec_card()

        if not self.selected_missile:
            self.is_in_range = False
            self.range_status_var.set("No missile selected")
            self.range_status_lbl.config(fg=COLOR_MUTED)
            self.launch_btn.config(state="disabled")
            if self.bridge:
                self.bridge.update_state(
                    origin=o_data,
                    destination=d_data,
                    missile=None,
                    in_range=False,
                    range_message="No missile selected",
                )
            return

        range_check = check_within_range(self.current_distance_km, self.selected_missile)
        self.is_in_range = range_check["in_range"]
        max_r = self.selected_missile.get("max_range_km", 0)

        if self.is_in_range:
            self.range_status_var.set(f"In Range: {self.current_distance_km:,.1f} km / {max_r:,.0f} km")
            self.range_status_lbl.config(fg=COLOR_GREEN)
            self.launch_btn.config(state="normal")
        else:
            self.range_status_var.set(f"Out of Range: {self.current_distance_km:,.1f} km > {max_r:,.0f} km max")
            self.range_status_lbl.config(fg=COLOR_RED)
            self.launch_btn.config(state="disabled")

        if self.bridge:
            self.bridge.update_state(
                origin=o_data,
                destination=d_data,
                missile=self.selected_missile,
                in_range=self.is_in_range,
                range_message=self.range_status_var.get(),
            )

    def simulate_launch(self) -> None:
        if not self.origin_candidate or not self.dest_candidate or not self.selected_missile:
            return

        self.launch_btn.config(state="disabled", text="Simulating...")
        self.status_var.set("Simulating trajectory and blast effects...")

        orig_dict = {
            "label": self.origin_candidate.label,
            "longitude": self.origin_candidate.longitude,
            "latitude": self.origin_candidate.latitude,
        }
        dest_dict = {
            "label": self.dest_candidate.label,
            "longitude": self.dest_candidate.longitude,
            "latitude": self.dest_candidate.latitude,
        }
        missile_id = self.selected_missile["id"]
        is_nuke = bool(self.is_nuclear_var.get())
        yield_kt = float(self.yield_var.get()) if is_nuke else float(self.selected_missile.get("conventional_yield_kt", 0.001))
        dens = self.current_pop_info.get("density_per_km2") if self.current_pop_info else None

        def _worker():
            res = self.api.simulate_launch(orig_dict, dest_dict, missile_id, is_nuke, yield_kt, dens)
            self.after(0, lambda: self._on_simulation_complete(res))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_simulation_complete(self, res: Dict[str, Any]) -> None:
        self.launch_btn.config(state="normal", text="Simulate Launch")

        if not res.get("success"):
            err_msg = res.get("error", "Simulation could not be completed.")
            messagebox.showwarning("Simulation Notice", err_msg, parent=self)
            self.status_var.set(err_msg)
            return

        self.status_var.set("Simulation complete")
        impact = res["impact"]

        if self.bridge:
            self.bridge.update_state(
                launched=True,
                impact=impact,
                fly_to={
                    "lon": self.dest_candidate.longitude,
                    "lat": self.dest_candidate.latitude,
                    "height": max(impact["radii_km"]["light_blast_1psi_km"] * 3500.0, 150000.0),
                    "fly_id": self._next_fly_id(),
                },
            )

        self._render_results(res)

    def _update_assessment_preview(self) -> None:
        if not self.dest_candidate or not self.selected_missile:
            return

        is_nuke = bool(self.is_nuclear_var.get())
        yield_kt = float(self.yield_var.get()) if is_nuke else float(self.selected_missile.get("conventional_yield_kt", 0.001))

        # population is fetched on a background thread; _apply_population_update re-runs
        # this preview when it arrives. fetching it here would freeze the ui on slow networks.
        if not self.current_pop_info:
            return
        pop_info = self.current_pop_info

        density = float(pop_info.get("density_per_km2", 1500.0))

        impact = compute_impact_effects(
            missile=self.selected_missile,
            distance_km=self.current_distance_km,
            is_nuclear=is_nuke,
            nuclear_yield_kt=yield_kt,
            pop_density_per_km2=density,
        )

        res = {
            "success": True,
            "in_range": self.is_in_range,
            "distance_km": self.current_distance_km,
            "missile": self.selected_missile,
            "impact": impact,
            "population_info": pop_info,
        }
        self._render_results(res)

    def _render_results(self, res: Dict[str, Any]) -> None:
        for widget in self.results_container.winfo_children():
            widget.destroy()

        impact = res["impact"]
        pop_info = res["population_info"]
        missile = res["missile"]
        dist_km = res["distance_km"]

        # Card 1: Flight & Warhead Summary
        c1 = ttk.LabelFrame(self.results_container, text="Flight & Warhead Summary", padding=8)
        c1.pack(fill="x", pady=4)

        tk.Label(c1, text=f"{missile['name']} ({missile.get('country', '')})", font=FONT_BOLD, fg=COLOR_ACCENT, bg=COLOR_PANEL_BG).pack(anchor="w")
        tk.Label(c1, text=f"Warhead: {impact['warhead_mode']}", fg=COLOR_TEXT, bg=COLOR_PANEL_BG, font=FONT_NORMAL).pack(anchor="w")
        dist_txt = f"Distance: {dist_km:,.1f} km" if dist_km > 0 else "Distance: Select origin to calculate distance"
        tk.Label(c1, text=dist_txt, fg=COLOR_TEXT, bg=COLOR_PANEL_BG, font=FONT_NORMAL).pack(anchor="w")

        if dist_km > 0:
            top_txt = f"Top Speed: Mach {impact['top_speed_mach']} ({impact['top_speed_kmh']:,.0f} km/h) -> {impact['flight_time_top_min']} min"
            avg_txt = f"Avg Speed: Mach {impact['avg_speed_mach']} ({impact['avg_speed_kmh']:,.0f} km/h) -> {impact['flight_time_avg_min']} min"
        else:
            top_txt = f"Top Speed: Mach {impact['top_speed_mach']} ({impact['top_speed_kmh']:,.0f} km/h)"
            avg_txt = f"Avg Speed: Mach {impact['avg_speed_mach']} ({impact['avg_speed_kmh']:,.0f} km/h)"
        tk.Label(c1, text=top_txt, fg=COLOR_MUTED, bg=COLOR_PANEL_BG, font=FONT_SMALL).pack(anchor="w", pady=(2, 0))
        tk.Label(c1, text=avg_txt, fg=COLOR_MUTED, bg=COLOR_PANEL_BG, font=FONT_SMALL).pack(anchor="w")

        # Card 2: Target Population
        c2 = ttk.LabelFrame(self.results_container, text="Target Population", padding=8)
        c2.pack(fill="x", pady=4)

        tk.Label(c2, text=f"{pop_info.get('place_name', 'Target')}, {pop_info.get('country', '')}", font=FONT_BOLD, fg=COLOR_TEXT, bg=COLOR_PANEL_BG).pack(anchor="w")
        tk.Label(c2, text=f"Population: {pop_info.get('population', 0):,} people", fg=COLOR_TEXT, bg=COLOR_PANEL_BG, font=FONT_NORMAL).pack(anchor="w")
        tk.Label(c2, text=f"Density: {pop_info.get('density_per_km2', 0):,.0f} people/km2", fg=COLOR_TEXT, bg=COLOR_PANEL_BG, font=FONT_NORMAL).pack(anchor="w")
        tk.Label(c2, text=f"Source: {pop_info.get('data_source', 'Open Database')}", fg=COLOR_MUTED, bg=COLOR_PANEL_BG, font=FONT_SMALL).pack(anchor="w", pady=(2, 0))

        # Card 3: Blast & Thermal Radii
        c3 = ttk.LabelFrame(self.results_container, text="Blast & Thermal Radii", padding=8)
        c3.pack(fill="x", pady=4)

        if "blast_pattern" in impact:
            pat_lbl = tk.Label(
                c3,
                text=f"Pattern: {impact['blast_pattern']}",
                fg=COLOR_ACCENT,
                bg=COLOR_PANEL_BG,
                font=FONT_SMALL,
                wraplength=px(340),
                justify="left",
            )
            pat_lbl.pack(fill="x", pady=(0, 4), anchor="w")

        r = impact["radii_km"]
        radii_items = [
            ("Fireball Vaporization", f"{r['fireball_km']:.3f} km ({r['fireball_km'] * 1000:.0f} m)", "#fde047"),
            ("Heavy Blast (20 psi)", f"{r['heavy_blast_20psi_km']:.3f} km", "#dc2626"),
            ("Moderate Blast (5 psi)", f"{r['moderate_blast_5psi_km']:.3f} km", "#ea580c"),
            ("Thermal Radiation (3rd-deg)", f"{r['thermal_3rd_deg_km']:.3f} km", "#f59e0b"),
            ("Light Blast (1 psi)", f"{r['light_blast_1psi_km']:.3f} km", "#eab308"),
        ]
        for name, val, color in radii_items:
            row = tk.Frame(c3, bg=COLOR_PANEL_BG)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=f"* {name}:", fg=color, bg=COLOR_PANEL_BG, font=FONT_SMALL).pack(side="left")
            tk.Label(row, text=val, fg=COLOR_TEXT, bg=COLOR_PANEL_BG, font=FONT_SMALL).pack(side="right")

        # Card 4: Casualty & Structural Damage
        c4 = ttk.LabelFrame(self.results_container, text="Casualties & Structural Damage", padding=8)
        c4.pack(fill="x", pady=4)

        est = impact["estimates"]
        total_exp = max(est.get("total_exposed", 1), 1)
        fatalities = est.get("estimated_fatalities", 0)
        injuries = est.get("estimated_injuries", 0)
        structures = est.get("structures_destroyed", 0)

        tk.Label(c4, text=f"Total Exposed Population: {total_exp:,}", fg=COLOR_TEXT, bg=COLOR_PANEL_BG, font=FONT_BOLD).pack(anchor="w")

        # helper for progress bar
        def _add_bar(parent_frame, label_text, count, color):
            tk.Label(parent_frame, text=f"{label_text}: {count:,}", fg=color, bg=COLOR_PANEL_BG, font=FONT_NORMAL).pack(anchor="w", pady=(4, 1))
            bar_canvas = tk.Canvas(parent_frame, height=8, bg=COLOR_BORDER, highlightthickness=0)
            bar_canvas.pack(fill="x", pady=(0, 2))
            ratio = min(max(count / total_exp, 0.0), 1.0)
            bar_width = int(ratio * px(320))
            if bar_width > 0:
                bar_canvas.create_rectangle(0, 0, bar_width, 8, fill=color, outline="")

        _add_bar(c4, "Estimated Fatalities", fatalities, COLOR_RED)
        _add_bar(c4, "Estimated Injuries", injuries, COLOR_AMBER)
        tk.Label(c4, text=f"Structures Destroyed: {structures:,} buildings", fg=COLOR_TEXT, bg=COLOR_PANEL_BG, font=FONT_NORMAL).pack(anchor="w", pady=(4, 2))

        # Card 5: Missile Reference Facts
        c5 = ttk.LabelFrame(self.results_container, text="Missile Specifications & Facts", padding=8)
        c5.pack(fill="x", pady=4)

        notes = missile.get("facts", [])
        if isinstance(notes, list):
            for note in notes[:4]:
                tk.Label(c5, text=f"* {note}", fg=COLOR_MUTED, bg=COLOR_PANEL_BG, font=FONT_SMALL, wraplength=px(320), justify="left").pack(anchor="w", pady=1)

        source_url = missile.get("source_url", "")
        if source_url:
            tk.Label(c5, text=f"Source: {source_url}", fg=COLOR_ACCENT, bg=COLOR_PANEL_BG, font=FONT_SMALL, wraplength=px(320), justify="left").pack(anchor="w", pady=(4, 0))

    def on_viewport_resize(self, event: tk.Event) -> None:
        self.current_width = event.width
        self.current_height = event.height
        if self.child_hwnd and sys.platform == "win32":
            ctypes.windll.user32.MoveWindow(
                wintypes.HWND(self.child_hwnd), 0, 0, event.width, event.height, True
            )

    def open_missile_catalog(self) -> None:
        MissileCatalogDialog(self, self.missiles, on_select=self._on_catalog_missile_selected)

    def open_missile_catalog_filter(self, country: str) -> None:
        dialog = MissileCatalogDialog(self, self.missiles, on_select=self._on_catalog_missile_selected)
        dialog.search_var.set(country)

    def _on_catalog_missile_selected(self, missile: Dict[str, Any]) -> None:
        self._select_missile_by_id(missile["id"])

    def open_scenarios_dialog(self) -> None:
        ScenarioManagerDialog(self, self.db, on_load=self.load_scenario)

    def open_save_dialog(self) -> None:
        if not self.origin_candidate or not self.dest_candidate:
            messagebox.showwarning("Save Scenario", "Please select both an origin and target city first.", parent=self)
            return
        if not self.selected_missile:
            messagebox.showwarning("Save Scenario", "Please select a missile first.", parent=self)
            return

        name = simpledialog.askstring("Save Scenario", "Enter scenario name:", parent=self)
        if name and name.strip():
            m_id = self.selected_missile.get("id", "agni_v") if self.selected_missile else "agni_v"
            is_nuke = bool(self.is_nuclear_var.get())
            y_kt = float(self.yield_var.get()) if is_nuke else float(self.selected_missile.get("conventional_yield_kt", 0.001))

            scen = Scenario(
                scenario_name=name.strip(),
                origin_city_label=self.origin_candidate.label,
                origin_longitude=self.origin_candidate.longitude,
                origin_latitude=self.origin_candidate.latitude,
                destination_city_label=self.dest_candidate.label,
                destination_longitude=self.dest_candidate.longitude,
                destination_latitude=self.dest_candidate.latitude,
                missile_id=m_id,
                params=json.dumps({"is_nuclear": is_nuke, "yield_kt": y_kt}),
            )
            try:
                sid = self.db.save_scenario(scen)
                messagebox.showinfo("Saved", f"Scenario '{name.strip()}' saved (ID #{sid})!", parent=self)
            except Exception as err:
                messagebox.showerror("Error", f"Could not save scenario: {err}", parent=self)

    def load_scenario(self, scen: Scenario) -> None:
        orig = PlaceCandidate(
            label=scen.origin_city_label,
            longitude=scen.origin_longitude,
            latitude=scen.origin_latitude,
            provider_place_id="scenario-origin",
        )
        dest = PlaceCandidate(
            label=scen.destination_city_label,
            longitude=scen.destination_longitude,
            latitude=scen.destination_latitude,
            provider_place_id="scenario-dest",
        )
        self.origin_candidate = orig
        self.origin_panel.set_place(orig)

        self.dest_candidate = dest
        self.dest_panel.set_place(dest)

        if scen.missile_id:
            self._select_missile_by_id(scen.missile_id)

        try:
            p = json.loads(scen.params)
            if "is_nuclear" in p:
                self.is_nuclear_var.set(bool(p["is_nuclear"]))
            if "yield_kt" in p:
                self.yield_var.set(str(int(p["yield_kt"]) if p["yield_kt"] == int(p["yield_kt"]) else p["yield_kt"]))
        except Exception:
            pass

        self._update_warhead_ui_state()
        self._update_range_and_pins()

        # fetch population on daemon thread
        def _worker():
            pop = self.api.get_population(dest.longitude, dest.latitude, dest.label)
            self.after(0, lambda: self._apply_population_update(pop))

        threading.Thread(target=_worker, daemon=True).start()

    def open_physics_info(self) -> None:
        PhysicsInfoDialog(self)

    def reset_all(self) -> None:
        self.origin_panel.clear_selection()
        self.dest_panel.clear_selection()
        self.origin_candidate = None
        self.dest_candidate = None
        self.current_pop_info = None
        self.target_pop_var.set("Population: -- | Density: --")
        self._update_range_and_pins()
        if self.bridge:
            self.bridge.update_state(
                origin=None,
                destination=None,
                launched=False,
                impact=None,
                fly_to={"lon": 0.0, "lat": 20.0, "height": 18000000.0, "fly_id": self._next_fly_id()},
            )
        self._set_pick_mode("origin")
        self.status_var.set("Cleared. Click the globe or search to place the launch site.")
        for widget in self.results_container.winfo_children():
            widget.destroy()
        self.placeholder_lbl = tk.Label(
            self.results_container,
            text="Select an origin, target, and missile on the left, then click Simulate Launch to view blast radii and casualty estimates.",
            fg=COLOR_MUTED,
            bg=COLOR_MAIN_BG,
            font=FONT_NORMAL,
            wraplength=px(340),
            justify="center",
            padx=12,
            pady=40,
        )
        self.placeholder_lbl.pack(fill="both", expand=True)

    def on_closing(self) -> None:
        try:
            self.destroy()
        except Exception:
            pass
        if self.on_exit:
            self.on_exit()
        os._exit(0)


def launch_simulator_app() -> None:
    """starts bridge server and launches tkinter with embedded pywebview"""
    app_ref: Dict[str, Any] = {"app": None}
    ready_event = threading.Event()

    def on_globe_pick_callback(role: str, lon: float, lat: float):
        if app_ref["app"]:
            app_ref["app"].on_globe_pick(role, lon, lat)

    enable_dpi_awareness()

    # use dynamic os assigned port (port=0)
    bridge = GlobeBridgeServer(on_globe_pick=on_globe_pick_callback)
    globe_url = bridge.start()
    api = bridge.api

    def run_tkinter():
        app = MissileSimulatorApp(globe_url, api, bridge)
        app_ref["app"] = app
        ready_event.set()
        app.mainloop()

    # tkinter runs on dedicated thread so webview can use the main thread
    t = threading.Thread(target=run_tkinter, daemon=True)
    t.start()
    ready_event.wait()
    app = app_ref["app"]

    win = webview.create_window(
        title="Missile Simulator Globe Viewport",
        url=globe_url,
        width=app.current_width,
        height=app.current_height,
        text_select=False,
    )

    def on_shown():
        if sys.platform == "win32" and app and app.tk_hwnd:
            try:
                child = win.native.Handle.ToInt64()
                u32 = ctypes.windll.user32
                u32.SetParent(wintypes.HWND(child), wintypes.HWND(app.tk_hwnd))
                gwl_style = -16
                ws_child = 0x40000000
                ws_popup = 0x80000000
                ws_caption = 0x00C00000
                ws_thickframe = 0x00040000
                style = u32.GetWindowLongW(child, gwl_style)
                style &= ~(ws_popup | ws_caption | ws_thickframe)
                style |= ws_child
                u32.SetWindowLongW(child, gwl_style, style)
                u32.MoveWindow(wintypes.HWND(child), 0, 0, app.current_width, app.current_height, True)
                app.child_hwnd = child
            except OSError as err:
                print(f"native embedding notice: {err}")

    win.events.shown += on_shown
    webview.start(debug=False)
