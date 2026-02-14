# scripts/run.py
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import argparse
from collections import Counter
from pathlib import Path

from src.qa import (
    load_tasks,
    now_stamp,
    ensure_dir,
    write_json,
    update_results_md,
    sanitize_code_imports,
)


def main() -> None:
    ap = argparse.ArgumentParser(description="QuanBench minimal runner (with Qiskit import sanitizer).")
    ap.add_argument("--data", type=str, default="data/quanbench44.jsonl", help="Path to JSONL tasks file.")
    ap.add_argument("--limit", type=int, default=5, help="How many tasks to include in this run.")
    ap.add_argument("--task_id", type=str, default=None, help="Optional single task_id to preview.")
    ap.add_argument(
        "--qiskit_mode",
        type=str,
        default="auto",
        choices=["auto", "qiskit1", "legacy"],
        help="Import-sanitizer mode. Use qiskit1 for QuanBench-117.",
    )
    args = ap.parse_args()

    tasks = load_tasks(args.data, limit=None)

    selected = tasks
    mode = "metadata-only"
    if args.task_id is not None:
        selected = [t for t in tasks if str(t.task_id) == str(args.task_id)]
        mode = "metadata-only-single"
        if not selected:
            raise SystemExit(f"task_id not found: {args.task_id}")

    if args.limit is not None and args.task_id is None:
        selected = selected[: args.limit]

    run_dir = ensure_dir(Path("runs") / now_stamp())
    per_task = ensure_dir(run_dir / "per_task")

    patch_counter = Counter()
    preview_rows = []
    results = {
        "mode": mode,
        "qiskit_mode": args.qiskit_mode,
        "data_path": str(Path(args.data)),
        "num_tasks_loaded": len(tasks),
        "num_tasks_selected": len(selected),
        "tasks": [],
    }

    # For now we demonstrate sanitizer on a placeholder "candidate code"
    # (Next step we will generate candidates and actually execute tests.)
    placeholder_candidate = """\
from qiskit import QuantumCircuit
from qiskit import Aer
from qiskit.opflow import I, X

def build_circuit():
    qc = QuantumCircuit(1)
    qc.x(0)
    return qc
"""

    for t in selected:
        snippet = (t.prompt[:120] + "…") if len(t.prompt) > 120 else t.prompt
        snippet = snippet.replace("\n", " ").strip()

        tdir = ensure_dir(per_task / str(t.task_id))
        write_json(tdir / "task.json", {"task_id": t.task_id, "prompt": t.prompt, "meta": t.meta})

        sanitized, patches = sanitize_code_imports(placeholder_candidate, mode=args.qiskit_mode)
        for p in patches:
            patch_counter[p] += 1

        # save sanitizer example artifact
        (tdir / "candidate_raw.py").write_text(placeholder_candidate, encoding="utf-8")
        (tdir / "candidate_sanitized.py").write_text(sanitized, encoding="utf-8")
        write_json(tdir / "sanitizer.json", {"patches_applied": patches})

        results["tasks"].append(
            {
                "task_id": t.task_id,
                "prompt_snippet": snippet,
                "sanitizer_patches": patches,
            }
        )
        preview_rows.append({"task_id": t.task_id, "prompt_snippet": snippet})

    write_json(run_dir / "results.json", results)

    summary = {
        "updated_utc": run_dir.name.replace("_utc", " UTC"),
        "num_tasks": len(selected),
        "qiskit_mode": args.qiskit_mode,
        "run_dir": str(run_dir),
        "sanitizer_patch_counts": dict(patch_counter),
        "preview": preview_rows[: min(10, len(preview_rows))],
    }
    update_results_md("docs/results.md", summary)

    print(f"OK: wrote {run_dir/'results.json'}")
    print("OK: updated docs/results.md")
    print(f"OK: sanitizer patches summary: {dict(patch_counter)}")


if __name__ == "__main__":
    main()
