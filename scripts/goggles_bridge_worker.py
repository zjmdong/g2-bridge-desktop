"""Entry point for the optional isolated Windows capture worker."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from goggles_bridge.app.windows.worker import main

if __name__ == '__main__':
    raise SystemExit(main())
