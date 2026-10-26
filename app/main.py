"""
Real-World Missile Impact Simulator
===================================
A desktop application built mandatorily with Tkinter as the primary GUI framework,
embedding a high-performance PyView (pywebview) 3D CesiumJS Earth geospatial engine.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.ui.main_window import launch_simulator_app


def main() -> None:
    """Launches the Tkinter Master Application embedding the PyView 3D Earth view."""
    launch_simulator_app()


if __name__ == "__main__":
    main()
