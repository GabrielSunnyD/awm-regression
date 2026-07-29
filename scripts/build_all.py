"""Compatibility wrapper; prefer ``uv run awm-build``."""

from awm_exposure.project_cli import main


raise SystemExit(main())
