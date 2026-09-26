"""정적 UI 빌드 후 OS별 실행 파일·문서 ZIP과 해시를 만든다."""

import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(stage: Path):
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--distpath",
            str(stage),
            "packaging/kwa.spec",
        ],
        cwd=ROOT,
        check=True,
    )
    distribution = stage / "kwa"
    for name in (
        "README.md",
        "README.ko.md",
        "LICENSE",
        "config.example.yaml",
    ):
        shutil.copy2(ROOT / name, distribution / name)
    shutil.copytree(
        ROOT / "docs",
        distribution / "docs",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("*TDD*", "*tdd*"),
    )
    shutil.copytree(
        ROOT / "examples",
        distribution / "examples",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "local_config.h"),
    )
    shutil.copytree(
        ROOT / "tests" / "fixtures", distribution / "tests" / "fixtures", dirs_exist_ok=True
    )
    dependencies = []
    for package in metadata.distributions():
        name = package.metadata.get("Name", "unknown")
        if name == "korea-war-alarm":
            continue
        license_text = package.metadata.get("License-Expression") or package.metadata.get(
            "License", "See bundled notice"
        )
        dependencies.append({"name": name, "version": package.version, "license": license_text})
        directory = distribution / "licenses" / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "NOTICE.txt").write_text(
            f"{name} {package.version}\n{license_text}\n", "utf-8"
        )
        for item in package.files or []:
            if item.name.lower().startswith(("license", "copying", "notice")):
                source = Path(package.locate_file(item))
                if source.is_file():
                    shutil.copy2(source, directory / item.name)
    (distribution / "DEPENDENCIES.json").write_text(json.dumps(dependencies, indent=2), "utf-8")
    # 새 staging에서만 ZIP을 생성해 기존 실행 폴더의 데이터가 포함되지 않게 한다.
    shutil.copytree(distribution, ROOT / "dist" / "kwa", dirs_exist_ok=True)
    release = (
        ROOT
        / "dist"
        / f"korea-war-alarm-0.1.0-{platform.system().lower()}-{platform.machine().lower()}.zip"
    )
    with zipfile.ZipFile(release, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in distribution.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(distribution.parent))
    with release.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    release.with_suffix(".zip.sha256").write_text(f"{digest}  {release.name}\n", "ascii")
    print(json.dumps({"artifact": str(release), "sha256": digest, "bytes": release.stat().st_size}))


def main():
    (ROOT / "build").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="release-", dir=ROOT / "build") as temporary:
        build(Path(temporary))


if __name__ == "__main__":
    main()
