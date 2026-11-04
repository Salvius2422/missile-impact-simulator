import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable, List, Optional
from app.data.database import PlaceCandidate
from app.services.geocoding import GeocodingService, GeocodingError

COLOR_PANEL_BG = "#0a0a0a"
COLOR_TEXT = "#ededed"
COLOR_MUTED = "#8a8a8a"
FONT_BOLD = ("Segoe UI", 9, "bold")
FONT_NORMAL = ("Segoe UI", 9)


class CitySearchPanel(ttk.LabelFrame):
    """search panel with city lookup and coordinate readout"""

    def __init__(
        self,
        parent: tk.Widget,
        title: str,
        geocoding_service: GeocodingService,
        on_selection_changed: Optional[Callable[[Optional[PlaceCandidate]], None]] = None,
    ):
        super().__init__(parent, text=title, padding=8)
        self.geocoding_service = geocoding_service
        self.on_selection_changed = on_selection_changed
        self.candidates: List[PlaceCandidate] = []
        self.selected_candidate: Optional[PlaceCandidate] = None
        self._build_ui()

    def _build_ui(self) -> None:
        self.columnconfigure(1, weight=1)

        ttk.Label(self, text="Search:").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=3)
        self.query_var = tk.StringVar()
        self.search_entry = ttk.Entry(self, textvariable=self.query_var)
        self.search_entry.grid(row=0, column=1, sticky="ew", pady=3)
        self.search_entry.bind("<Return>", lambda _event: self.perform_search())

        self.search_btn = ttk.Button(self, text="Search", command=self.perform_search)
        self.search_btn.grid(row=0, column=2, padx=(6, 0), pady=3)

        ttk.Label(self, text="Matches:").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=3)
        self.candidate_combo = ttk.Combobox(self, state="readonly")
        self.candidate_combo.grid(row=1, column=1, columnspan=2, sticky="ew", pady=3)
        self.candidate_combo.bind("<<ComboboxSelected>>", self._on_candidate_picked)

        self.summary_var = tk.StringVar(value="Selected: None")
        ttk.Label(self, textvariable=self.summary_var, font=FONT_BOLD).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(4, 2)
        )

        self.coords_var = tk.StringVar(value="Lon: --  Lat: --")
        ttk.Label(self, textvariable=self.coords_var, foreground=COLOR_MUTED, font=FONT_NORMAL).grid(
            row=3, column=0, columnspan=3, sticky="w"
        )

    def perform_search(self) -> None:
        query = self.query_var.get().strip()
        if not query:
            messagebox.showwarning("Search", "Please type a city name first.", parent=self)
            return

        self.search_btn.config(state="disabled")
        self.summary_var.set("Searching...")

        def _worker():
            try:
                results = self.geocoding_service.search_city(query)
                err = None
            except GeocodingError as e:
                results = []
                err = str(e)
            except Exception as e:
                results = []
                err = f"Search failed: {e}"
            self.after(0, lambda: self._on_search_complete(query, results, err))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_search_complete(self, query: str, results: List[PlaceCandidate], error: Optional[str]) -> None:
        self.search_btn.config(state="normal")
        if error:
            self.summary_var.set("Search error")
            messagebox.showwarning("Search Error", error, parent=self)
            return

        if not results:
            self.candidates = []
            self.candidate_combo["values"] = []
            self.candidate_combo.set("")
            self.clear_selection(keep_query=True)
            messagebox.showinfo("No Results", f"No cities found for '{query}'.", parent=self)
            return

        self.candidates = results
        labels = [f"{c.label} [{c.longitude:.4f}, {c.latitude:.4f}]" for c in results]
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
        self.coords_var.set(f"Lon: {candidate.longitude:.4f}  Lat: {candidate.latitude:.4f} ({candidate.attribution})")
        if self.on_selection_changed:
            self.on_selection_changed(candidate)

    def set_place(self, candidate: PlaceCandidate) -> None:
        """updates the panel when a pin is clicked or scenario loaded"""
        self.candidates = [candidate]
        self.selected_candidate = candidate
        self.query_var.set(candidate.label)
        label_text = f"{candidate.label} [{candidate.longitude:.4f}, {candidate.latitude:.4f}]"
        self.candidate_combo["values"] = [label_text]
        self.candidate_combo.current(0)
        self.summary_var.set(f"Selected: {candidate.label}")
        self.coords_var.set(f"Lon: {candidate.longitude:.4f}  Lat: {candidate.latitude:.4f}")

    def clear_selection(self, keep_query: bool = False) -> None:
        if not keep_query:
            self.query_var.set("")
        self.candidates = []
        self.selected_candidate = None
        self.candidate_combo["values"] = []
        self.candidate_combo.set("")
        self.summary_var.set("Selected: None")
        self.coords_var.set("Lon: --  Lat: --")
        if self.on_selection_changed:
            self.on_selection_changed(None)
