"""Hidden Windows worker: no WebView, no GUI event loop on the USB sender."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if __name__ == '__main__':
    from goggles_bridge.app.windows.worker import main
    raise SystemExit(main())
