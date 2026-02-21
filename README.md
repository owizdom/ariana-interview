# GitHub Function Scanner

Scans GitHub repos and prints detected functions in the terminal.

## Files
- `runner.py` (entrypoint)
- `gf_client.py` (GitHub API helpers)
- `gf_scanner.py` (zip download + file scan)
- `gf_extractors.py` (function detection)

## Quick start
```bash
cd "/Users/Apple/Desktop/my future"
python3 runner.py
```

## What it prints
Each match prints:
`[owner/repo] path start:<n> end:<n> <type> <name>`

If `--show-body` is enabled, the function body is printed after this line.

It also prints:
- `[repo_idx/total] done` for each repo
- `[batch x/y] repos a-b` for each chunk

## Default behavior
- Repo search: top by stars
- `--top`: `100` (max 100)
- Chunking: `--chunk-size 25` (`1-25`, `26-50`, `...`, `...-100`)
- Parallel scans: `--workers 12`
- No output file is written
- Body output is off by default (`--show-body` to enable)
- Repo ZIP downloads are written to `<workdir>/repo.zip/` and removed after each repo unless `--keep-zips` is passed.

To see function bodies on `python3 runner.py`, use:
```bash
python3 runner.py --show-body
```

## Options
- `--query` Query string for GitHub search (default: `stars:>1`)
- `--top N` Repos to process (default: `100`)
- `--chunk-size N` Chunk size for default batching (default: `25`)
- `--batch-targets "10,20,25,30"` Custom batch end points (overrides `--chunk-size`)
- `--workers N` Parallel workers (default: `12`)
- `--max-file-kb N` Skip files larger than N KB (default: `128`)
- `--show-body` Print function bodies
- `--no-body` Disable function bodies (default)
- `--workdir` Base directory for temporary files (default: `~/Desktop/my future`; ZIPs stored in `<workdir>/repo.zip/`)
- `--keep-zips` Keep downloaded ZIP files in `<workdir>/repo.zip/`
- `--parallel-terminals` Spawn each batch in separate Terminal instances
- `--terminal-app` Terminal app name (default: `Terminal`) used with `--parallel-terminals`

## Examples
```bash
python3 runner.py
python3 runner.py --show-body
python3 runner.py --top 100 --workers 8
python3 runner.py --chunk-size 20
python3 runner.py --parallel-terminals
python3 runner.py --parallel-terminals --chunk-size 15
```
