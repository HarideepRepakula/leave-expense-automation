"""Compare two generator output folders (docs/07 section 10; feeds metric M13).

    python -m src.data.compare_runs <folder A> <folder B>

Prints row counts side by side and the SHA-256 comparison of every exported file. Only manifest.generated_at
is ignored (ASM-050). Exit code 0 = reproducible, 1 = differences found.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from src.data.export import compare_manifests, dataset_fingerprint, sha256_file


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2:
        print(__doc__)
        return 2
    a_dir, b_dir = Path(args[0]), Path(args[1])
    a = json.loads((a_dir / "manifest.json").read_text(encoding="utf-8"))
    b = json.loads((b_dir / "manifest.json").read_text(encoding="utf-8"))

    print(f"{'table':<34}{'run A':>8}{'run B':>8}")
    for name in a["row_counts"]:
        print(f"  {name:<32}{a['row_counts'][name]:>8}{b['row_counts'].get(name, '-'):>8}")
    same_files = 0
    for rel in sorted(set(a["files"]) | set(b["files"])):
        on_disk_a = sha256_file(a_dir / rel) if (a_dir / rel).exists() else None
        on_disk_b = sha256_file(b_dir / rel) if (b_dir / rel).exists() else None
        if on_disk_a == on_disk_b == a["files"].get(rel) == b["files"].get(rel):
            same_files += 1
        else:
            print(f"  DIFFERENT: {rel}")
    diffs = compare_manifests(a, b)
    print(f"files compared: {len(a['files'])}; identical SHA-256: {same_files}")
    print(f"fingerprint A: {dataset_fingerprint(a)}")
    print(f"fingerprint B: {dataset_fingerprint(b)}")
    print(f"generated_at (excluded): A={a['generated_at']}  B={b['generated_at']}")
    ok = not diffs and same_files == len(a["files"]) == len(b["files"])
    print("RESULT: REPRODUCIBLE" if ok else "RESULT: DIFFERENT\n" + "\n".join(diffs))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
