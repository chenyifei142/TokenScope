"""Build release artifacts for GitHub Releases."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_identity import (
    APP_VERSION,
    MAIN_EXECUTABLE_NAME,
    UPDATER_EXECUTABLE_NAME,
)

DIST_DIR = ROOT / "dist"
MAIN_SPEC = ROOT / "TokenMeter.spec"
UPDATER_SPEC = ROOT / "TokenMeterUpdater.spec"
APP_DIST_DIR = DIST_DIR / "TokenMeter"
UPDATER_DIST_DIR = DIST_DIR / "TokenMeterUpdater"
INSTALLER_SCRIPT = ROOT / "installer" / "TokenMeter.iss"
INSTALLER_OUTPUT_DIR = ROOT / "dist-installer"
INSTALLER_PATH = INSTALLER_OUTPUT_DIR / f"TokenMeter-Setup-v{APP_VERSION}-x64.exe"
SHA_FILE = INSTALLER_OUTPUT_DIR / "SHA256SUMS.txt"
LEGACY_SHA_FILE = DIST_DIR / "SHA256SUMS.txt"


def _run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_sha256_file(paths: list[Path]) -> None:
    lines = [f"{_sha256(path)} *{path.name}" for path in paths]
    SHA_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _smoke_test_main(executable: Path) -> None:
    process = subprocess.Popen([str(executable)], cwd=executable.parent)
    try:
        time.sleep(5)
        if process.poll() not in (None, 0):
            raise RuntimeError(f"{executable.name} exited early with code {process.poll()}")
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        smoke_data = executable.parent / "data"
        if smoke_data.exists():
            # The packaged app correctly creates adjacent data on first launch;
            # smoke-test state must never become installer input.
            shutil.rmtree(smoke_data)


def _smoke_test_updater(executable: Path) -> None:
    subprocess.run([str(executable), "--help"], cwd=executable.parent, check=True)


def build_onedir() -> None:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    INSTALLER_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    INSTALLER_PATH.unlink(missing_ok=True)
    SHA_FILE.unlink(missing_ok=True)
    LEGACY_SHA_FILE.unlink(missing_ok=True)
    _run([sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", str(MAIN_SPEC)])
    _run([sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", str(UPDATER_SPEC)])

    # Reuse the identity constants so build outputs and release asset names stay
    # aligned after repository/branding adjustments.
    main_exe = APP_DIST_DIR / MAIN_EXECUTABLE_NAME
    built_updater_exe = UPDATER_DIST_DIR / UPDATER_EXECUTABLE_NAME
    updater_exe = APP_DIST_DIR / UPDATER_EXECUTABLE_NAME
    if built_updater_exe.exists():
        shutil.copy2(built_updater_exe, updater_exe)
        updater_internal = UPDATER_DIST_DIR / "_internal"
        if updater_internal.exists():
            shutil.copytree(
                updater_internal, APP_DIST_DIR / "_internal", dirs_exist_ok=True
            )
    if not main_exe.exists() or not updater_exe.exists():
        raise FileNotFoundError("PyInstaller did not produce both executables")

def _inno_compiler() -> str | None:
    compiler = shutil.which("iscc") or shutil.which("ISCC.exe")
    if compiler:
        return compiler
    program_files = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    candidates = [Path(program_files) / "Inno Setup 6" / "ISCC.exe"]
    if local_appdata:
        candidates.append(Path(local_appdata) / "Programs" / "Inno Setup 6" / "ISCC.exe")
    return next((str(path) for path in candidates if path.exists()), None)


def build_installer(*, required: bool) -> bool:
    compiler = _inno_compiler()
    if compiler:
        _run([compiler, f"/DMyAppVersion={APP_VERSION}", str(INSTALLER_SCRIPT)])
        if not INSTALLER_PATH.exists():
            raise FileNotFoundError("Inno Setup did not produce the expected installer")
        return True
    if required:
        raise FileNotFoundError("Inno Setup compiler not found")
    print("Inno Setup compiler not found; onedir build completed, installer skipped.")
    return False


def smoke_test() -> None:
    _smoke_test_updater(APP_DIST_DIR / UPDATER_EXECUTABLE_NAME)
    _smoke_test_main(APP_DIST_DIR / MAIN_EXECUTABLE_NAME)


def write_release_checksums(*, required: bool) -> bool:
    if not INSTALLER_PATH.exists():
        if required:
            raise FileNotFoundError("Installer missing; cannot generate release checksums")
        print("Installer missing; SHA256SUMS.txt generation skipped.")
        return False
    _write_sha256_file([INSTALLER_PATH])
    return True


def build_release(*, skip_smoke_test: bool) -> None:
    build_onedir()
    installer_built = build_installer(required=False)
    if not skip_smoke_test:
        smoke_test()
    if installer_built:
        write_release_checksums(required=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build TokenMeter release assets")
    parser.add_argument("--skip-smoke-test", action="store_true")
    parser.add_argument(
        "--stage",
        choices=("all", "onedir", "installer", "smoke", "checksums"),
        default="all",
    )
    parser.add_argument("--require-installer", action="store_true")
    args = parser.parse_args(argv)
    if args.stage == "all":
        build_release(skip_smoke_test=args.skip_smoke_test)
    elif args.stage == "onedir":
        build_onedir()
    elif args.stage == "installer":
        build_installer(required=args.require_installer)
    elif args.stage == "smoke":
        smoke_test()
    else:
        write_release_checksums(required=args.require_installer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
