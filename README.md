# Fuse Show Creator — pywebview edition

A rebuild of the app using **pywebview** instead of CustomTkinter. The window is
the operating system's native webview (WKWebView on macOS, WebView2 on Windows),
so HiDPI / Retina scaling and click hit-boxes are handled correctly by the
platform — the Tk DPI/click-offset issues are gone.

All the original logic (similarity engine, template copy + FULLSHOW rename,
Dropbox path resolution, "reveal in Finder/Explorer") is unchanged and lives in
`show_logic.py`. Only the interface was rewritten, in HTML/CSS/JS.

## Files
```
app.py            Entry point: hosts the webview and bridges Python ↔ JS
show_logic.py     All non-UI logic (reused as-is)
ui/index.html     Interface: markup, CSS theme, and JS (logo embedded inline)
```

## Run from source
```bash
pip install pywebview
python app.py
```
On Linux you also need a webview backend: `pip install pywebview[qt]` (or `[gtk]`).
macOS and Windows work out of the box.

## How the Python ↔ JS bridge works
- The page calls Python with `pywebview.api.<method>(...)`, which returns a promise.
- Long-running work (the copy) runs on a background thread in Python and streams
  progress back by calling JS functions (`window.onProgress`, `window.onComplete`,
  `window.onError`) via `window.evaluate_js(...)`, so the UI never blocks.
- The folder picker uses pywebview's native `create_file_dialog`.

## Build a standalone app

### macOS (fast-launching .app)
```bash
pip install pyinstaller
pyinstaller --windowed --name "FuseShowCreator" \
  --add-data "ui:ui" \
  app.py
```
Use `--windowed` (a onedir `.app`), **not** `--onefile`. The onefile build
re-extracts the whole runtime to a temp folder on every launch, which is what
caused the ~8-second startup delay. The `.app` lands in `dist/`.

Optional, to avoid the first-launch Gatekeeper scan:
```bash
xattr -cr "dist/FuseShowCreator.app"
codesign --force --deep --sign - "dist/FuseShowCreator.app"
```

### Windows (.exe)
```cmd
pip install pyinstaller
pyinstaller --windowed --name "FuseShowCreator" --add-data "ui;ui" app.py
```
Note the separator is `;` on Windows (`ui;ui`) versus `:` on macOS (`ui:ui`).
Windows 10/11 already include the WebView2 runtime; on older builds, install
Microsoft's free "Evergreen" WebView2 runtime once.

## Notes
- The Year field is a dropdown defaulting to the current year, offering the
  previous year through two years ahead (current − 1 … current + 2).
- **Show Options** card: a **CAD Application** dropdown (AutoCAD / Vectorworks)
  and a **Create show shortcut** checkbox. Both are remembered per user.
- The CAD Application choice controls which CAD folder is copied: selecting
  **AutoCAD** omits the `CAD - VWX` folder, and selecting **Vectorworks** omits
  the `CAD - ACAD` folder. After copying, whichever CAD folder was kept is
  renamed to just `CAD`. Everything else in the template is copied normally.
- When **Create show shortcut** is checked, a **Shortcut Folder** field appears
  in the Folders card. After the show is created, a shortcut to the new show
  folder (named the same as the show) is placed in that folder:
    - Windows: a `.lnk` shortcut file
    - macOS: a Finder alias (deliberately *not* a symlink — Dropbox follows
      symlinks and would duplicate the whole show; a Finder alias is a small file
      Dropbox syncs safely)
    - Linux: a symbolic link
  If the shortcut can't be created, the show is still created and the success
  dialog notes the shortcut problem.
- The default template/active paths are resolved in the background after the
  window appears, so the app opens instantly even if Dropbox is slow to respond.
- If a path can't be found it shows in red; use **Browse** to point it manually.

## Per-user settings memory
The app remembers each user's **Template Folder**, **Active Show Directory**,
**CAD Application**, the **Create show shortcut** checkbox, and the **Shortcut
Folder**, and restores them next launch. Because the program lives in a shared
Dropbox folder used by many people on many machines, these settings are stored
**locally on each machine**, in the OS-standard per-user location — never inside
Dropbox — so there are no sync conflicts and every user/machine keeps its own
preferences:

- macOS:   `~/Library/Application Support/FuseShowCreator/settings.json`
- Windows: `%APPDATA%\FuseShowCreator\settings.json`
- Linux:   `~/.config/FuseShowCreator/settings.json`

On launch, a saved folder is used only if it still exists; otherwise the app falls
back to auto-resolving the default Dropbox path. Settings are saved automatically
whenever you change a folder or the CAD application, and after a successful create.
