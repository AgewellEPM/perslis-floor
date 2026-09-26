#!/usr/bin/env python3
"""Start the Perslis symbolic-floor MCP server from any working directory.

    python3 /path/to/floor-serve.py --data /path/to/your/data --tools /path/to/tools

MCP clients launch servers from an unspecified folder; this file puts its own
folder on the import path first, so the runtime next to it is always found.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from floor_runtime.serve import main  # noqa: E402

raise SystemExit(main())
