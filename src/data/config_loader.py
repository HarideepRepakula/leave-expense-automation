"""Load the generator's YAML configuration (docs/03 section 5: config/*.yaml, each marked illustrative)."""
from __future__ import annotations

from pathlib import Path

import yaml

CONFIG_FILES = ("generation", "organisation", "leave_policies", "expense_policies", "approval_rules", "calendar")


def load_config(config_dir: Path) -> dict[str, dict]:
    cfg: dict[str, dict] = {}
    for name in CONFIG_FILES:
        path = config_dir / f"{name}.yaml"
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if data.get("illustrative_synthetic") is not True:
            raise ValueError(f"{path} must declare illustrative_synthetic: true (RK-12)")
        cfg[name] = data
    return cfg
