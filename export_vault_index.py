#!/usr/bin/env python3
"""
Vault Index Generator for OpenClaw Integration

Scans an Obsidian vault and generates a two-tier Markdown index:
- vault_index_summary.md: Top notes and vault breakdown (~500 lines, fits in LLM context)
- vault_index_full.md: All notes with structural metadata (searchable via memory_search)
"""

import os
import re
import sys
import yaml
import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional
from collections import defaultdict, Counter

import frontmatter as fm

SUMMARY_TOP_N = 50
UNDERDEVELOPED_MIN_BACKLINKS = 3
UNDERDEVELOPED_MAX_WORDS = 300
MAX_DISPLAY_LINKS = 20
MAX_DISPLAY_HEADINGS = 10


def setup_logging(log_level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(levelname)s - %(message)s",
    )


def scan_note(file_path: Path, vault_path: Path) -> Optional[Dict[str, Any]]:
    """Read a single note and extract all structural metadata in one pass."""
    try:
        raw_content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        logging.warning(f"Cannot read {file_path}: {e}")
        return None

    note_name = file_path.stem
    relative_path = str(file_path.relative_to(vault_path))
    stat = file_path.stat()

    try:
        created_at = datetime.fromtimestamp(stat.st_birthtime).isoformat()
    except AttributeError:
        created_at = datetime.fromtimestamp(stat.st_ctime).isoformat()
    modified_at = datetime.fromtimestamp(stat.st_mtime).isoformat()

    tags = []
    aliases = []
    frontmatter_fields = {}
    body = raw_content

    try:
        post = fm.loads(raw_content)
        body = post.content

        for key, value in post.metadata.items():
            if key == "tags":
                if isinstance(value, list):
                    tags = [str(t).strip() for t in value if t]
                elif value:
                    tags = [str(value).strip()]
            elif key == "aliases":
                if isinstance(value, list):
                    aliases = [str(a).strip() for a in value if a]
                elif value:
                    aliases = [str(value).strip()]
            elif isinstance(value, (str, int, float, bool)):
                frontmatter_fields[key] = str(value)
            elif isinstance(value, list):
                frontmatter_fields[key] = ", ".join(str(item) for item in value)
    except Exception as e:
        logging.debug(f"Frontmatter parse error for {file_path}: {e}")

    words = body.split()

    inline_tags = re.findall(r"(?<!\w)#(\w[\w/-]*)", body)
    all_tags = sorted(set(tags + inline_tags))

    headings = []
    for line in body.split("\n"):
        m = re.match(r"^(#{1,3})\s+(.+)", line)
        if m:
            headings.append(m.group(2).strip())

    raw_links = re.findall(r"\[\[([^\]]+)\]\]", body)
    wikilink_targets = []
    for link in raw_links:
        target = link.split("|")[0].split("#")[0].strip()
        if target.endswith(".md"):
            target = target[:-3]
        if "/" in target:
            target = target.rsplit("/", 1)[-1]
        if target:
            wikilink_targets.append(target)

    external_url_count = len(re.findall(r"\[[^\]]*\]\(https?://[^)]+\)", body))

    return {
        "note_name": note_name,
        "path": relative_path,
        "word_count": len(words),
        "line_count": raw_content.count("\n") + 1,
        "file_size": stat.st_size,
        "created_at": created_at,
        "modified_at": modified_at,
        "headings": headings,
        "external_url_count": external_url_count,
        "wikilinks": wikilink_targets,
        "tags": all_tags,
        "aliases": aliases,
        "frontmatter": frontmatter_fields,
    }


def scan_vault(vault_path: Path) -> List[Dict[str, Any]]:
    """Scan all markdown files in the vault, skipping hidden directories."""
    md_files = list(vault_path.rglob("*.md"))
    logging.info(f"Found {len(md_files)} markdown files in {vault_path}")

    notes = []
    skipped = 0
    for file_path in md_files:
        if any(
            part.startswith(".") for part in file_path.relative_to(vault_path).parts
        ):
            skipped += 1
            continue
        result = scan_note(file_path, vault_path)
        if result:
            notes.append(result)

    logging.info(f"Scanned {len(notes)} notes ({skipped} hidden files skipped)")
    return notes


