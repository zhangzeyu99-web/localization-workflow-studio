"""Sync the embedded workflow copies in this repository from their source repos.

Single maintenance sources:
- localization: D:\\project\\localization-workflow-project  -> workflow/localization
- glossary:     D:\\codex\\glossary-extraction-workflow      -> workflow/glossary

The embedded copies are sync artifacts. Never edit them directly; edit the
source repository, run its tests, then run this script and its verification.

Usage:
    python scripts/sync_workflow_sources.py glossary
    python scripts/sync_workflow_sources.py localization
    python scripts/sync_workflow_sources.py all [--dry-run]

After syncing `localization` you MUST run the backend suite
(`python -m pytest backend/tests -q`) because the product invokes
process_language.py / run_quality_harness.py / run_translation_harness.py
as subprocesses. After syncing `glossary`, run the embedded tests
(`python -m pytest workflow/glossary/tests -q`).
"""
from __future__ import annotations

import argparse
import filecmp
import fnmatch
import hashlib
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

STUDIO_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class SyncTarget:
    name: str
    source: Path
    dest: Path
    # Directory names excluded anywhere in the tree.
    exclude_dirs: set[str] = field(default_factory=set)
    # Top-level entries (files or dirs) excluded from the sync scope.
    exclude_top: set[str] = field(default_factory=set)
    # Glob patterns excluded anywhere in the tree.
    exclude_globs: tuple[str, ...] = ()
    # Files preserved in the destination even though the source lacks them.
    keep_in_dest: set[str] = field(default_factory=lambda: {"SYNC.md"})


COMMON_EXCLUDE_DIRS = {".git", ".github", ".pytest_cache", "__pycache__", ".ruff_cache", ".cursor", ".agents", ".local", ".tmp", ".translation_cache", "tmp", "output"}

TARGETS = {
    "glossary": SyncTarget(
        name="glossary",
        source=Path(r"D:\codex\glossary-extraction-workflow"),
        dest=STUDIO_ROOT / "workflow" / "glossary",
        exclude_dirs=set(COMMON_EXCLUDE_DIRS),
        exclude_top={".gitignore"},
        exclude_globs=("*.log",),
    ),
    "localization": SyncTarget(
        name="localization",
        source=Path(r"D:\project\localization-workflow-project"),
        dest=STUDIO_ROOT / "workflow" / "localization",
        exclude_dirs=set(COMMON_EXCLUDE_DIRS),
        # Repo-private assets stay in the source repo only.
        exclude_top={
            ".gitignore",
            "docs",
            "tools",
            "examples",
            "AGENTS.md",
            "README.md",
            "workflow-design.md",
            "localization-workflow.code-workspace",
        },
        exclude_globs=("*.log", "*.pdf", "*.xlsx", "*.docx", "*说明*.md"),
    ),
}


def _norm_hash(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha1(data).hexdigest()


def _in_scope(target: SyncTarget, rel: Path) -> bool:
    parts = rel.parts
    if not parts:
        return False
    if parts[0] in target.exclude_top:
        return False
    if any(p in target.exclude_dirs for p in parts):
        return False
    return not any(fnmatch.fnmatch(parts[-1], pat) or fnmatch.fnmatch(str(rel), pat) for pat in target.exclude_globs)


def _scoped_files(target: SyncTarget, root: Path) -> dict[Path, Path]:
    files: dict[Path, Path] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if _in_scope(target, rel):
            files[rel] = path
    return files


def sync(target: SyncTarget, dry_run: bool = False) -> int:
    if not target.source.exists():
        print(f"[{target.name}] ERROR: source not found: {target.source}")
        return 1
    src_files = _scoped_files(target, target.source)
    dst_files = _scoped_files(target, target.dest) if target.dest.exists() else {}

    copied, removed, unchanged = [], [], []
    for rel, src in sorted(src_files.items()):
        dst = target.dest / rel
        if dst.exists() and filecmp.cmp(src, dst, shallow=False):
            unchanged.append(rel)
            continue
        copied.append(rel)
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    for rel in sorted(dst_files):
        if rel in src_files or rel.name in target.keep_in_dest:
            continue
        removed.append(rel)
        if not dry_run:
            (target.dest / rel).unlink()

    prefix = "[dry-run] " if dry_run else ""
    print(f"[{target.name}] {prefix}copied={len(copied)} removed={len(removed)} unchanged={len(unchanged)}")
    for rel in copied:
        print(f"  + {rel}")
    for rel in removed:
        print(f"  - {rel}")

    if dry_run:
        return 0

    mismatches = [rel for rel, src in src_files.items() if _norm_hash(src) != _norm_hash(target.dest / rel)]
    if mismatches:
        print(f"[{target.name}] READBACK FAILED: {len(mismatches)} mismatched files")
        for rel in mismatches:
            print(f"  ! {rel}")
        return 1
    print(f"[{target.name}] readback OK: {len(src_files)} files hash-verified")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", choices=[*TARGETS, "all"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    names = list(TARGETS) if args.target == "all" else [args.target]
    rc = 0
    for name in names:
        rc |= sync(TARGETS[name], dry_run=args.dry_run)
    if rc == 0 and not args.dry_run:
        print("Next: run the verification suites listed in the module docstring.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
