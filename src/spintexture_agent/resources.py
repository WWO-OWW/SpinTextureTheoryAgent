from __future__ import annotations

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = Path(__file__).resolve().parents[2]


def resource_dir(name: str) -> Path:
    """Return an installed package resource, with an editable-source fallback."""
    packaged = PACKAGE_ROOT / name
    if packaged.is_dir():
        return packaged
    source = SOURCE_ROOT / name
    if source.is_dir():
        return source
    raise FileNotFoundError(f"SpinTextureTheoryAgent resource directory is missing: {name}")


def resource_file(directory: str, name: str) -> Path:
    path = resource_dir(directory) / name
    if not path.is_file():
        raise FileNotFoundError(
            f"SpinTextureTheoryAgent resource file is missing: {directory}/{name}"
        )
    return path
