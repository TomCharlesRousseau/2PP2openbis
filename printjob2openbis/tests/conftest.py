"""
pytest setup: tests never read the private ``config/settings.json``.

They use the tracked ``settings.json.example`` (placeholder values), so the
suite runs in a fresh clone and cannot depend on real instance data.
"""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config import settings  # noqa: E402

settings._CONFIG_FILE = _PROJECT_ROOT / "config" / "settings.json.example"
settings.Settings._instance = None
