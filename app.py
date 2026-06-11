"""
Fuse Show Creator — pywebview shell.

Hosts the HTML/CSS/JS interface in the OS-native webview (WKWebView on macOS,
WebView2 on Windows) and exposes the Python logic in show_logic.py to the page
through a js_api object. Using the native webview means HiDPI / Retina scaling
is handled correctly by the platform — none of the Tk DPI/click-offset issues.

Run during development:
    pip install pywebview
    python app.py
"""

import os
import sys
import threading

import webview

import show_logic as L
from version import VERSION

ICON_B64 = "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"

def resource_path(relative: str) -> str:
    """Resolve a path to a bundled resource, working both when running from
    source and when frozen by PyInstaller (which unpacks to sys._MEIPASS)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def _icon_path() -> str:
    """Write the embedded icon to a temp file in the format the platform needs.
    Windows Forms requires a real .ico file — passing a .png raises
    'Argument must be a picture that can be used as an Icon'.
    macOS and Linux are happy with a .png."""
    import base64, tempfile, io
    try:
        from PIL import Image
        data = base64.b64decode(ICON_B64)
        img  = Image.open(io.BytesIO(data))
        if os.name == "nt":
            suffix = ".ico"
        else:
            suffix = ".png"
        tmp  = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        path = tmp.name
        tmp.close()
        if os.name == "nt":
            # Embed multiple resolutions so Windows can pick the right size
            img.save(path, format="ICO",
                     sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
        else:
            img.save(path, format="PNG")
        return path
    except Exception:
        return ""


class Api:
    """Methods here are callable from JS as `pywebview.api.<name>(...)`.
    Arguments arrive as plain JSON values; return values are JSON-serialized."""

    def __init__(self):
        self._window = None  # set after the window is created

    # ── Startup: resolve paths + restore saved per-user settings ──────────
    def initial_state(self):
        import datetime
        saved = L.load_settings()

        # For each folder: prefer a saved value that still exists; otherwise
        # fall back to resolving the platform default; otherwise keep saved
        # (even if invalid) so the user sees something to correct.
        src = saved.get("src", "") or ""
        if not (src and os.path.isdir(src)):
            resolved = L.resolve_glob_path(*L.SRC_PATTERNS)
            src = resolved or src
        dest = saved.get("dest", "") or ""
        if not (dest and os.path.isdir(dest)):
            resolved = L.resolve_glob_path(*L.DEST_PATTERNS)
            dest = resolved or dest

        cur = datetime.date.today().year
        shortcut_dir = saved.get("shortcut_dir", "") or ""
        return {
            "src":     src,
            "dest":    dest,
            "src_ok":  os.path.isdir(src)  if src  else False,
            "dest_ok": os.path.isdir(dest) if dest else False,
            "make_shortcut": bool(saved.get("make_shortcut", False)),
            "shortcut_dir":  shortcut_dir,
            "shortcut_ok":   os.path.isdir(shortcut_dir) if shortcut_dir else False,
            "current_year":  cur,
            "year_options":  [cur - 1, cur, cur + 1, cur + 2],
            "version":       VERSION,
        }

    # ── Persist the user's choices (template/active dirs + CAD app) ───────
    def save_settings(self, settings):
        return L.save_settings(settings)

    # ── Live similarity check (runs on every debounced keystroke) ─────────
    def find_similar(self, show_name, dest):
        # Returns a list of [folder_name, score] pairs above threshold.
        return [[name, score] for name, score in L.find_similar_folders(show_name, dest)]

    # ── Small validators used by the UI ───────────────────────────────────
    def check_path(self, path):
        return bool(path) and os.path.isdir(path)

    def show_exists(self, dest, show_name):
        return os.path.exists(os.path.join(dest, show_name))

    # ── Native folder picker ──────────────────────────────────────────────
    def pick_folder(self):
        result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        if not result:
            return None
        # pywebview returns a tuple/list of selected paths
        return result[0] if isinstance(result, (list, tuple)) else result

    # ── The main action: copy template + rename FULLSHOW (+ optional shortcut)
    def create_show(self, artist, desc, year, src, dest,
                    make_shortcut=False, shortcut_dir=""):
        """Kicks off the copy on a background thread and streams progress and
        completion back to the page via JS callbacks (onProgress / onComplete /
        onError). Returns immediately so the webview stays responsive."""
        show_name = L.build_show_name(artist, desc, year)
        dest_show = os.path.join(dest, show_name)
        # Both CAD folders are copied as-is. To re-enable per-CAD filtering,
        # restore the cad param and pass L.cad_exclusions/cad_rename_map here.

        def run():
            import time
            start = time.monotonic()

            def progress(done, total):
                self._js(f"window.onProgress({done}, {total})")

            # ── Zero-byte check (Dropbox not fully downloaded) ────────────
            zero_byte = L.find_zero_byte_files(src)
            if zero_byte:
                import json as _json
                self._js(f"window.onZeroByteWarning({_json.dumps(zero_byte)}, {_json.dumps(src)})")
                return

            # ── Copy ──────────────────────────────────────────────────────
            count, renamed, copy_errors = 0, 0, []
            copy_exc: Exception | None = None
            try:
                count, renamed, copy_errors = L.copy_and_rename(
                    src, dest, show_name, progress)
            except Exception as e:
                copy_exc = e

            duration = round(time.monotonic() - start, 2)

            # ── Shortcut (only if copy succeeded cleanly) ─────────────────
            shortcut_created = False
            shortcut_err     = ""
            shortcut_note    = ""
            if copy_exc is None and not copy_errors and make_shortcut:
                shortcut_err     = L.create_shortcut(dest_show, shortcut_dir, show_name)
                shortcut_created = not bool(shortcut_err)
                shortcut_note    = ("Shortcut created." if shortcut_created
                                    else f"Shortcut failed: {shortcut_err}")

            # ── Write provenance metadata ─────────────────────────────────
            # Always attempt this, even on failure, so errors are on disk.
            # Only skip if the destination folder was never created.
            if os.path.isdir(dest_show):
                all_errors = (([str(copy_exc)] if copy_exc else [])
                              + (copy_errors or []))
                L.write_show_meta(
                    dest_show,
                    artist=artist, desc=desc, year=year, show_name=show_name,
                    src=src, dest=dest,
                    make_shortcut=make_shortcut, shortcut_dir=shortcut_dir,
                    shortcut_created=shortcut_created, shortcut_error=shortcut_err,
                    files_copied=count, items_renamed=renamed,
                    copy_errors=all_errors, duration_seconds=duration,
                    success=(copy_exc is None and not copy_errors),
                    version=VERSION,
                )

            # ── Report result to UI ───────────────────────────────────────
            if copy_exc is not None:
                self._js("window.onError(%s)" % _jsstr(str(copy_exc)))
                return
            if copy_errors:
                msg = (f"{count} files copied, {renamed} item(s) renamed.\n\n"
                       f"{len(copy_errors)} error(s):\n"
                       + "\n".join(copy_errors[:10]))
                self._js("window.onError(%s)" % _jsstr(msg))
                return

            self._js("window.onComplete(%s, %s, %d, %d, %s)" % (
                _jsstr(show_name), _jsstr(dest_show), count, renamed,
                _jsstr(shortcut_note)))

        threading.Thread(target=run, daemon=True).start()
        return True

    # ── Success dialog button: reveal folder, then close the app ──────────
    def open_and_quit(self, dest_show):
        L.open_in_file_manager(dest_show)
        # Give the OS a moment to foreground Finder/Explorer before we exit.
        threading.Timer(0.3, self._window.destroy).start()
        return True

    # ── helpers ────────────────────────────────────────────────────────────
    def _js(self, code):
        if self._window is not None:
            try:
                self._window.evaluate_js(code)
            except Exception:
                pass


def _jsstr(s: str) -> str:
    """Encode a Python string as a safe JS string literal."""
    import json
    return json.dumps(s)


def main():
    api = Api()
    window = webview.create_window(
        "Fuse Show Creator",
        url=resource_path(os.path.join("ui", "index.html")),
        js_api=api,
        width=740,
        height=820,
        min_size=(700, 760),
    )
    api._window = window
    webview.start(icon=_icon_path())


if __name__ == "__main__":
    main()