def compute_backlinks(notes: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Invert wikilinks: for each target note name, list the notes that link to it."""
    backlinks: Dict[str, List[str]] = defaultdict(list)
    for note in notes:
        source = note["note_name"]
        seen: set = set()
        for target in note["wikilinks"]:
            if target not in seen:
                backlinks[target].append(source)
                seen.add(target)
    return dict(backlinks)


def format_note_block(note: Dict[str, Any], backlinks: Dict[str, List[str]]) -> str:
    """Format a single note as a Markdown block for the index."""
    n = note
    bl = backlinks.get(n["note_name"], [])
    bl_count = len(bl)
    ol_count = len(n["wikilinks"])

    parts = [f"### {n['note_name']}"]

    parts.append(
        f"- **Path**: {n['path']} | **Words**: {n['word_count']:,} "
        f"| **Backlinks**: {bl_count} | **Outlinks**: {ol_count}"
    )

    tag_str = ", ".join(f"#{t}" for t in n["tags"]) if n["tags"] else "none"
    meta = [f"**Tags**: {tag_str}"]
    if "status" in n["frontmatter"]:
        meta.append(f"**Status**: {n['frontmatter']['status']}")
    if "type" in n["frontmatter"]:
        meta.append(f"**Type**: {n['frontmatter']['type']}")
    parts.append(f"- {' | '.join(meta)}")

    mod = n["modified_at"][:10] if n["modified_at"] else "unknown"
    cre = n["created_at"][:10] if n["created_at"] else "unknown"
    parts.append(
        f"- **Modified**: {mod} | **Created**: {cre} "
        f"| **URLs**: {n['external_url_count']}"
    )

    if n["wikilinks"]:
        display = n["wikilinks"][:MAX_DISPLAY_LINKS]
        links_str = ", ".join(f"[[{lnk}]]" for lnk in display)
        if len(n["wikilinks"]) > MAX_DISPLAY_LINKS:
            links_str += f" ... ({len(n['wikilinks'])} total)"
        parts.append(f"- **Links to**: {links_str}")

    if bl:
        display = bl[:MAX_DISPLAY_LINKS]
        bl_str = ", ".join(f"[[{s}]]" for s in display)
        if bl_count > MAX_DISPLAY_LINKS:
            bl_str += f" ... ({bl_count} total)"
        parts.append(f"- **Linked by**: {bl_str}")

    if n["headings"]:
        display = n["headings"][:MAX_DISPLAY_HEADINGS]
        h_str = " > ".join(display)
        if len(n["headings"]) > MAX_DISPLAY_HEADINGS:
            h_str += " ..."
        parts.append(f"- **Headings**: {h_str}")

    if n["aliases"]:
        parts.append(f"- **Aliases**: {', '.join(n['aliases'])}")

    return "\n".join(parts)


def generate_summary(
    notes: List[Dict[str, Any]],
    backlinks: Dict[str, List[str]],
    vault_name: str,
    output_path: Path,
) -> None:
    """Generate vault_index_summary.md with top notes and vault breakdown."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    total_words = sum(n["word_count"] for n in notes)
    all_tags: set = set()
    for n in notes:
        all_tags.update(n["tags"])

    lines = [
        "# Vault Index Summary",
        "",
        f"Generated: {now} | Vault: {vault_name} | Notes: {len(notes):,} "
        f"| Total Words: {total_words:,} | Unique Tags: {len(all_tags):,}",
        "",
        "---",
        "",
    ]

    notes_with_bl = [
        (n, len(backlinks.get(n["note_name"], []))) for n in notes
    ]
    notes_with_bl.sort(key=lambda x: x[1], reverse=True)

    lines.append("## Most Backlinked Notes\n")
    for note, bl_count in notes_with_bl[:SUMMARY_TOP_N]:
        if bl_count == 0:
            break
        lines.append(format_note_block(note, backlinks))
        lines.append("")

    underdeveloped = [
        (n, len(backlinks.get(n["note_name"], [])))
        for n in notes
        if len(backlinks.get(n["note_name"], [])) >= UNDERDEVELOPED_MIN_BACKLINKS
        and n["word_count"] < UNDERDEVELOPED_MAX_WORDS
    ]
    underdeveloped.sort(
        key=lambda x: x[1] / max(x[0]["word_count"], 1), reverse=True
    )

    lines.append("## Linked But Underdeveloped\n")
    if underdeveloped:
        for note, _ in underdeveloped[:SUMMARY_TOP_N]:
            lines.append(format_note_block(note, backlinks))
            lines.append("")
    else:
        lines.append(
            f"No notes match the criteria "
            f"({UNDERDEVELOPED_MIN_BACKLINKS}+ backlinks "
            f"and <{UNDERDEVELOPED_MAX_WORDS} words).\n"
        )

    recently_modified = sorted(
        notes, key=lambda n: n["modified_at"], reverse=True
    )

    lines.append("## Recently Modified\n")
    for note in recently_modified[:SUMMARY_TOP_N]:
        lines.append(format_note_block(note, backlinks))
        lines.append("")

    lines.append("## Vault Breakdown\n")

    status_counts = Counter(n["frontmatter"].get("status", "") for n in notes)
    no_status = status_counts.pop("", 0)
    lines.append("### By Status")
    for status, count in status_counts.most_common():
        lines.append(f"- {status}: {count:,} notes")
    if no_status:
        lines.append(f"- (no status): {no_status:,} notes")
    lines.append("")

    type_counts = Counter(n["frontmatter"].get("type", "") for n in notes)
    no_type = type_counts.pop("", 0)
    lines.append("### By Type")
    for t, count in type_counts.most_common():
        lines.append(f"- {t}: {count:,} notes")
    if no_type:
        lines.append(f"- (no type): {no_type:,} notes")
    lines.append("")

    folder_counts: Counter = Counter()
    for n in notes:
        parts = Path(n["path"]).parts
        top = parts[0] if len(parts) > 1 else "(root)"
        folder_counts[top] += 1
    lines.append("### By Top-Level Folder")
    for folder, count in folder_counts.most_common():
        lines.append(f"- {folder}: {count:,} notes")
    lines.append("")

    tag_counts: Counter = Counter()
    for n in notes:
        for t in n["tags"]:
            tag_counts[t] += 1
    lines.append("### Top 20 Tags")
    for tag, count in tag_counts.most_common(20):
        lines.append(f"- #{tag}: {count:,} notes")
    lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    logging.info(f"Wrote summary to {output_path} ({len(lines)} lines)")


def generate_full_index(
    notes: List[Dict[str, Any]],
    backlinks: Dict[str, List[str]],
    vault_name: str,
    output_path: Path,
) -> None:
    """Generate vault_index_full.md with every note's structural metadata."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    total_words = sum(n["word_count"] for n in notes)

    lines = [
        "# Vault Index (Full)",
        "",
        f"Generated: {now} | Vault: {vault_name} "
        f"| Notes: {len(notes):,} | Total Words: {total_words:,}",
        "",
        "---",
        "",
    ]

    notes_sorted = sorted(
        notes,
        key=lambda n: len(backlinks.get(n["note_name"], [])),
        reverse=True,
    )

    for note in notes_sorted:
        lines.append(format_note_block(note, backlinks))
        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    logging.info(f"Wrote full index to {output_path} ({len(lines)} lines)")


def load_config(config_path: Path) -> dict:
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    return {}


def main():
    parser = argparse.ArgumentParser(
        description="Generate a two-tier vault index for OpenClaw"
    )
    parser.add_argument(
        "--config", default="config.yaml", help="Configuration file path"
    )
    parser.add_argument("--vault-path", help="Override vault path from config")
    parser.add_argument("--output-dir", help="Override output directory from config")
    parser.add_argument("--log-level", default=None, help="Log level")

    args = parser.parse_args()

    config = load_config(Path(args.config))

    vault_path_str = args.vault_path or config.get("vault_path", "")
    output_dir_str = args.output_dir or config.get("index_output_path", "./index")
    log_level = args.log_level or config.get("log_level", "INFO")

    setup_logging(log_level)

    vault_path = Path(vault_path_str)
    if not vault_path.exists():
        logging.error(f"Vault path does not exist: {vault_path}")
        sys.exit(1)

    output_dir = Path(output_dir_str)
    output_dir.mkdir(parents=True, exist_ok=True)

    vault_name = vault_path.name

    logging.info(f"Scanning vault: {vault_path}")
    start = datetime.now()

    notes = scan_vault(vault_path)

    scan_elapsed = (datetime.now() - start).total_seconds()
    logging.info(f"Vault scan completed in {scan_elapsed:.1f}s")

    backlinks = compute_backlinks(notes)
    logging.info(
        f"Computed backlinks: {len(backlinks)} unique targets, "
        f"{sum(len(v) for v in backlinks.values())} total links"
    )

    generate_summary(
        notes, backlinks, vault_name, output_dir / "vault_index_summary.md"
    )
    generate_full_index(
        notes, backlinks, vault_name, output_dir / "vault_index_full.md"
    )

    elapsed = (datetime.now() - start).total_seconds()
    logging.info(f"Index generation complete in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
