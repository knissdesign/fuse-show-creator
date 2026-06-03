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


def resource_path(relative: str) -> str:
    """Resolve a path to a bundled resource, working both when running from
    source and when frozen by PyInstaller (which unpacks to sys._MEIPASS)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


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
            def progress(done, total):
                self._js(f"window.onProgress({done}, {total})")
            try:
                count, renamed, errors = L.copy_and_rename(
                    src, dest, show_name, progress)
            except Exception as e:
                self._js("window.onError(%s)" % _jsstr(str(e)))
                return
            if errors:
                msg = (f"{count} files copied, {renamed} item(s) renamed.\n\n"
                       f"{len(errors)} error(s):\n" + "\n".join(errors[:10]))
                self._js("window.onError(%s)" % _jsstr(msg))
                return

            # Optional: create a shortcut to the new show folder.
            shortcut_note = ""
            if make_shortcut:
                err = L.create_shortcut(dest_show, shortcut_dir, show_name)
                shortcut_note = "Shortcut created." if not err else f"Shortcut failed: {err}"

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
    webview.start()


if __name__ == "__main__":
    main()
