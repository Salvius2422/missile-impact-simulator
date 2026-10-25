import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable, List, Optional
from app.data.models import PlaceCandidate
from app.services.mapbox_geocoding import MapboxGeocodingService, GeocodingError


class CitySearchPanel(ttk.LabelFrame):
    """
    Reusable Tkinter component for searching a city via Mapbox, selecting from
    candidate matches, and displaying validated [longitude, latitude] coordinates.
    """

    def __init__(
        self,
        parent: tk.Widget,
        title: str,
        geocoding_service: MapboxGeocodingService,
        on_selection_changed: Optional[Callable[[Optional[PlaceCandidate]], None]] = None,
    ):
        super().__init__(parent, text=title, padding=10)
        self.geocoding_service = geocoding_service
        self.on_selection_changed = on_selection_changed
        self.candidates: List[PlaceCandidate] = []
        self.selected_candidate: Optional[PlaceCandidate] = None
        self._build_ui()

    def _build_ui(self) -> None:
        self.columnconfigure(1, weight=1)

        ttk.Label(self, text="Search City:").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=4)
        self.query_var = tk.StringVar()
        self.search_entry = ttk.Entry(self, textvariable=self.query_var)
        self.search_entry.grid(row=0, column=1, sticky="ew", pady=4)
        self.search_entry.bind("<Return>", lambda _event: self.perform_search())

        self.search_btn = ttk.Button(self, text="Search", command=self.perform_search)
        self.search_btn.grid(row=0, column=2, padx=(6, 0), pady=4)

        ttk.Label(self, text="Matches:").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=4)
        self.candidate_combo = ttk.Combobox(self, state="readonly")
        self.candidate_combo.grid(row=1, column=1, columnspan=2, sticky="ew", pady=4)
        self.candidate_combo.bind("<<ComboboxSelected>>", self._on_candidate_picked)

        self.summary_var = tk.StringVar(value="Selected: None")
        ttk.Label(self, textvariable=self.summary_var, font=("Segoe UI", 9, "bold")).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(6, 2)
        )

        self.coords_var = tk.StringVar(value="Longitude: -- | Latitude: --")
        ttk.Label(self, textvariable=self.coords_var, foreground="#333333").grid(
            row=3, column=0, columnspan=3, sticky="w"
        )

    def perform_search(self) -> None:
        query = self.query_var.get()
        try:
            results = self.geocoding_service.search_city(query)
        except GeocodingError as err:
            messagebox.showwarning("Search Error", str(err), parent=self)
            return

        if not results:
            self.candidates = []
            self.candidate_combo["values"] = []
            self.candidate_combo.set("")
            self.clear_selection(keep_query=True)
            messagebox.showinfo("No Results", f"No matching cities found for '{query.strip()}'.", parent=self)
            return

        self.candidates = results
        labels = [f"{c.label}  [{c.longitude:.4f}, {c.latitude:.4f}]" for c in results]
        self.candidate_combo["values"] = labels
        self.candidate_combo.current(0)
        self._apply_selection(0)

    def _on_candidate_picked(self, _event: tk.Event) -> None:
        idx = self.candidate_combo.current()
        if 0 <= idx < len(self.candidates):
            self._apply_selection(idx)

    def _apply_selection(self, index: int) -> None:
        candidate = self.candidates[index]
        self.selected_candidate = candidate
        self.summary_var.set(f"Selected: {candidate.label}")
        self.coords_var.set(
            f"Longitude: {candidate.longitude:.5f}°  |  Latitude: {candidate.latitude:.5f}°  ({candidate.attribution})"
        )
        if self.on_selection_changed:
            self.on_selection_changed(candidate)

    def clear_selection(self, keep_query: bool = False) -> None:
        if not keep_query:
            self.query_var.set("")
        self.candidates = []
        self.selected_candidate = None
        self.candidate_combo["values"] = []
        self.candidate_combo.set("")
        self.summary_var.set("Selected: None")
        self.coords_var.set("Longitude: -- | Latitude: --")
        if self.on_selection_changed:
            self.on_selection_changed(None)
