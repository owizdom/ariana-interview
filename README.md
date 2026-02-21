# GitHub Function Scanner

This script scans the top 100 GitHub repositories and prints all detected functions with:
- repository
- file path
- start line and end line
- function name and type

## Files
- `runner.py` - main command
- `gf_client.py` - GitHub API helpers
- `gf_scanner.py` - zip download + code scan + line detection
- `gf_extractors.py` - function extractors for supported languages

## Quick start
```bash
cd "/Users/Apple/Desktop/my future"
python3 runner.py
```

## Default behavior
- Searches top repos by stars
- Default `top`: `100`
- Default batch targets: `10,20,25,30`
- Prints function output as soon as each repository is processed
- No report file is written
- Body output is **on** by default (use `--no-body` to disable)

## Options
- `--query` Set GitHub search query (default: `stars:>1`)
- `--top N` Number of repos to process (max 100)
- `--batch-targets "10,20,25,30"` Cumulative batch checkpoints
- `--workers N` Parallel workers for repo scan (default: `4`)
- `--max-file-kb N` Skip files larger than N KB (default: `512`)
- `--show-body` Print function bodies in terminal output (default on)
- `--no-body` Disable function body output
- `--workdir` Temp/output directory (default: `~/Desktop/my future`)

## Example
```bash
python3 runner.py --top 100 --workers 8
python3 runner.py --top 100 --show-body
```
