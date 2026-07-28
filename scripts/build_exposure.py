"""Compatibility wrapper; prefer ``uv run awm-exposure``."""

from awm_exposure.cli import main

raise SystemExit(main())
