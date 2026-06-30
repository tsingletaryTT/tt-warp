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

def _warp_dirs() -> list[Path]:
    """Return the Warp config directories to write into.

    Every Warp channel — the Linux stable package (`warp-terminal`), the
    open-source build (`warp`, built via `./script/run`), and preview builds —
    reads its agent config from a single `~/.warp` directory. Warp does not
    document per-channel suffixed dirs (`.warp-oss`, `.warp-dev`), so we write
    to the one documented location. Returned as a list to keep the call sites
    channel-agnostic if Warp ever splits this.

    See: https://docs.warp.dev/terminal/settings/file-locations/
    """
    return [Path.home() / ".warp"]


def _mcp_server_command() -> str:
    """Return the absolute path to tt-mcp-server, falling back to the bare name.

    Warp spawns MCP servers without inheriting the user's full PATH, so a bare
    command name only works if tt-mcp-server is in a system directory.  Prefer
    the absolute path so the correct virtualenv binary is always used.
    """
    cmd = shutil.which("tt-mcp-server")
    return cmd if cmd else "tt-mcp-server"


def _write_mcp_config() -> None:
    command = _mcp_server_command()
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
        servers["tt-hardware"] = {"command": command, "env": {}}
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
        # Warp loads skills from <skills_dir>/<name>/SKILL.md subdirectories.
        for skill_file in _SKILLS_SRC.glob("*.md"):
            skill_subdir = skills_dir / skill_file.stem
            skill_subdir.mkdir(parents=True, exist_ok=True)
            shutil.copy(skill_file, skill_subdir / "SKILL.md")
        click.echo(f"  ✓ Skills installed to {skills_dir}")


@click.group()
def main() -> None:
    pass


def _register_claude_code_mcp() -> None:
    """Register tt-hardware with Claude Code's global MCP config if claude is installed."""
    claude = shutil.which("claude")
    if not claude:
        return
    command = _mcp_server_command()
    result = __import__("subprocess").run(
        [claude, "mcp", "add", "--scope", "user", "tt-hardware", command],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        click.echo(f"  ✓ Claude Code MCP registered: tt-hardware")
    else:
        # Already registered or other harmless error — don't fail the install.
        click.echo(f"  ✓ Claude Code MCP: {result.stderr.strip() or 'already registered'}")


@main.command()
def install() -> None:
    """Wire tt-warp into Warp: MCP config, shell hooks, skills, and Claude Code."""
    click.echo("Installing tt-warp...")
    _TT_WARP_DIR.mkdir(parents=True, exist_ok=True)
    _write_mcp_config()
    _wire_shell_hooks()
    _install_skills()
    _register_claude_code_mcp()

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
