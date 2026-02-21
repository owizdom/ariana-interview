#!/usr/bin/env python3
"""Collect function definitions from top GitHub repositories.

Prints matches as soon as each repository finishes scanning.
"""

from __future__ import annotations

import argparse
import os
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

import gf_client
import gf_scanner


@dataclass
class RepoResult:
    name: str
    full_name: str
    url: str
    stars: int
    functions: list[dict]


def _parse_batch_targets(raw: str | None, final_top: int) -> list[int]:
    if not raw:
        return [final_top]

    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        return [final_top]

    targets: list[int] = []
    for part in parts:
        value = int(part)
        if value <= 0:
            continue
        if value > final_top:
            value = final_top
        targets.append(value)

    if not targets:
        return [final_top]

    targets = sorted(set(targets))
    if targets[-1] < final_top:
        targets.append(final_top)

    return targets


def _chunked_targets(final_top: int, chunk_size: int) -> list[int]:
    step = max(1, chunk_size)
    targets = list(range(step, final_top + 1, step))
    if not targets or targets[-1] != final_top:
        targets.append(final_top)
    return targets


def _print_functions(repo: str, functions: list[dict], show_body: bool) -> None:
    for fn in functions:
        start = int(fn["start_line"])
        end = max(start, int(fn["end_line"]))
        print(f"[{repo}] {fn['path']} start:{start} end:{end} {fn['kind']} {fn['name']}")
        if show_body:
            body = fn.get("body")
            if isinstance(body, str) and body.strip():
                print(body)
        print("-" * 80)


def _scan_repository(
    idx: int,
    repo: dict,
    zip_dir: Path,
    token: str | None,
    max_file_kb: int,
    show_body: bool,
    keep_zip: bool,
) -> tuple[int, RepoResult, int]:
    full_name = repo["full_name"]
    branch = repo.get("default_branch", "main")
    zip_url = gf_client.repo_zip_url(full_name, default_branch=branch)
    zip_path = zip_dir / f"{full_name.replace('/', '__')}.zip"

    try:
        gf_client.download_file(zip_url, token=token, dest=zip_path)
        funcs = gf_scanner.scan_zip_archive(
            zip_path,
            full_name,
            max_file_kb,
            collect_body=show_body,
        )
    except (HTTPError, URLError, zipfile.BadZipFile):
        funcs = []
    finally:
        if zip_path.exists() and not keep_zip:
            zip_path.unlink()

    result = RepoResult(
        name=full_name.split("/", 1)[1],
        full_name=full_name,
        url=repo.get("html_url", ""),
        stars=repo.get("stargazers_count", 0),
        functions=funcs,
    )

    return idx, result, len(funcs)


def _process_repositories(
    repos: list[dict],
    start: int,
    end: int,
    total: int,
    zip_dir: Path,
    args,
) -> tuple[int, int]:
    selected = repos[start:end]
    processed = 0
    function_count = 0

    workers = max(1, int(args.workers))
    if workers == 1:
        for offset, repo in enumerate(selected, start=start + 1):
            idx, result, count = _scan_repository(
                offset,
                repo,
                zip_dir,
                args.token,
                args.max_file_kb,
                args.show_body,
                args.keep_zip,
            )
            print(f"[{idx}/{total}] done")
            _print_functions(result.full_name, result.functions, args.show_body)
            processed += 1
            function_count += count
        return processed, function_count

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _scan_repository,
                offset,
                repo,
                zip_dir,
                args.token,
                args.max_file_kb,
                args.show_body,
                args.keep_zip,
            ): offset
            for offset, repo in enumerate(selected, start=start + 1)
        }

        for future in as_completed(futures):
            idx, result, count = future.result()
            print(f"[{idx}/{total}] done")
            _print_functions(result.full_name, result.functions, args.show_body)
            processed += 1
            function_count += count

    return processed, function_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect function definitions from top GitHub repositories")
    parser.add_argument(
        "--query",
        default="stars:>1",
        help="GitHub search query (default: stars:>1).",
    )
    parser.add_argument("--top", type=int, default=100, help="How many repositories to process (max 100)")
    parser.add_argument(
        "--token",
        default=os.getenv("GITHUB_TOKEN"),
        help="GitHub token (or set GITHUB_TOKEN)",
    )
    parser.add_argument(
        "--max-file-kb",
        type=int,
        default=128,
        help="Skip files larger than this",
    )
    parser.add_argument(
        "--workdir",
        default=str(Path.home() / "Desktop" / "my future"),
        help="Temp/output directory",
    )
    parser.add_argument(
        "--batch-targets",
        default=None,
        help="Cumulative batch checkpoints, comma-separated. Example: `10,20,25,30`.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=25,
        help="Process repositories in fixed-size batches (e.g. 25 => 1-25, 26-50, ...).",
    )
    parser.add_argument(
        "--show-body",
        action="store_true",
        default=False,
        help="Print function bodies in terminal output",
    )
    parser.add_argument(
        "--no-body",
        action="store_true",
        help="Disable function body output in terminal (default)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=12,
        help="Parallel workers for repo download/scan",
    )
    parser.add_argument(
        "--keep-zips",
        action="store_true",
        default=False,
        help="Keep downloaded repo ZIP files in the repo.zip folder",
    )
    args = parser.parse_args()

    args.show_body = False if args.no_body else args.show_body

    requested_top = max(1, min(args.top, 100))
    workdir = Path(args.workdir)
    zip_dir = workdir / "repo.zip"
    zip_dir.mkdir(parents=True, exist_ok=True)

    repos, total_count = gf_client.fetch_top_repositories(args.query, requested_top, token=args.token)
    if not repos:
        raise SystemExit("No repositories returned. Check query and API token/rate limits.")

    if total_count and total_count < requested_top:
        print(
            f"Warning: query '{args.query}' matches only {total_count} repositories. "
            f"Returning {len(repos)} out of requested {requested_top}."
        )

    if args.batch_targets:
        batch_targets = _parse_batch_targets(args.batch_targets, requested_top)
    else:
        batch_targets = _chunked_targets(requested_top, args.chunk_size)
    stats = defaultdict(int)
    prev = 0

    for batch_no, target in enumerate(batch_targets, start=1):
        if target > len(repos):
            target = len(repos)
        if target <= prev:
            continue

        print(f"[batch {batch_no}/{len(batch_targets)}] repos {prev + 1}-{target}")
        batch_processed, batch_functions = _process_repositories(
            repos,
            prev,
            target,
            len(repos),
            zip_dir,
            args,
        )
        stats["repositories"] += batch_processed
        stats["functions"] += batch_functions
        prev = target

    print(f"Done. Printed {stats['functions']} functions across {stats['repositories']} repos.")


if __name__ == "__main__":
    main()
