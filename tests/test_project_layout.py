"""R-21.1: the folder structure from spec section 21 / docs/03 section 6 exists. No database needed."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_DIRS = [
    "config", "data", "data/raw", "data/processed", "data/ground_truth", "data/validation",
    "src", "src/common", "src/models", "src/repositories", "src/services", "src/reference", "src/data",
    "src/validation", "src/evaluation", "src/api", "src/analytics", "src/dashboard",
    "sql", "migrations", "migrations/versions", "tests", "tests/db", "tests/fixtures/negative", "docs", "scripts",
]
REQUIRED_FILES = [
    "CLAUDE.md", "PROGRESS.md", "README.md", "pyproject.toml", "requirements.txt", ".env.example", ".gitignore",
    "docker-compose.yml", "alembic.ini", "migrations/env.py", "sql/triggers.sql", "sql/grants.sql",
    "docs/10_data_dictionary.md",
]


def test_required_directories_exist():
    missing = [d for d in REQUIRED_DIRS if not (ROOT / d).is_dir()]
    assert not missing, f"missing directories: {missing}"


def test_required_files_exist():
    missing = [f for f in REQUIRED_FILES if not (ROOT / f).is_file()]
    assert not missing, f"missing files: {missing}"


def test_env_example_has_no_real_looking_secrets():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for line in text.splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, _, value = line.partition("=")
            if "PASSWORD" in key or "SECRET" in key or "API_KEY" in key:
                assert value.strip() in ("", "change-me") or value.strip().startswith("change-me"), f"{key} looks like a real secret"


def test_env_file_is_gitignored():
    assert ".env" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
