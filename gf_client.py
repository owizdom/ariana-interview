#!/usr/bin/env python3
from __future__ import annotations

import json
import ssl
from urllib import request
from urllib.parse import quote_plus

from typing import Any

GITHUB_API = "https://api.github.com"


def _headers(token: str | None) -> dict[str, str]:
    h = {
        "User-Agent": "github-top-functions-script",
        "Accept": "application/vnd.github+json",
    }
    if token:
        h["Authorization"] = f"token {token}"
    return h


def request_json(url: str, token: str | None = None) -> Any:
    req = request.Request(url, headers=_headers(token))
    with request.urlopen(req, context=ssl.create_default_context()) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _build_search_url(query: str, *, sort: str, order: str, per_page: int, page: int) -> str:
    return (
        f"{GITHUB_API}/search/repositories?"
        f"q={quote_plus(query)}&sort={sort}&order={order}"
        f"&per_page={per_page}&page={page}"
    )


def fetch_top_repositories(query: str, top_n: int, token: str | None = None) -> tuple[list[dict], int]:
    requested = max(1, min(top_n, 1000))
    repos: list[dict] = []
    page = 1
    total_count = 0

    while len(repos) < requested:
        remain = requested - len(repos)
        per_page = min(100, remain)
        url = _build_search_url(query, sort="stars", order="desc", per_page=per_page, page=page)
        response = request_json(url, token=token)

        if not total_count:
            total_count = int(response.get("total_count", 0))

        items = response.get("items", [])
        if not items:
            break

        repos.extend(items)
        if len(items) < per_page:
            break
        if page * 100 >= 1000:
            break
        if len(repos) >= total_count:
            break

        page += 1

    return repos[:requested], total_count


def repo_zip_url(full_name: str, default_branch: str | None = None) -> str:
    owner, name = full_name.split("/", 1)
    branch = default_branch or "main"
    return f"{GITHUB_API}/repos/{owner}/{name}/zipball/{branch}"


def download_file(url: str, token: str | None, dest):
    req = request.Request(url, headers=_headers(token))
    with request.urlopen(req, context=ssl.create_default_context()) as resp, dest.open("wb") as out:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
