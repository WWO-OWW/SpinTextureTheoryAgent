from pathlib import Path
from shutil import copy2, copytree

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py


ROOT = Path(__file__).resolve().parent


class build_py(_build_py):
    """Copy canonical non-Python runtime resources into the wheel."""

    def run(self):
        super().run()
        package_root = Path(self.build_lib) / "spintexture_agent"
        copytree(
            ROOT / "knowledge_base",
            package_root / "knowledge_base",
            dirs_exist_ok=True,
        )
        wolfram_root = package_root / "mathematica"
        wolfram_root.mkdir(parents=True, exist_ok=True)
        copy2(
            ROOT / "mathematica" / "SpinTextureTheory.wl",
            wolfram_root / "SpinTextureTheory.wl",
        )
        copy2(ROOT / "LICENSE", package_root / "LICENSE")


setup(cmdclass={"build_py": build_py})
