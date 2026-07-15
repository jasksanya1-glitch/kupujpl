"""Known affiliate referral IDs provided by the site owner (chat + scan_config)."""
from __future__ import annotations

import os
import re
from pathlib import Path

# Referral links the user explicitly provided in project chat / config files.
KNOWN_AFFILIATE_ENV: dict[str, str] = {
    "G2A_GOLDMINE_GNAME": "reflink-1c4032615f",
    "INSTANT_GAMING_REF": "gamer-c353127",
    "GAMIVO_REF": "5oq0ouor",
}


def merge_affiliate_env_file(env_path: Path, extra: dict[str, str] | None = None) -> list[str]:
    """Ensure known affiliate keys exist in a .env file. Returns list of keys added/updated."""
    values = {**KNOWN_AFFILIATE_ENV, **(extra or {})}
    lines: list[str] = []
    if env_path.is_file():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    present = set()
    out: list[str] = []
    changed: list[str] = []
    for line in lines:
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line.strip())
        if m and m.group(1) in values:
            key = m.group(1)
            new_val = values[key]
            old_val = m.group(2).strip().strip('"').strip("'")
            if old_val != new_val:
                changed.append(key)
            out.append(f"{key}={new_val}")
            present.add(key)
        else:
            out.append(line)
    for key, val in values.items():
        if key not in present:
            out.append(f"{key}={val}")
            changed.append(key)
    if not any(l.strip() == "# --- affiliate referral IDs (owner) ---" for l in out):
        out.append("")
        out.append("# --- affiliate referral IDs (owner) ---")
        for key in sorted(values):
            if key not in present and key in changed:
                pass  # already appended above
    env_path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    return changed


def sync_scan_config_affiliate_to_env(
    scan_config_path: Path,
    env_path: Path,
) -> list[str]:
    """Copy AWIN_* and AFFILIATE_* lines from scan_config.env into main .env if missing."""
    if not scan_config_path.is_file():
        return []
    prefixes = ("AWIN_", "AFFILIATE_", "G2A_GOLDMINE_", "GAMIVO_REF", "INSTANT_GAMING_")
    to_merge: dict[str, str] = {}
    for line in scan_config_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if key.startswith(prefixes) and val:
            to_merge[key] = val
    return merge_affiliate_env_file(env_path, to_merge)
