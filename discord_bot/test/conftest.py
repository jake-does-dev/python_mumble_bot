"""Make the `python_discord_bot` package importable when pytest is run from the
discord_bot directory (mirrors the mumble_bot test setup)."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
