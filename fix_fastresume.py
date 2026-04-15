#!/usr/bin/env python3
"""
Fix qBittorrent .fastresume active time bug.

qBittorrent has a known bug where active_time, seeding_time, and finished_time
drift below the actual elapsed time even when the client runs 24/7. This script
corrects those duration fields to match the real elapsed time since each torrent
was added/completed.

Usage:
    python3 fix_fastresume.py <folder_path> [--dry-run]

IMPORTANT: Stop qBittorrent before running this script. It overwrites
.fastresume files on shutdown and would revert any changes made while running.
"""

import argparse
import os
import shutil
import sys
import time


# ---------------------------------------------------------------------------
# Bencode decoder / encoder
# ---------------------------------------------------------------------------

def bdecode(data: bytes, idx: int = 0) -> tuple:
    """Decode a bencoded value starting at idx. Returns (value, next_idx)."""
    ch = data[idx:idx + 1]

    if ch == b"d":
        idx += 1
        d = {}
        keys_order = []
        while data[idx:idx + 1] != b"e":
            key, idx = bdecode(data, idx)
            val, idx = bdecode(data, idx)
            d[key] = val
            keys_order.append(key)
        d["__keys_order__"] = keys_order
        return d, idx + 1

    if ch == b"l":
        idx += 1
        lst = []
        while data[idx:idx + 1] != b"e":
            val, idx = bdecode(data, idx)
            lst.append(val)
        return lst, idx + 1

    if ch == b"i":
        end = data.index(b"e", idx)
        return int(data[idx + 1:end]), end + 1

    # byte string: <length>:<data>
    colon = data.index(b":", idx)
    length = int(data[idx:colon])
    start = colon + 1
    return data[start:start + length], start + length


def bencode(val) -> bytes:
    """Encode a value into bencode format."""
    if isinstance(val, int):
        return b"i" + str(val).encode() + b"e"

    if isinstance(val, bytes):
        return str(len(val)).encode() + b":" + val

    if isinstance(val, str):
        encoded = val.encode("utf-8")
        return str(len(encoded)).encode() + b":" + encoded

    if isinstance(val, list):
        return b"l" + b"".join(bencode(item) for item in val) + b"e"

    if isinstance(val, dict):
        result = b"d"
        keys_order = val.get("__keys_order__")
        if keys_order is not None:
            keys = keys_order
        else:
            keys = sorted(k for k in val if k != "__keys_order__")
        for key in keys:
            if key == "__keys_order__":
                continue
            result += bencode(key) + bencode(val[key])
        result += b"e"
        return result

    raise TypeError(f"Cannot bencode type {type(val)}")


# ---------------------------------------------------------------------------
# Fix logic
# ---------------------------------------------------------------------------

def fix_fastresume(data: dict, now: int) -> dict:
    """Return a copy of the decoded fastresume dict with corrected time fields.

    Returns a dict with keys 'data', 'changes' where changes is a list of
    (field, old_value, new_value) tuples. If no changes are needed, changes
    is empty.
    """
    changes = []
    added_time = data.get(b"added_time", 0)
    completed_time = data.get(b"completed_time", 0)

    if added_time <= 0:
        return {"data": data, "changes": changes}

    expected_active = now - added_time
    active_time = data.get(b"active_time", 0)
    if active_time < expected_active:
        changes.append(("active_time", active_time, expected_active))
        data[b"active_time"] = expected_active

    if completed_time > 0:
        expected_seeding = now - completed_time
        seeding_time = data.get(b"seeding_time", 0)
        if seeding_time < expected_seeding:
            changes.append(("seeding_time", seeding_time, expected_seeding))
            data[b"seeding_time"] = expected_seeding

        finished_time = data.get(b"finished_time", 0)
        if finished_time < expected_seeding:
            changes.append(("finished_time", finished_time, expected_seeding))
            data[b"finished_time"] = expected_seeding

    return {"data": data, "changes": changes}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fmt_duration(seconds: int) -> str:
    """Format a duration in seconds as a human-readable string."""
    days = seconds / 86400
    if days >= 1:
        return f"{days:.1f}d"
    hours = seconds / 3600
    return f"{hours:.1f}h"


def get_torrent_name(data: dict) -> str:
    """Extract the torrent name from the decoded data."""
    name = data.get(b"qBt-name", data.get(b"name", b""))
    if isinstance(name, bytes):
        return name.decode("utf-8", errors="replace")
    return str(name)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Fix qBittorrent .fastresume active time bug."
    )
    parser.add_argument(
        "folder",
        help="Path to folder containing .fastresume files (e.g. BT_backup).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without modifying any files.",
    )
    args = parser.parse_args()

    folder = os.path.abspath(args.folder)
    if not os.path.isdir(folder):
        print(f"Error: '{folder}' is not a directory.", file=sys.stderr)
        sys.exit(1)

    files = sorted(
        f for f in os.listdir(folder) if f.endswith(".fastresume")
    )
    if not files:
        print(f"No .fastresume files found in '{folder}'.")
        sys.exit(0)

    now = int(time.time())
    total_files = len(files)
    fixed_count = 0
    skipped_count = 0
    error_count = 0

    mode_label = "DRY RUN" if args.dry_run else "FIX"
    print(f"[{mode_label}] Processing {total_files} .fastresume files in: {folder}")
    print(f"Reference time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))}")
    print("-" * 90)

    for fname in files:
        fpath = os.path.join(folder, fname)
        short = fname[:12] + "..."

        try:
            with open(fpath, "rb") as f:
                raw = f.read()
            data, _ = bdecode(raw)
        except Exception as e:
            print(f"  ERROR  {short}  Failed to decode: {e}")
            error_count += 1
            continue

        result = fix_fastresume(data, now)
        changes = result["changes"]

        if not changes:
            skipped_count += 1
            continue

        name = get_torrent_name(data)
        display_name = (name[:50] + "...") if len(name) > 50 else name
        print(f"\n  {short}  {display_name}")

        for field, old_val, new_val in changes:
            deficit = new_val - old_val
            print(
                f"    {field:16s}  {fmt_duration(old_val):>8s} -> "
                f"{fmt_duration(new_val):>8s}  (deficit: {fmt_duration(deficit)})"
            )

        if not args.dry_run:
            bak_path = fpath + ".bak"
            shutil.copy2(fpath, bak_path)
            encoded = bencode(result["data"])
            with open(fpath, "wb") as f:
                f.write(encoded)

        fixed_count += 1

    print("-" * 90)
    action = "Would fix" if args.dry_run else "Fixed"
    print(
        f"{action} {fixed_count} / {total_files} files  "
        f"(skipped {skipped_count}, errors {error_count})"
    )
    if args.dry_run and fixed_count > 0:
        print("Run again without --dry-run to apply changes.")


if __name__ == "__main__":
    main()
