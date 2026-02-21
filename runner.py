#!/usr/bin/env python3
"""Collect function definitions from top GitHub repositories.

Prints matches as soon as each repository finishes scanning.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
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


def _batch_ranges(total: int, targets: list[int] | None, chunk_size: int) -> list[tuple[int, int]]:
    if not targets:
        targets = _chunked_targets(total, chunk_size)

    ranges: list[tuple[int, int]] = []
    prev = 0
    for target in targets:
        end = min(total, max(target, 0))
        if end > prev:
            ranges.append((prev, end))
            prev = end
    if prev < total:
        ranges.append((prev, total))
    return ranges


def _build_common_argv(args: argparse.Namespace) -> list[str]:
    argv = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--query",
        args.query,
        "--top",
        str(args.top),
        "--max-file-kb",
        str(args.max_file_kb),
        "--workers",
        str(args.workers),
        "--workdir",
        args.workdir,
        "--chunk-size",
        str(args.chunk_size),
    ]

    if args.token:
        argv.extend(["--token", args.token])
    if args.show_body:
        argv.append("--show-body")
    if args.no_body:
        argv.append("--no-body")
    if args.keep_zips:
        argv.append("--keep-zips")

    return argv


def _escape_applescript_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _launch_terminal_batch(
    batch_no: int,
    total_batches: int,
    start: int,
    end: int,
    args: argparse.Namespace,
) -> subprocess.Popen[object]:
    start_idx = start + 1
    end_idx = end
    argv = _build_common_argv(args)
    argv.extend(
        [
            "--subset-start",
            str(start_idx),
            "--subset-end",
            str(end_idx),
            "--batch-label",
            f"{batch_no}/{total_batches}",
        ]
    )

    if sys.platform.startswith("darwin"):
        script_body = " ".join(shlex.quote(part) for part in argv)
        terminal = args.terminal_app
        cwd = shlex.quote(str(Path(__file__).resolve().parent))
        command = f"cd {cwd} && {script_body}"
        escaped_command = _escape_applescript_text(command)
        osascript = [
            "osascript",
            "-e",
            f'tell application "{terminal}" to activate',
            "-e",
            f'tell application "{terminal}" to do script "{escaped_command}"',
        ]
        return subprocess.Popen(osascript)

    return subprocess.Popen(argv)


def _run_subset(args: argparse.Namespace) -> tuple[int, int]:
    if args.subset_start is None or args.subset_end is None:
        return 0, 0

    requested_top = max(1, min(args.top, 100))
    workdir = Path(args.workdir)
    zip_dir = workdir / "repo.zip"
    zip_dir.mkdir(parents=True, exist_ok=True)

    repos, _ = gf_client.fetch_top_repositories(args.query, requested_top, token=args.token)
    if not repos:
        return 0, 0

    start = max(args.subset_start - 1, 0)
    end = min(args.subset_end, len(repos))
    if end <= 0 or start >= end:
        return 0, 0

    if getattr(args, "batch_label", None):
        print(f"[batch {args.batch_label}] repos {start + 1}-{end}")

    repositories, functions = _process_repositories(
        repos,
        start,
        end,
        len(repos),
        zip_dir,
        args,
    )
    print(f"[batch {args.batch_label} done] Printed {functions} functions across {repositories} repos.")
    return repositories, functions


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
            args.keep_zips,
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
                args.keep_zips,
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
    parser.add_argument(
        "--parallel-terminals",
        action="store_true",
        help="Spawn each batch in a separate Terminal window/process",
    )
    parser.add_argument(
        "--terminal-app",
        default="Terminal",
        help="Terminal app name (default: Terminal)",
    )
    parser.add_argument(
        "--subset-start",
        type=int,
        default=None,
        help="(internal) 1-based start index of repos to scan",
    )
    parser.add_argument(
        "--subset-end",
        type=int,
        default=None,
        help="(internal) 1-based end index of repos to scan",
    )
    parser.add_argument(
        "--batch-label",
        default=None,
        help="(internal) label for batch output",
    )
    args = parser.parse_args()

    args.show_body = False if args.no_body else args.show_body

    if args.subset_start is not None and args.subset_end is not None:
        _, _ = _run_subset(args)
        return

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
        batch_targets = None

    ranges = _batch_ranges(len(repos), batch_targets, args.chunk_size)
    if not ranges:
        return

    if args.parallel_terminals:
        processes = []
        print(
            f"Starting {len(ranges)} terminal instance(s) for batches using app '{args.terminal_app}'."
        )
        for batch_no, (start, end) in enumerate(ranges, start=1):
            print(f"[batch {batch_no}/{len(ranges)}] spawning repos {start + 1}-{end}")
            proc = _launch_terminal_batch(batch_no, len(ranges), start, end, args)
            processes.append(proc)

        for process in processes:
            stdout, stderr = process.communicate()
            return_code = process.returncode
            if return_code != 0:
                print(f"One batch command failed with status {return_code}.")
                if stdout:
                    print(stdout.strip())
                if stderr:
                    print(stderr.strip())
        print(f"Spawned and waited for {len(processes)} batch process(es).")
        return

    stats = defaultdict(int)
    for batch_no, (start, end) in enumerate(ranges, start=1):
        print(f"[batch {batch_no}/{len(ranges)}] repos {start + 1}-{end}")
        batch_processed, batch_functions = _process_repositories(
            repos,
            start,
            end,
            len(repos),
            zip_dir,
            args,
        )
        stats["repositories"] += batch_processed
        stats["functions"] += batch_functions

    print(f"Done. Printed {stats['functions']} functions across {stats['repositories']} repos.")


if __name__ == "__main__":
    main()
