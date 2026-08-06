"""Compatibility wrapper; prefer ``uv run awm-ted``."""

from awm_exposure.ted_cli import main


raise SystemExit(main())
