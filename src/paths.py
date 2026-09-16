"""Central path definitions anchored to the project root instead of the CWD."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def project_path(*parts: str) -> Path:
    """Return a path anchored at the project root, independent of the CWD."""
    return PROJECT_ROOT.joinpath(*parts)
