# Real-World Missile Impact Simulator

A desktop application developed mandatorily using **Python Tkinter** as the core GUI framework, seamlessly embedding a high-performance **PyView (`pywebview`)** and **CesiumJS 3D Earth** geospatial viewport. The application delivers real-time 3D orbital trajectory simulation, Glasstone-Dolan nuclear and conventional blast physics assessments, live public urban population exposure metrics, and local SQLite scenario management.

---

## Architecture & Technical Frameworks

1. **Mandatory Core Desktop GUI (Tkinter)**:
   - Built on Python's native `tkinter` framework as the primary application window.
   - **Tkinter Native Menu Bar**: Full access to Scenario Persistence (`Ctrl+S`, `Ctrl+O`), 58-Missile Technical Catalog, Blast Physics Documentation, and System Controls.
   - **Tkinter Command & Navigation Bar**: Quick-access controls for loading scenarios, saving missions, viewing missile inventories, and resetting simulation states.
   - **Tkinter Viewport Container**: Embeds the hardware-accelerated 3D CesiumJS Earth viewport directly inside a native Tkinter frame with dynamic resizing.
   - **Tkinter Live Telemetry Status Bar**: Displays real-time engine status, database connection, Wi-Fi geocoding status, and active coordinates.
   - **Interactive Tkinter Dialogs**:
     - `MissileCatalogDialog`: Searchable `ttk.Treeview` detailing all 58 global missile systems.
     - `ScenarioManagerDialog`: SQLite mission explorer with load, inspect, and delete operations.
     - `PhysicsInfoDialog`: Formal documentation of Glasstone-Dolan cube-root scaling equations.

2. **Embedded 3D Geospatial Engine (PyView & CesiumJS)**:
   - Embedded directly inside the Tkinter application container—no external browser tabs or detached HTML viewers.
   - Complete on-map HUD command overlay with real-time range envelope calculation, Glasstone-Dolan blast rings, and animated post-impact assessment popups.

3. **58-Missile Technical Database**:
   - Comprehensive inventory of 58 strategic, intermediate, and tactical missile systems across 10 major global powers (India, United States, Russia, China, France, United Kingdom, Israel, Iran, South Korea, North Korea).
   - Covers ICBMs, SLBMs, IRBMs, MRBMs, SRBMs, Hypersonic Glide Vehicles (HGV), and Cruise Missiles.

4. **Glasstone-Dolan Impact Physics & Atmospheric Scaling**:
   - Computes concentric hazard radii based on cube-root scaling:
     - **Fireball Vaporization Zone** ($~100\%$ lethality)
     - **Heavy Blast Damage Zone** ($20\text{ psi}$ complete destruction)
     - **Moderate Blast Damage Zone** ($5\text{ psi}$ structural collapse)
     - **Thermal Radiation Zone** ($3\text{rd}$-degree flash burns)
     - **Light Blast Damage Zone** ($1\text{ psi}$ shattered glass)

5. **Live Public Population & Wi-Fi Geocoding Engine**:
   - Live query over Wi-Fi against OpenStreetMap Nominatim and OpenDataSoft / GeoNames datasets without requiring proprietary API tokens.
   - Automatic real-world urban population and density retrieval cached in local SQLite database.

---

## How to Run

1. **Launch the Tkinter Desktop Simulator**:
   ```powershell
   python app/main.py
   ```
   *(Or double-click `run_simulator.bat`)*

2. **Run Unit Test Suite**:
   ```powershell
   python -m unittest discover -s tests -p "test_*.py"
   ```

---

## Directory Structure

```
├── .env.example                # Optional configuration
├── requirements.txt            # Python dependencies (pywebview, requests, etc.)
├── run_simulator.bat           # 1-click desktop launcher
├── README.md                   # Technical documentation
├── app/
│   ├── main.py                 # Primary entry point (boots Tkinter application)
│   ├── ui/
│   │   ├── main_window.py      # Tkinter Master Application & embedded PyView viewport
│   │   └── city_search.py      # Reusable Tkinter search and autocomplete panel
│   ├── services/
│   │   ├── webview_api.py      # Python API bridge exposed to the 3D viewport
│   │   ├── bridge_server.py    # Local HTTP server & REST fallback
│   │   ├── impact_physics.py   # Glasstone-Dolan blast equations & casualties
│   │   ├── distance_service.py # Haversine great-circle calculation
│   │   ├── mapbox_geocoding.py # Forward/reverse geocoding (OSM / GeoNames)
│   │   └── population_service.py# Public population database engine with SQLite caching
│   ├── data/
│   │   ├── models.py           # Dataclasses & schemas
│   │   ├── database.py         # SQLite scenario persistence
│   │   └── reference_data.json # 58-Missile technical database
│   └── visualization/
│       └── globe/
│           └── index.html      # 3D CesiumJS Earth globe with on-map HUD overlays
└── tests/
    └── test_all.py             # 8-test unit verification suite
```
