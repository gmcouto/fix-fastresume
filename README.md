# fix-fastresume

Corrects **qBittorrent** `.fastresume` time fields when they drift below real elapsed time (`active_time`, `seeding_time`, `finished_time`). This matches the workaround for a known client behavior where counters can lag even if the app runs continuously.

**Stop qBittorrent before running.** If the client is open, it may overwrite `.fastresume` on exit and undo your changes.

## Requirements

- Python 3 (stdlib only; no pip packages)

## Usage

Point at the folder that contains `*.fastresume` files (on many installs this is `BT_backup` under qBittorrent’s data directory).

```bash
python3 fix_fastresume.py /path/to/BT_backup --dry-run
```

Review the report, then apply:

```bash
python3 fix_fastresume.py /path/to/BT_backup
```

For each file that changes, the script writes a same-name backup next to the original (`.bak`) before overwriting.

## What it changes

- **`active_time`**: set to at least `now - added_time` when the stored value is lower.
- If **`completed_time`** is set: **`seeding_time`** and **`finished_time`** are raised to at least `now - completed_time` when lower.

Torrents with invalid or missing `added_time` are skipped.

## Optional local wrapper

`fix.sh` is gitignored so you can keep a personal script that passes your own `BT_backup` path. Example:

```bash
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/fix_fastresume.py" "$YOUR_BT_BACKUP" "$@"
```

Run with `--dry-run` from the CLI as shown above, or pass it through `"$@"`.

## License

No license file is bundled; treat as personal use unless you add one.
