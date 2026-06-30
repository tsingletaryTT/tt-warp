import os
from pathlib import Path
from typing import Optional

# Registry of all known TT framework environments.
# Each entry describes:
#   venv_path  - path to the virtualenv (used to build the activation snippet)
#   set_vars   - environment variables to export when activating this env
#   unset_vars - environment variables to clear (avoid cross-contamination)
ENVIRONMENTS = {
    "metal": {
        "venv_path": "~/tt-metal/python_env",
        "set_vars": {
            "TT_METAL_HOME": str(Path("~/tt-metal").expanduser()),
            "PYTHONPATH": str(Path("~/tt-metal").expanduser()),
            "LD_LIBRARY_PATH": "/opt/openmpi-v5.0.7-ulfm/lib",
        },
        "unset_vars": [],
    },
    "vllm": {
        "venv_path": "~/tt-metal/build/python_env_vllm",
        "set_vars": {
            "TT_METAL_HOME": str(Path("~/tt-metal").expanduser()),
            "PYTHONPATH": str(Path("~/tt-metal").expanduser()),
            "LD_LIBRARY_PATH": "/opt/openmpi-v5.0.7-ulfm/lib",
        },
        "unset_vars": [],
    },
    "forge": {
        "venv_path": "~/tt-forge-venv",
        "set_vars": {
            "PYTHONPATH": str(Path("~/tt-forge").expanduser()),
        },
        # TT_METAL_HOME must be cleared so Metal's C-extensions are not loaded
        # alongside Forge's incompatible runtime.
        "unset_vars": ["TT_METAL_HOME", "TT_METAL_VERSION"],
    },
    "xla": {
        "venv_path": "~/tt-xla-venv",
        "set_vars": {
            "PJRT_PLUGIN_LIBRARY_PATH": str(
                Path("~/tt-xla/build/lib/libpjrt_tt.so").expanduser()
            ),
            "LD_LIBRARY_PATH": "/opt/openmpi-v5.0.7-ulfm/lib",
        },
        "unset_vars": [],
    },
}

# Maps the final path component of a virtualenv directory to its logical
# environment name.  This is the primary detection heuristic: if $VIRTUAL_ENV
# is set and its basename matches one of these keys, we know which env is live.
_VENV_MARKERS = {
    "python_env": "metal",
    "python_env_vllm": "vllm",
    # QB2 (and other pre-installed Blackhole boxes) ship vLLM in a standalone
    # venv at ~/.tenstorrent-venv rather than under the tt-metal build tree.
    ".tenstorrent-venv": "vllm",
    "tt-forge-venv": "forge",
    "tt-xla-venv": "xla",
}

# Environments that run on the tt-metal runtime and therefore need
# TT_METAL_ARCH_NAME set to the connected board's architecture.
_METAL_BACKED_ENVS = frozenset({"metal", "vllm"})


def _detected_arch() -> Optional[str]:
    """Return the tt-metal arch string for the connected hardware, or None.

    "blackhole" for Blackhole boards (QB2's p300c, p150, …), "wormhole" for
    Wormhole boards (n150/n300/T3K). Imported lazily so this module stays
    cheap to import and easy to monkeypatch in tests.
    """
    from tt_mcp import hardware

    if hardware.is_blackhole():
        return "blackhole"
    if hardware.is_wormhole():
        return "wormhole"
    return None


def _resolve_env(name: str) -> tuple[Path, dict, list]:
    """Resolve (venv_path, set_vars, unset_vars) for *name*.

    Special-cases ``vllm``: a QB2 ships vLLM in ``~/.tenstorrent-venv`` and has
    no tt-metal source tree, so when that venv exists we activate it directly
    and deliberately do NOT export ``TT_METAL_HOME`` (pointing it at the
    source-less ``~/tt-metal`` would mislead the runtime). On a tt-metal build
    machine we fall back to the build-tree venv and the original variables.

    Raises:
        KeyError: if *name* is not in ENVIRONMENTS.
    """
    env = ENVIRONMENTS[name]  # intentionally raises KeyError for unknown names
    if name == "vllm":
        qb2_venv = Path("~/.tenstorrent-venv").expanduser()
        if qb2_venv.exists():
            return qb2_venv, {}, []
    return Path(env["venv_path"]).expanduser(), env["set_vars"], env["unset_vars"]


def detect_active_env() -> Optional[str]:
    """Return the name of the currently active TT environment, or None.

    Detection order:
    1. $VIRTUAL_ENV basename — set by ``source .../bin/activate``; most reliable.
    2. $TT_METAL_HOME presence — fallback for shells that source Metal's env
       without using a traditional virtualenv.
    """
    virtual_env = os.environ.get("VIRTUAL_ENV", "")
    if virtual_env:
        # Path("…/tt-forge-venv").name == "tt-forge-venv"
        stem = Path(virtual_env).name
        if stem in _VENV_MARKERS:
            return _VENV_MARKERS[stem]

    # Fallback: TT_METAL_HOME is exported by Metal's setup scripts even when
    # not using a standard venv.
    if os.environ.get("TT_METAL_HOME"):
        return "metal"

    return None


def get_activation_snippet(name: str, arch: Optional[str] = None) -> str:
    """Return a bash snippet that activates the named TT environment.

    The snippet can be eval'd by a subprocess shell to bring up the correct
    Python environment and all required runtime variables, e.g.:

        subprocess.run(["bash", "-c", get_activation_snippet("metal") + " && python my_script.py"])

    Args:
        name: One of the keys in :data:`ENVIRONMENTS`.
        arch: tt-metal architecture ("blackhole"/"wormhole"). When None, it is
              auto-detected from the connected hardware. Only emitted for
              tt-metal-backed envs (``metal``/``vllm``); Blackhole hardware
              (QB2) requires ``TT_METAL_ARCH_NAME=blackhole``.

    Raises:
        KeyError: if *name* is not in ENVIRONMENTS.
    """
    venv, set_vars, unset_vars = _resolve_env(name)

    lines = [f'source "{venv}/bin/activate"']

    # Unset conflicting variables before exporting new ones so there is no
    # partial state from a previously active environment.
    for var in unset_vars:
        lines.append(f"unset {var}")

    for var, val in set_vars.items():
        lines.append(f'export {var}="{val}"')

    # tt-metal selects its device backend from TT_METAL_ARCH_NAME; without it,
    # Blackhole hardware fails to initialise. Only relevant to metal-backed envs.
    if name in _METAL_BACKED_ENVS:
        resolved_arch = arch if arch is not None else _detected_arch()
        if resolved_arch:
            lines.append(f'export TT_METAL_ARCH_NAME="{resolved_arch}"')

    return "\n".join(lines)
