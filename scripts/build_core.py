"""Build the standalone Python core and place it where Tauri expects it.

The result is a single executable named ``funpay-monitor-core-<target-triple>``
inside ``frontend/src-tauri/binaries``. Tauri strips the target triple when it
bundles the file, so the desktop shell can start it as a sidecar.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BINARIES = ROOT / "frontend" / "src-tauri" / "binaries"
FRONTEND_DIST = ROOT / "frontend" / "dist"
NAME = "funpay-monitor-core"

#: Modules that are only used by the VK bot and would double the bundle size.
EXCLUDES = [
    "matplotlib",
    "numpy",
    "pandas",
    "PIL",
    "tkinter",
    "vkbottle",
    "app.bot",
    "app.worker",
]


def rust_target_triple() -> str:
    """Return the host triple reported by rustc, or a platform default."""
    rustc = shutil.which("rustc") or str(Path.home() / ".cargo" / "bin" / "rustc")
    try:
        output = subprocess.run(
            [rustc, "-vV"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        output = ""
    for line in output.splitlines():
        if line.startswith("host: "):
            return line.split(": ", 1)[1].strip()
    if sys.platform == "win32":
        return "x86_64-pc-windows-msvc"
    if sys.platform == "darwin":
        return "aarch64-apple-darwin"
    return "x86_64-unknown-linux-gnu"


def main() -> None:
    if not (FRONTEND_DIST / "index.html").is_file():
        npm = shutil.which("npm")
        if npm is None:
            raise SystemExit(
                "frontend/dist is missing; run `npm install && npm run build` in frontend/"
            )
        subprocess.run([npm, "--prefix", str(ROOT / "frontend"), "run", "build"], check=True)

    BINARIES.mkdir(parents=True, exist_ok=True)
    work = ROOT / "build" / "core"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        NAME,
        "--paths",
        str(ROOT),
        "--distpath",
        str(work / "dist"),
        "--workpath",
        str(work / "work"),
        "--specpath",
        str(work),
        "--collect-submodules",
        "uvicorn",
        "--hidden-import",
        "aiosqlite",
        "--add-data",
        f"{FRONTEND_DIST}{os.pathsep}frontend/dist",
    ]
    for module in EXCLUDES:
        command += ["--exclude-module", module]
    command.append(str(ROOT / "scripts" / "core_entry.py"))

    subprocess.run(command, check=True, cwd=ROOT)

    suffix = ".exe" if sys.platform == "win32" else ""
    built = work / "dist" / f"{NAME}{suffix}"
    target = BINARIES / f"{NAME}-{rust_target_triple()}{suffix}"
    shutil.copy2(built, target)
    target.chmod(0o755)
    print(f"Sidecar ready: {target}")


if __name__ == "__main__":
    main()
