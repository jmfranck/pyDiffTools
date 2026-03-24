import os
import sys
from pathlib import Path

# Ensure Jupyter uses the platformdirs path to avoid deprecation warnings.
os.environ.setdefault("JUPYTER_PLATFORM_DIRS", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
