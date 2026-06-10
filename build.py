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

# On Windows, auto-generate icon.ico from icon.png if it doesn't exist yet.
if sys.platform != "darwin":
    ico_path = os.path.join(here, "icon.ico")
    svg_path = os.path.join(here, "icon.svg")
    png_path = os.path.join(here, "icon.png")
    try:
        from PIL import Image
        import io

        sizes = [256, 128, 64, 48, 32, 16]
        frames = []

        if os.path.exists(svg_path):
            try:
                import cairosvg
                for size in sizes:
                    png_bytes = cairosvg.svg2png(
                        url=svg_path, output_width=size, output_height=size)
                    frames.append(Image.open(io.BytesIO(png_bytes)).convert("RGBA"))
                print("Generated icon.ico from icon.svg (vector-sharp)")
            except ImportError:
                print("cairosvg not found — falling back to icon.png (install with: pip install cairosvg)")

        if not frames and os.path.exists(png_path):
            src = Image.open(png_path).convert("RGBA")
            for size in sizes:
                frames.append(src.resize((size, size), Image.LANCZOS))
            print("Generated icon.ico from icon.png (raster fallback)")

        if frames:
            frames[0].save(ico_path, format="ICO",
                           append_images=frames[1:],
                           sizes=[(s, s) for s in sizes])
        else:
            print("Warning: neither icon.svg nor icon.png found — no icon embedded")

    except Exception as e:
        print(f"Warning: could not generate icon.ico: {e}")
if sys.platform == "darwin":
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--windowed",
        "--noconfirm",
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
        "--noconfirm",
        "--onefile",
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

# ── 4. Clean up the onedir folder that PyInstaller leaves alongside ────────
#    the .exe / .app — it's the unpacked contents and isn't needed.
import shutil
onedir = os.path.join(here, "dist", "FuseShowCreator")
if os.path.isdir(onedir):
    shutil.rmtree(onedir)
    print("Removed leftover dist/FuseShowCreator folder.")
