# Real-World Missile Impact Simulator

An interactive, map-centric desktop application powered by **PyView (`pywebview`)** and **CesiumJS 3D Earth**. The 3D globe fills the entire application window, with all control panels, configuration options, post-impact assessments, and casualty breakdown charts rendered as floating glassmorphism overlays and pop-up modal dialogs directly on the map.

---

## Key Features

1. **Integrated Map-Centric Application (Powered by PyView)**:
   - The map opens **directly inside the native desktop application window**—no external browser tabs, no separate web popups, and no disconnected HTML files.
   - All controls, search bars, missile selectors, and warhead toggles are floating overlays right on the 3D globe.
2. **Interactive 3D Pin Picking & Dragging**:
   - Click anywhere on the 3D Earth or drag the **Origin (Green)** and **Target (Red)** pins across continents with real-time coordinate updates and reverse geocoding.
3. **Maximum Range Demarcation Circle & Launch Locking**:
   - A cyan geodesic circle demarcates the active missile's maximum range.
   - Selecting a target outside this limit triggers an **"OUT OF RANGE"** warning and locks the Launch button.
4. **Real-World Missiles Included**:
   - **Agni-V** (India, ICBM, 5,500 km, Mach 24)
   - **Agni-IV** (India, IRBM, 4,000 km, Mach 7)
   - **BrahMos Block-III / ER** (India / Russia, Supersonic Cruise, 800 km, Mach 2.8)
   - **LGM-30G Minuteman III** (USA, ICBM, 13,000 km, Mach 23)
   - **AGM-114 Hellfire** (USA, Tactical, 11 km, Mach 1.3)
5. **Pop-Up Modal Post-Impact Assessment**:
   - Launches an animated pop-up modal box right over the map displaying:
     - **Concentric Blast Radii** (Glasstone-Dolan cube-root scaling): Fireball (vaporization), 20 psi heavy blast, 5 psi moderate collapse, 3rd-degree thermal radiation, and 1 psi light damage.
     - **Casualties & Structural Damage**: Estimated fatalities, injuries, exposed population, and destroyed buildings based on urban density benchmarks.
     - **Interactive Casualty Bar Chart** with animated fill bars.
     - **Missile Facts & Source References**.
   - **3D Impact Zone View**: Concentric glowing rings rendered on Earth, with smooth camera fly-to animation.
6. **Local Scenario Persistence**:
   - Save and reload simulation scenarios to local SQLite database directly from the on-map modal dialogs.
7. **Tkinter Compatibility Mode**:
   - Can also be run with the traditional Tkinter control panel using `python app/main.py --tkinter`.

---

## How to Run

1. **Launch the simulator**:
   ```powershell
   python app/main.py
   ```
   *(Or double-click `run_simulator.bat`)*

2. **Tkinter fallback (optional)**:
   ```powershell
   python app/main.py --tkinter
   ```

---

## Directory Structure

```
├── .env                        # Mapbox API token (optional)
├── requirements.txt            # Python dependencies (pywebview, requests, etc.)
├── run_simulator.bat           # 1-click desktop launcher
├── README.md
├── app/
│   ├── main.py                 # Primary entry point (launches PyView map)
│   ├── services/
│   │   ├── webview_api.py      # Python API bridge exposed to pywebview
│   │   ├── bridge_server.py    # Local HTTP server & REST fallback
│   │   ├── impact_physics.py   # Glasstone-Dolan blast equations & casualties
│   │   ├── distance_service.py # Haversine great-circle calculation
│   │   └── mapbox_geocoding.py # Forward & reverse geocoding with offline catalog
│   ├── data/
│   │   ├── models.py           # Data classes
│   │   ├── database.py         # SQLite scenario persistence
│   │   └── reference_data.json # Missile technical specifications
│   ├── ui/
│   │   ├── main_window.py      # Tkinter control panel (compatibility mode)
│   │   └── city_search.py      # Reusable Tkinter search widget
│   └── visualization/
│       └── globe/
│           └── index.html      # Full-screen 3D CesiumJS globe with overlays
└── tests/
    └── test_all.py             # Unit test suite
```
