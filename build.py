"""
Fuse Show Creator — build script.

Run this instead of pyinstaller directly:
    python build.py

Automatically stamps version.py with today's date (YYYY.MM.DD), launches
PyInstaller with the correct flags for the current platform (including the
app icon), and on macOS patches the generated Info.plist so the system
About dialog shows the correct version instead of 0.0.0.
"""

import subprocess, sys, os, plistlib
from datetime import date

here = os.path.dirname(os.path.abspath(__file__))

# ── 1. Stamp version.py with today's date ─────────────────────────────────
version = date.today().strftime("%Y.%m.%d")
with open(os.path.join(here, "version.py"), "w") as f:
    f.write(f'VERSION = "{version}"\n')
print(f"Version → {version}")

# ── 2. Run PyInstaller ─────────────────────────────────────────────────────
if sys.platform == "darwin":
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--windowed",
        "--name", "FuseShowCreator",
        "--add-data", "ui:ui",
        "--collect-all", "webview",
        "app.py",
    ]
    if os.path.exists(os.path.join(here, "icon.icns")):
        cmd += ["--icon", "icon.icns"]

else:  # Windows
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--windowed",
        "--name", "FuseShowCreator",
        "--add-data", "ui;ui",
        "--collect-all", "webview",
        "app.py",
    ]
    if os.path.exists(os.path.join(here, "icon.ico")):
        cmd += ["--icon", "icon.ico"]

print("Running:", " ".join(cmd))
result = subprocess.run(cmd, cwd=here)
if result.returncode != 0:
    sys.exit(result.returncode)

# ── 3. macOS: patch Info.plist so About dialog shows the real version ──────
if sys.platform == "darwin":
    plist_path = os.path.join(here, "dist", "FuseShowCreator.app",
                              "Contents", "Info.plist")
    if os.path.exists(plist_path):
        with open(plist_path, "rb") as f:
            plist = plistlib.load(f)
        plist["CFBundleShortVersionString"] = version
        plist["CFBundleVersion"] = version
        with open(plist_path, "wb") as f:
            plistlib.dump(plist, f)
        print(f"Info.plist → CFBundleShortVersionString = {version}")

print("Build complete.")
