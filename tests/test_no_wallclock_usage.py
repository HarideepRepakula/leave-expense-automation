"""Amendment A7: no wall-clock calls in src/ outside the clock module (which arrives in Phase 3)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = re.compile(r"\b(datetime\.now|datetime\.utcnow|date\.today|time\.time)\s*\(")
ALLOWED = {ROOT / "src" / "common" / "clock.py"}


def test_no_wall_clock_in_src():
    offenders = []
    for path in (ROOT / "src").rglob("*.py"):
        if path in ALLOWED:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if FORBIDDEN.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
    assert not offenders, "wall clock used outside src/common/clock.py:\n" + "\n".join(offenders)
