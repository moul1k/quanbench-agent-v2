# src/qa.py
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class Task:
    task_id: str
    prompt: str
    meta: Dict[str, Any]
    raw: Dict[str, Any]


# -------------------------
# loading
# -------------------------
def _guess_prompt_field(d: Dict[str, Any]) -> str:
    for k in ["prompt", "docstring", "nl", "natural_language", "instruction", "question", "description", "text"]:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return json.dumps(d, ensure_ascii=False)[:2000]


def _guess_task_id(d: Dict[str, Any], idx: int) -> str:
    for k in ["task_id", "id", "qid", "name", "uid"]:
        v = d.get(k)
        if v is None:
            continue
        if isinstance(v, (int, float)):
            return str(int(v))
        if isinstance(v, str) and v.strip():
            return v.strip()
    return str(idx)


def load_tasks(jsonl_path: str | Path, limit: Optional[int] = None) -> List[Task]:
    path = Path(jsonl_path)
    if not path.exists():
        raise FileNotFoundError(f"tasks file not found: {path}")

    tasks: List[Task] = []
    with path.open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            if limit is not None and len(tasks) >= limit:
                break
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            tasks.append(
                Task(
                    task_id=_guess_task_id(d, idx),
                    prompt=_guess_prompt_field(d),
                    meta={k: v for k, v in d.items()},
                    raw=d,
                )
            )
    return tasks


# -------------------------
# run utilities
# -------------------------
def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S_utc")


def ensure_dir(p: str | Path) -> Path:
    p = Path(p)
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_json(path: str | Path, obj: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def update_results_md(md_path: str | Path, summary: Dict[str, Any]) -> None:
    md_path = Path(md_path)
    md_path.parent.mkdir(parents=True, exist_ok=True)

    lines: List[str] = []
    lines.append("# Results\n\n")
    lines.append(f"- Updated: `{summary.get('updated_utc','')}`\n")
    lines.append(f"- Tasks evaluated: **{summary.get('num_tasks', 0)}**\n")
    lines.append(f"- Qiskit mode: `{summary.get('qiskit_mode','auto')}`\n")
    lines.append(f"- Run directory: `{summary.get('run_dir','')}`\n\n")

    patches = summary.get("sanitizer_patch_counts", {})
    if patches:
        lines.append("## Import sanitizer patches (counts)\n\n")
        for k, v in sorted(patches.items(), key=lambda x: (-x[1], x[0])):
            lines.append(f"- `{k}`: **{v}**\n")
        lines.append("\n")

    preview = summary.get("preview", [])
    if preview:
        lines.append("## Task preview\n\n")
        lines.append("| task_id | prompt_snippet |\n")
        lines.append("|---:|---|\n")
        for row in preview:
            tid = str(row.get("task_id", ""))
            snip = str(row.get("prompt_snippet", "")).replace("\n", " ")
            lines.append(f"| {tid} | {snip} |\n")

    md_path.write_text("".join(lines), encoding="utf-8")


# -------------------------
# "agentic" sanitizer for Qiskit import drift
# -------------------------
_SANITIZER_RULES_QISKIT1: List[Tuple[str, str, str]] = [
    # name, pattern, replacement
    (
        "remove_qiskit_opflow",
        r"(?m)^\s*from\s+qiskit\.opflow\s+import\s+.*\n?",
        "",
    ),
    (
        "remove_qiskit_aqua",
        r"(?m)^\s*from\s+qiskit\.aqua\s+import\s+.*\n?",
        "",
    ),
    (
        "remove_ignis",
        r"(?m)^\s*from\s+qiskit\.ignis\s+import\s+.*\n?",
        "",
    ),
    # Aer import mistakes: prefer qiskit_aer if available; if not, don't crash just on import
    (
        "rewrite_aer_provider",
        r"(?m)^\s*from\s+qiskit\s+import\s+Aer\s*\n",
        "try:\n    from qiskit_aer import Aer\nexcept Exception:\n    Aer = None\n",
    ),
    (
        "rewrite_execute_import",
        r"(?m)^\s*from\s+qiskit\s+import\s+execute\s*\n",
        "",
    ),
]

_SANITIZER_RULES_LEGACY: List[Tuple[str, str, str]] = [
    # legacy mode is permissive; we mostly avoid crashing on Aer
    (
        "rewrite_aer_provider",
        r"(?m)^\s*from\s+qiskit\s+import\s+Aer\s*\n",
        "try:\n    from qiskit import Aer\nexcept Exception:\n    Aer = None\n",
    ),
]


def sanitize_code_imports(code: str, mode: str = "auto") -> Tuple[str, List[str]]:
    """
    Returns (sanitized_code, patches_applied_names).
    mode: auto | qiskit1 | legacy
    """
    # auto: default to qiskit1-style sanitization because it is stricter and avoids many runtime errors
    rules = _SANITIZER_RULES_QISKIT1 if mode in ("auto", "qiskit1") else _SANITIZER_RULES_LEGACY

    applied: List[str] = []
    out = code

    for name, pattern, repl in rules:
        new_out, n = re.subn(pattern, repl, out)
        if n > 0:
            applied.append(name)
            out = new_out

    # also: strip duplicated blank lines after removals
    out = re.sub(r"\n{3,}", "\n\n", out).strip() + "\n"
    return out, applied
