import sys
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.bridge_server import GlobeBridgeServer
from app.services.webview_api import SimulatorApi


def launch_pywebview() -> None:
    """Launches the map-centric application using PyView (pywebview)."""
    import webview

    bridge = GlobeBridgeServer(port=8765)
    globe_url = bridge.start()
    api = bridge.api

    window = webview.create_window(
        title="Real-World Missile Impact Simulator — 3D Earth & Impact Assessment",
        url=globe_url,
        js_api=api,
        width=1380,
        height=880,
        min_size=(1080, 720),
        text_select=False,
    )
    webview.start(debug=False)


def launch_tkinter() -> None:
    """Launches the Tkinter control panel."""
    from app.ui.main_window import MainWindow

    app = MainWindow()
    app.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Real-World Missile Impact Simulator")
    parser.add_argument("--tkinter", action="store_true", help="Launch using legacy Tkinter panel")
    args, _ = parser.parse_known_args()

    if args.tkinter:
        launch_tkinter()
    else:
        try:
            launch_pywebview()
        except ImportError:
            print("pywebview not installed, falling back to Tkinter...")
            launch_tkinter()


if __name__ == "__main__":
    main()
