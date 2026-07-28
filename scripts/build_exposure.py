#!/usr/bin/env python3
"""Run the package CLI without requiring an editable installation."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from awm_exposure.cli import main  # noqa: E402

raise SystemExit(main())

