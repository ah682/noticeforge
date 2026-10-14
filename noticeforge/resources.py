"""Locate read-only assets in either a source checkout or an installed wheel."""

from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent
_BUNDLED_DATA = _PACKAGE_DIR / "data"
DATA_ROOT = _BUNDLED_DATA if _BUNDLED_DATA.is_dir() else _PACKAGE_DIR.parent
