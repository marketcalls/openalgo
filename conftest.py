"""Root conftest.py — ensures project root is on sys.path for test imports."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
