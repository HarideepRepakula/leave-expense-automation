"""Compare two generator output folders (docs/07 section 10; feeds metric M13).

    python -m src.data.compare_runs <folder A> <folder B> [--report <file.json>]

Prints row counts side by side and the SHA-256 comparison of every exported file. Only manifest.generated_at
is ignored (ASM-050). Exit code 0 = reproducible, 1 = differences found. --report also writes the counts as JSON
(the reproducibility scripts write data/validation/reproducibility.json, read by src/evaluation for M13).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from src.data.export import compare_manifests, dataset_fingerprint, sha256_file


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    report = None
    if "--report" in args:
        i = args.index("--report")
        report = Path(args[i + 1]) if i + 1 < len(args) else None
        del args[i:i + 2]
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
    per_folder: dict[str, list[int]] = {}
    for rel in sorted(set(a["files"]) | set(b["files"])):
        on_disk_a = sha256_file(a_dir / rel) if (a_dir / rel).exists() else None
        on_disk_b = sha256_file(b_dir / rel) if (b_dir / rel).exists() else None
        counts = per_folder.setdefault(rel.split("/")[0], [0, 0])
        counts[0] += 1
        if on_disk_a == on_disk_b == a["files"].get(rel) == b["files"].get(rel):
            same_files += 1
            counts[1] += 1
        else:
            print(f"  DIFFERENT: {rel}")
    for folder, (n, same) in sorted(per_folder.items()):
        print(f"  {folder + '/':<16}files {n:>3}   identical SHA-256 {same:>3}")
    diffs = compare_manifests(a, b)
    print(f"files compared: {len(a['files'])}; identical SHA-256: {same_files}")
    print(f"fingerprint A: {dataset_fingerprint(a)}")
    print(f"fingerprint B: {dataset_fingerprint(b)}")
    print(f"generated_at (excluded): A={a['generated_at']}  B={b['generated_at']}")
    ok = not diffs and same_files == len(a["files"]) == len(b["files"])
    print("RESULT: REPRODUCIBLE" if ok else "RESULT: DIFFERENT\n" + "\n".join(diffs))
    if report is not None:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({
            "files_compared": len(a["files"]), "identical_sha256": same_files, "reproducible": ok,
            "per_folder": {k: {"files": n, "identical": s} for k, (n, s) in sorted(per_folder.items())},
            "fingerprint_a": dataset_fingerprint(a), "fingerprint_b": dataset_fingerprint(b), "seed": a.get("seed"),
            "differences": diffs}, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
