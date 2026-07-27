from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .resources import resource_dir


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_KB_DIR = resource_dir("knowledge_base")


class KnowledgeBase:
    def __init__(self, kb_dir: str | Path = DEFAULT_KB_DIR):
        self.kb_dir = Path(kb_dir)
        self.materials = self._load("materials.yaml")
        self.textures = self._load("textures.yaml")
        self.drives = self._load("drives.yaml")
        self.hamiltonians = self._load("hamiltonians.yaml")
        self.benchmarks = self._load("benchmarks.yaml")

    def _load(self, name: str) -> dict[str, Any]:
        path = self.kb_dir / name
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def material(self, key: str) -> dict[str, Any]:
        return self.materials[key]

    def texture(self, key: str) -> dict[str, Any]:
        return self.textures[key]

    def drive(self, key: str | None) -> dict[str, Any] | None:
        if key is None:
            return None
        return self.drives[key]
