from pathlib import Path
import sys
import tomllib

import repopilot

ROOT = Path(__file__).resolve().parents[1]


def test_python_version_is_supported() -> None:
    assert sys.version_info >= (3, 11)


def test_project_metadata_is_present() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)

    assert data["project"]["name"] == "repopilot"
    assert data["project"]["requires-python"] == ">=3.11"


def test_package_skeleton_imports() -> None:
    assert repopilot.__version__ == "0.0.1"
