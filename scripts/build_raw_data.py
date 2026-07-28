"""Compatibility wrapper; prefer ``uv run awm-sources all``."""

from awm_exposure.source_cli import main


raise SystemExit(main())
