"""
tt-warp CLI — install and sync commands.

  tt-warp install   Wire MCP config, shell hooks, and skills into Warp
  tt-warp sync      Fetch knowledge corpus from upstream TT sources
"""
from __future__ import annotations
import json
import shutil
import sys
import time
from pathlib import Path

import click

from tt_mcp import hardware
from tt_mcp.knowledge.db import KnowledgeDB
from tt_mcp.knowledge.sync import sync_lessons

_TT_WARP_DIR = Path("~/.tt-warp").expanduser()
_SKILLS_SRC = Path(__file__).parent.parent / "skills"
_SHELL_SRC = Path(__file__).parent.parent / "shell" / "tt-warprc"

# Map Warp channel binary names to their config directory names.
# Stable and Preview share ~/.warp; OSS/Dev/Local use suffixed directories.
_WARP_CHANNEL_BINS: dict[str, str] = {
    "warp":         ".warp",
    "warp-oss":     ".warp-oss",
    "warp-dev":     ".warp-dev",
    "warp-preview": ".warp",
}


def _warp_dirs() -> list[Path]:
    """Return config dirs for every Warp channel binary found in PATH.

    Always includes ~/.warp as the baseline. Deduplicates so stable and
    preview (which share the same dir) only appear once.
    """
    home = Path.home()
    seen: set[Path] = set()
    dirs: list[Path] = []
    for binary, dirname in _WARP_CHANNEL_BINS.items():
        if shutil.which(binary):
            d = home / dirname
            if d not in seen:
                seen.add(d)
                dirs.append(d)
    # Always include the baseline dir even if no binary was found.
    baseline = home / ".warp"
    if baseline not in seen:
        dirs.append(baseline)
    return dirs


def _write_mcp_config() -> None:
    for warp_dir in _warp_dirs():
        mcp_path = warp_dir / ".mcp.json"
        warp_dir.mkdir(parents=True, exist_ok=True)
        config = {}
        if mcp_path.exists():
            try:
                config = json.loads(mcp_path.read_text())
            except json.JSONDecodeError:
                pass
        servers = config.setdefault("mcpServers", {})
        servers["tt-hardware"] = {"command": "tt-mcp-server", "env": {}}
        mcp_path.write_text(json.dumps(config, indent=2))
        click.echo(f"  ✓ MCP config written to {mcp_path}")


def _wire_shell_hooks() -> None:
    rc_line = f'\n# tt-warp shell integration\nsource "{_TT_WARP_DIR}/tt-warprc"\n'
    target = _TT_WARP_DIR / "tt-warprc"
    _TT_WARP_DIR.mkdir(parents=True, exist_ok=True)
    if _SHELL_SRC.exists():
        shutil.copy(_SHELL_SRC, target)
    for rc_file in [Path("~/.bashrc").expanduser(), Path("~/.zshrc").expanduser()]:
        if rc_file.exists():
            content = rc_file.read_text()
            if "tt-warp shell integration" not in content:
                rc_file.write_text(content + rc_line)
                click.echo(f"  ✓ Shell hook added to {rc_file}")


def _install_skills() -> None:
    if not _SKILLS_SRC.exists():
        return
    for warp_dir in _warp_dirs():
        skills_dir = warp_dir / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        for skill_file in _SKILLS_SRC.glob("*.md"):
            shutil.copy(skill_file, skills_dir / skill_file.name)
        click.echo(f"  ✓ Skills installed to {skills_dir}")


@click.group()
def main() -> None:
    pass


@main.command()
def install() -> None:
    """Wire tt-warp into Warp: MCP config, shell hooks, skills."""
    click.echo("Installing tt-warp...")
    _TT_WARP_DIR.mkdir(parents=True, exist_ok=True)
    _write_mcp_config()
    _wire_shell_hooks()
    _install_skills()

    hw = hardware.detect_hardware()
    if hw:
        mesh = hardware.get_mesh_device()
        click.echo(f"\n  Hardware detected: {hw['count']}x {hw['primary_type']} ({mesh})")
    else:
        click.echo("\n  No TT hardware detected (tt-smi not found or no devices)")

    click.echo("\nDone. Run `tt-warp sync` to fetch the knowledge corpus.")
    click.echo("Then restart your shell: source ~/.bashrc")


@main.command()
@click.option("--source", default="all",
              type=click.Choice(["lessons", "docs", "all"]),
              help="Which sources to sync")
@click.option("--embed", is_flag=True, default=False,
              help="Re-embed chunks on local TT hardware (Phase 2)")
def sync(source: str, embed: bool) -> None:
    """Fetch knowledge corpus from tt-vscode-toolkit and tenstorrent.github.io."""
    db_path = _TT_WARP_DIR / "knowledge" / "knowledge.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = KnowledgeDB(db_path)

    if source in ("lessons", "all"):
        click.echo("Syncing tt-vscode-toolkit lessons...")
        n = sync_lessons(db)
        click.echo(f"  ✓ Indexed {n} lessons")

    if embed:
        click.echo("  --embed: Phase 2 embeddings not yet implemented")

    db.close()
    click.echo(f"\nKnowledge corpus updated at {db_path}")


if __name__ == "__main__":
    main()
