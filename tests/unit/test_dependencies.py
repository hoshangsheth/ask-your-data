"""
The runtime dependencies are listed twice: requirements.txt (pip, Docker, CI) and
pyproject.toml (Vercel installs from it). This test fails if the two lists drift apart.
"""

import tomllib

from app.core.config import PROJECT_ROOT


def _requirements() -> set[str]:
    lines = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    return {line.split("#")[0].strip() for line in lines if line.split("#")[0].strip()}


def test_pyproject_matches_requirements():
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert set(pyproject["project"]["dependencies"]) == _requirements()
