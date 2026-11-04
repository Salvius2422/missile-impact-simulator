# Missile Impact Simulator

A Python desktop project combining a Tkinter GUI with an embedded CesiumJS 3D Earth map inside pywebview. It lets you select an origin and target city anywhere in the world, pick a missile system, and calculate great-circle trajectory distance, flight times, and blast effects using the Glasstone-Dolan scaling laws.

---

## Layout and Features

1. **Left Panel: Mission Controls (Tkinter)**
   - City search for origin (launch site) and target (detonation site) via OpenStreetMap Nominatim and GeoNames datasets.
   - Interactive map-click buttons to place or drag pins directly on the 3D globe.
   - Filterable catalog of 58 missile systems from 10 countries (India, United States, Russia, China, France, United Kingdom, Israel, Iran, South Korea, North Korea).
   - Speed metrics: displays both top speed and estimated average cruising speed (Mach and km/h).
   - Warhead options: nuclear yield selection (1 to 1,000 kt) or conventional mode.
   - Live range check that enables the launch button only when the target is within missile range.

2. **Center Viewport: 3D Earth Map (pywebview + CesiumJS)**
   - Renders Esri satellite imagery combined with an Esri reference layer for country boundaries and place names.
   - Fixed camera zoom limits: minimum zoom distance of 100 meters, maximum of 25,000 km.
   - Renders the launch site pin, target pin, maximum range circle, parabolic trajectory arc, and concentric blast damage rings.
   - Differentiates between dragging to rotate the globe and stationary clicking to drop or move a pin.

3. **Right Panel: Post-Impact Assessment (Tkinter)**
   - Flight summary with top speed, average speed, and flight times in minutes.
   - Target population and density resolved from public datasets and cached in SQLite.
   - Five concentric blast radii calculated from Glasstone-Dolan (1977) equations.
   - Casualty estimations (fatalities, injuries, structures destroyed) with visual ratio bars.
   - Missile technical notes and reference links.

---

## Blast Physics Model (Glasstone & Dolan, 1977)

Concentric hazard radii scale with explosive yield `Y` (in kilotons TNT equivalent):

- **Fireball Radius**: `r_fireball = 0.09 * Y^0.40` km
- **Heavy Blast (20 psi)**: `r_20psi = 0.28 * Y^(1/3)` km (98% fatalities, 99% structures destroyed)
- **Moderate Blast (5 psi)**: `r_5psi = 0.70 * Y^(1/3)` km (50% fatalities, 75% structures destroyed)
- **Thermal Radiation (3rd-deg burns)**: `r_thermal = 1.20 * Y^0.41` km (nuclear) or `0.35 * Y^(1/3)` km (conventional)
- **Light Blast (1 psi)**: `r_1psi = 1.90 * Y^(1/3)` km (5% fatalities, 35% injuries)

Flight time is computed from great-circle distance using:
- **Top Speed**: peak terminal Mach (`Mach * 1225` km/h)
- **Average Speed**: `0.65 * top_speed` for ballistic missiles (Mach >= 5), `0.85 * top_speed` for cruise/tactical missiles (Mach < 5)

---

## How to Run

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the desktop application**:
   ```bash
   python app/main.py
   ```
   *(Or run `run_simulator.bat` on Windows)*

3. **Run unit tests**:
   ```bash
   python -m unittest discover -s tests -p "test_*.py" -v
   ```

---

## Project Structure

```
├── requirements.txt            # dependencies (requests, pywebview)
├── run_simulator.bat           # batch launcher script
├── scenarios.db                # local sqlite scenario and population cache
├── README.md                   # project documentation
├── app/
│   ├── main.py                 # application entry point
│   ├── ui/
│   │   ├── main_window.py      # tkinter 3-column interface and pywebview embedding
│   │   └── city_search.py      # city search and autocomplete panel
│   ├── services/
│   │   ├── bridge_server.py    # simulator api + local http server linking tkinter and the globe
│   │   ├── impact_physics.py   # great-circle distance, glasstone-dolan blast scaling, speed stats
│   │   └── geocoding.py        # city search, reverse geocoding, population lookup with sqlite cache
│   ├── data/
│   │   ├── database.py         # place/scenario dataclasses and sqlite scenario storage
│   │   └── reference_data.json # 58 missile systems dataset
│   └── visualization/
│       └── globe/
│           └── index.html      # cesiumjs 3d map viewport
└── tests/
    └── test_all.py             # test suite covering database, physics, and api
```
