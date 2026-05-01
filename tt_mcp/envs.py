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
    "tt-forge-venv": "forge",
    "tt-xla-venv": "xla",
}


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


def get_activation_snippet(name: str) -> str:
    """Return a bash snippet that activates the named TT environment.

    The snippet can be eval'd by a subprocess shell to bring up the correct
    Python environment and all required runtime variables, e.g.:

        subprocess.run(["bash", "-c", get_activation_snippet("metal") + " && python my_script.py"])

    Raises:
        KeyError: if *name* is not in ENVIRONMENTS.
    """
    env = ENVIRONMENTS[name]  # intentionally raises KeyError for unknown names
    venv = Path(env["venv_path"]).expanduser()

    lines = [f'source "{venv}/bin/activate"']

    # Unset conflicting variables before exporting new ones so there is no
    # partial state from a previously active environment.
    for var in env["unset_vars"]:
        lines.append(f"unset {var}")

    for var, val in env["set_vars"].items():
        lines.append(f'export {var}="{val}"')

    return "\n".join(lines)
