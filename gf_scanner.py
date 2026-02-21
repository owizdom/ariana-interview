#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

import gf_extractors

SKIP_DIRS = {
    ".git",
    "node_modules",
    "dist",
    "build",
    ".venv",
    "vendor",
    "target",
    "__pycache__",
    ".idea",
    ".vscode",
}


def should_skip(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def find_brace_block_end(lines: list[str], start_line: int) -> int:
    depth = 0
    seen_open = False

    for i in range(start_line - 1, len(lines)):
        line = lines[i]
        for ch in line:
            if ch == "{":
                depth += 1
                seen_open = True
            elif ch == "}" and depth > 0:
                depth -= 1
                if depth == 0:
                    return i + 1

    return len(lines) if seen_open else start_line


def find_ruby_end_line(lines: list[str], start_line: int) -> int:
    depth = 0
    for i in range(start_line - 1, len(lines)):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("def "):
            depth += 1
        if stripped == "end" or stripped.startswith("end"):
            if depth > 0:
                depth -= 1
                if depth == 0:
                    return i + 1
    return len(lines)


def infer_end_line(extension: str, lines: list[str], start_line: int) -> int:
    if extension == ".rb":
        return find_ruby_end_line(lines, start_line)
    return find_brace_block_end(lines, start_line)


def scan_zip_archive(
    zip_path: Path,
    repo_id: str,
    max_file_kb: int,
    *,
    collect_body: bool = False,
) -> list[dict]:
    funcs: list[dict] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(root)

        extracted = [p for p in root.rglob("*") if p.is_dir()]
        top_dir = next((p for p in extracted if (p / "README.md").exists()), None)
        if top_dir is None:
            top_dir = extracted[0] if extracted else root

        for file_path in top_dir.rglob("*"):
            if file_path.is_dir() or should_skip(file_path.relative_to(top_dir)):
                continue

            rel = file_path.relative_to(top_dir)
            extension = file_path.suffix.lower()
            extractor = gf_extractors.EXTRACTORS.get(extension)
            if not extractor:
                continue

            try:
                if file_path.stat().st_size > max_file_kb * 1024:
                    continue
                source = file_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            try:
                extracted_funcs = extractor(source)
            except Exception:
                continue

            lines = source.splitlines()
            for hit in extracted_funcs:
                actual_end = hit.end_line
                if extension not in {".py", ".pyi"}:
                    actual_end = infer_end_line(extension, lines, hit.start_line)

                if actual_end < hit.start_line:
                    actual_end = hit.start_line
                record: dict[str, object] = {
                    "repo": repo_id,
                    "path": str(rel).replace("\\", "/"),
                    "name": hit.name,
                    "start_line": hit.start_line,
                    "end_line": actual_end,
                    "kind": hit.kind,
                    "extension": extension,
                }
                if collect_body:
                    body = "\n".join(lines[hit.start_line - 1 : actual_end])
                    if body:
                        record["body"] = body
                funcs.append(record)

    return funcs
