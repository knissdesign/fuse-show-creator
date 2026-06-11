"""
Fuse Show Creator — core logic (UI-agnostic).

This module contains everything that is NOT user interface: the similarity
engine, default-path resolution, the copy + FULLSHOW rename routine, and the
"reveal in file manager" helper. It is imported by app.py (the pywebview shell)
and has no dependency on any GUI toolkit.
"""

import os, re, glob, shutil, math, sys, subprocess, json, platform, getpass, datetime, time
from collections import Counter


# ── Platform defaults ──────────────────────────────────────────────────────

IS_MAC = sys.platform == "darwin"

# Candidate path patterns per platform. These are resolved lazily in a
# background thread AFTER the window appears, because globbing into a Dropbox /
# CloudStorage mount can stall for a moment while the cloud folder is resolved
# — doing it at import time made the app slow to open.
if IS_MAC:
    SRC_PATTERNS = (
        "~/Fuse Technical Group Dropbox/*/Projects/Library/Active/TEMPLATES/NEW SHOW",
        "~/Library/CloudStorage/Dropbox-FuseTechnicalGroup/*/Projects/Library/TEMPLATES/NEW SHOW",
    )
    DEST_PATTERNS = (
        "~/Fuse Technical Group Dropbox/*/Projects/Shows/Active/",
        "~/Library/CloudStorage/Dropbox-FuseTechnicalGroup/*/Projects/Shows/Active/",
    )
else:
    SRC_PATTERNS  = (r"Z:/TEMPLATES/NEW SHOW",)
    DEST_PATTERNS = (r"Y:/",)

def resolve_glob_path(*patterns: str) -> str:
    """Try each glob pattern in order; return first match, or first expanded
    literal pattern if it has no wildcard, or '' if nothing resolves."""
    for pattern in patterns:
        expanded = os.path.expanduser(pattern)
        if any(ch in expanded for ch in "*?["):
            matches = glob.glob(expanded)
            if matches:
                return matches[0]
        elif os.path.exists(expanded):
            return expanded
    # Fall back to the first literal (non-wildcard) pattern so the user still
    # sees a sensible default they can correct, even if it doesn't exist yet.
    for pattern in patterns:
        expanded = os.path.expanduser(pattern)
        if not any(ch in expanded for ch in "*?["):
            return expanded
    return ""


def truncate_path(full_path: str) -> str:
    """Show only the last two path components for display."""
    if not full_path:
        return ""
    parts = full_path.replace("\\", "/").rstrip("/").split("/")
    return "/" + "/".join(parts[-2:]) if len(parts) >= 2 else full_path


# ── Similarity Engine (artist-weighted) ───────────────────────────────────

SIMILARITY_WARN_THRESHOLD = 0.50

# Common non-artist tokens to down-weight
COMMON_TOKENS = {"tour", "world", "eu", "us", "north", "south", "east", "west",
                 "america", "europe", "arena", "stadium", "show", "live", "concert",
                 "the", "a", "an", "and", "of", "in", "at", "on"}

def tokenize(text: str) -> list:
    return re.sub(r"[^a-z0-9\s]", "", text.lower()).split()

def ngrams(tokens: list, n: int) -> list:
    return [tuple(tokens[i:i+n]) for i in range(len(tokens) - n + 1)]

def jaccard(a: set, b: set) -> float:
    u = a | b
    return len(a & b) / len(u) if u else (1.0 if not a and not b else 0.0)

def token_frequency_score(ta: list, tb: list) -> float:
    fa, fb = Counter(ta), Counter(tb)
    dot = sum(fa[t] * fb[t] for t in set(fa) | set(fb))
    ma  = math.sqrt(sum(v**2 for v in fa.values()))
    mb  = math.sqrt(sum(v**2 for v in fb.values()))
    return dot / (ma * mb) if ma and mb else 0.0

def initials_of(tokens: list) -> str:
    return "".join(t[0] for t in tokens if t)

def abbreviation_score(a: str, b: str) -> float:
    """
    Strict initialism check between artist portions of two show names.
    Returns 1.0 only when one side is a SINGLE short token whose letters
    exactly spell the first letters of the other side's significant tokens.

    Example that SHOULD match:
        'NK Tour 2026'  vs  'Noah Kahan Tour 2026'
        -> 'nk' == initials(['noah','kahan']) == 'nk'  -> 1.0

    Examples that must NOT match (these broke the old substring logic):
        'Lany World 2026' vs 'Jeezy LV 2026'   -> 0.0
        'Lany World 2026' vs 'Mitski LA 2026'  -> 0.0

    Years/digits are excluded so they can't contaminate the initials.
    """
    sig_a = [t for t in tokenize(a) if t not in COMMON_TOKENS and not t.isdigit()]
    sig_b = [t for t in tokenize(b) if t not in COMMON_TOKENS and not t.isdigit()]
    if not sig_a or not sig_b:
        return 0.0

    def is_initialism(abbr_toks, full_toks) -> float:
        # The abbreviation must be exactly one short token (2-5 chars)
        if len(abbr_toks) != 1:
            return 0.0
        abbr = abbr_toks[0]
        if not (2 <= len(abbr) <= 5):
            return 0.0
        # The full side must have at least two tokens to abbreviate
        if len(full_toks) < 2:
            return 0.0
        # Exact match of the abbreviation to the full side's initials
        return 1.0 if abbr == initials_of(full_toks) else 0.0

    return max(is_initialism(sig_a, sig_b), is_initialism(sig_b, sig_a))

def artist_token_score(a: str, b: str) -> float:
    """
    Compare only the significant (non-common) tokens — i.e. the artist portion.
    'Lany Tour 2026' vs 'BTS Tour 2026' should score low here.
    'Lany Tour 2026' vs 'Lany World Tour 2026' should score high.
    """
    ta = [t for t in tokenize(a) if t not in COMMON_TOKENS and not t.isdigit()]
    tb = [t for t in tokenize(b) if t not in COMMON_TOKENS and not t.isdigit()]
    if not ta or not tb:
        return 0.0
    return jaccard(set(ta), set(tb))

def year_match(a: str, b: str) -> float:
    ya = set(re.findall(r"\b\d{4}\b", a))
    yb = set(re.findall(r"\b\d{4}\b", b))
    if not ya or not yb:
        return 0.5   # neutral if no year present
    return 1.0 if ya & yb else 0.0

def similarity_score(a: str, b: str) -> float:
    """
    Weighted similarity:
      45%  effective artist (direct token overlap OR abbreviation as proxy)
      20%  abbreviation / initials match
      10%  full token bigram overlap
      15%  cosine TF on all tokens
      10%  year match bonus
    When abbreviation fires strongly (e.g. 'NK' == initials of 'Noah Kahan'),
    it acts as a substitute artist signal so the total score reaches threshold.
    Hard gate: if no artist signal at all, cap at 0.25 to avoid
    pure-descriptor matches like 'BTS Tour 2026' matching 'Lany Tour 2026'.
    """
    ta, tb = tokenize(a), tokenize(b)
    artist = artist_token_score(a, b)
    abbr   = abbreviation_score(a, b)
    bigram = jaccard(set(ngrams(ta, 2)), set(ngrams(tb, 2)))
    cos    = token_frequency_score(ta, tb)
    yr     = year_match(a, b)

    # Use abbreviation as a proxy for artist when direct overlap is zero
    effective_artist = max(artist, abbr * 0.85)

    raw = (0.45 * effective_artist
         + 0.20 * abbr
         + 0.10 * bigram
         + 0.15 * cos
         + 0.10 * yr)

    if effective_artist < 0.15:
        raw = min(raw, 0.25)

    return round(raw, 4)

def find_similar_folders(show_name: str, dest_dir: str) -> list:
    if not show_name.strip() or not os.path.isdir(dest_dir):
        return []
    results = [(e.name, similarity_score(show_name, e.name))
               for e in os.scandir(dest_dir) if e.is_dir()]
    return sorted([(n, s) for n, s in results if s >= SIMILARITY_WARN_THRESHOLD],
                  key=lambda x: x[1], reverse=True)


# ── File Operations ────────────────────────────────────────────────────────

def build_show_name(artist: str, desc: str, year: str) -> str:
    """Build the show folder name, omitting any empty parts."""
    return ' '.join(p.strip() for p in [artist, desc, year] if p.strip())

# ── CAD folder exclusion / rename — currently disabled ────────────────────────
# Both CAD folders (CAD - ACAD and CAD - VWX) are copied as-is.
# Re-enable these functions and wire them back into app.py / create_show()
# if you want to restore per-CAD-app filtering and the rename to "CAD".
#
# def cad_exclusions(cad: str) -> list:
#     """Folder name(s) to skip when copying, based on the chosen CAD application.
#     AutoCAD keeps 'CAD - ACAD' and drops 'CAD - VWX'; Vectorworks the reverse."""
#     if cad == "AutoCAD":
#         return ["CAD - VWX"]
#     if cad == "Vectorworks":
#         return ["CAD - ACAD"]
#     return []
#
# def cad_rename_map(cad: str) -> dict:
#     """After copying, the CAD folder that WAS kept is renamed to just 'CAD'."""
#     if cad == "AutoCAD":
#         return {"CAD - ACAD": "CAD"}
#     if cad == "Vectorworks":
#         return {"CAD - VWX": "CAD"}
#     return {}
# ─────────────────────────────────────────────────────────────────────────────

def open_in_file_manager(path: str) -> None:
    """Reveal a folder in the OS file manager (Finder / Explorer / xdg)."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        elif os.name == "nt":
            os.startfile(path)            # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", path], check=False)
    except Exception:
        pass


def _as_quote(s: str) -> str:
    """Quote a string as an AppleScript double-quoted literal."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _create_lnk(target: str, link_path: str) -> str:
    """
    Create a Windows .lnk shortcut to a folder using pylnk3.
    pylnk3 is a pure-Python library that handles the .lnk binary format
    correctly without needing COM or WScript.Shell — both of which silently
    fail in frozen PyInstaller apps running alongside WebView2.

    Requires: pip install pylnk3  (bundled automatically by PyInstaller)
    """
    import datetime

    try:
        import pylnk3
    except ImportError:
        return ("pylnk3 not installed. Run: pip install pylnk3  "
                "then rebuild the app.")

    target = os.path.normpath(target).replace('/', '\\')

    if len(target) < 3 or target[1] != ':':
        return f"Could not parse drive letter from path: {target!r}"

    drive_str   = target[:2]              # e.g. "Y:"
    folder_name = target.rsplit('\\', 1)[-1]

    now     = datetime.datetime.now()
    segment = pylnk3.PathSegmentEntry()
    segment.type       = pylnk3.TYPE_FOLDER
    segment.file_size  = 0
    segment.short_name = folder_name
    segment.full_name  = folder_name
    segment.created    = now
    segment.modified   = now
    segment.accessed   = now

    lnk = pylnk3.Lnk()
    lnk.shell_item_id_list       = pylnk3.LinkTargetIDList()
    lnk.shell_item_id_list.items = [
        pylnk3.RootEntry(pylnk3.ROOT_MY_COMPUTER),
        pylnk3.DriveEntry(drive_str),
        segment,
    ]
    lnk.work_dir = target

    try:
        if os.path.lexists(link_path):
            os.remove(link_path)
        lnk.save(link_path)
        return ''
    except Exception as e:
        return str(e)


def _set_hidden(path: str) -> None:
    """Set the hidden file attribute on Windows so the file is invisible in
    Explorer.  On macOS/Linux the leading dot already handles this."""
    if os.name != "nt":
        return
    try:
        import ctypes
        FILE_ATTRIBUTE_HIDDEN = 0x02
        existing = ctypes.windll.kernel32.GetFileAttributesW(path)  # type: ignore
        ctypes.windll.kernel32.SetFileAttributesW(                   # type: ignore
            path, existing | FILE_ATTRIBUTE_HIDDEN)
    except Exception:
        pass


def _get_unc_path(path: str) -> str:
    """On Windows, try to resolve a mapped drive letter (e.g. Y:\\) to its
    underlying UNC path (e.g. \\\\server\\share).  Returns '' if the path
    is not on a mapped drive or the resolution fails."""
    if os.name != "nt" or len(path) < 2 or path[1] != ":":
        return ""
    try:
        import ctypes
        drive = path[:2] + "\\"
        buf = ctypes.create_unicode_buffer(512)
        size = ctypes.c_ulong(512)
        if ctypes.windll.mpr.WNetGetConnectionW(drive, buf, ctypes.byref(size)) == 0:  # type: ignore
            return buf.value
    except Exception:
        pass
    return ""


def write_show_meta(
    dest_show: str,
    *,
    artist: str,
    desc: str,
    year: str,
    show_name: str,
    src: str,
    dest: str,
    make_shortcut: bool,
    shortcut_dir: str,
    shortcut_created: bool,
    shortcut_error: str,
    files_copied: int,
    items_renamed: int,
    copy_errors: list,
    duration_seconds: float,
    success: bool,
    version: str,
) -> None:
    """
    Write (or append to) a hidden .show_meta.json provenance file inside the
    newly-created show folder.  Each call appends a new entry to the top-level
    JSON array so the file accumulates a history if the folder is ever re-built.

    The file is hidden on both macOS (leading dot) and Windows (hidden
    attribute set after writing).  A write failure is silently swallowed —
    metadata logging should never prevent a show from being created.
    """
    meta_path = os.path.join(dest_show, ".show_meta.json")

    # ── Timestamps ────────────────────────────────────────────────────────
    now_utc   = datetime.datetime.now(datetime.timezone.utc)
    now_local = now_utc.astimezone()
    timestamp = {
        "utc":      now_utc.isoformat(),
        "local":    now_local.isoformat(),
        "timezone": now_local.tzname() or "",
    }

    # ── Machine identity ──────────────────────────────────────────────────
    try:
        user = getpass.getuser()
    except Exception:
        user = os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"

    created_by = {
        "user":     user,
        "hostname": platform.node(),
        "os":       f"{platform.system()} {platform.release()}".strip(),
    }

    # ── Network drive UNC resolution (Windows only) ───────────────────────
    src_unc  = _get_unc_path(src)
    dest_unc = _get_unc_path(dest)
    network  = {}
    if src_unc:
        network["template_unc"] = src_unc
    if dest_unc:
        network["dest_unc"] = dest_unc

    # ── Assemble entry ────────────────────────────────────────────────────
    entry = {
        "success":   success,
        "timestamp": timestamp,
        "created_by": created_by,
        "app": {
            "name":    "Fuse Show Creator",
            "version": version,
        },
        "show": {
            "name":        show_name,
            "artist":      artist,
            "description": desc,
            "year":        year,
        },
        "settings": {
            "template_dir":     src,
            "active_show_dir":  dest,
            "shortcut_created": shortcut_created,
            "shortcut_dir":     shortcut_dir if make_shortcut else "",
            "shortcut_error":   shortcut_error,
        },
        "copy_stats": {
            "files_copied":    files_copied,
            "items_renamed":   items_renamed,
            "duration_seconds": duration_seconds,
            "errors":          copy_errors,
        },
    }
    if network:
        entry["network"] = network

    # ── Append to existing file, or start a new array ─────────────────────
    entries: list = []
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            entries = existing if isinstance(existing, list) else [existing]
        except Exception:
            entries = []

    entries.append(entry)

    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
        _set_hidden(meta_path)
    except Exception:
        pass   # metadata write failure must never crash the app


def create_shortcut(target: str, shortcut_dir: str, name: str) -> str:
    """
    Create a native shortcut to the `target` folder inside `shortcut_dir`,
    named `name`. Returns '' on success or an error message on failure.

    Platform behavior:
      - Windows: a .lnk file created via pylnk3 (pure Python, no COM).
                 Opens with the user's default file manager.
      - macOS:   a Finder alias (Dropbox treats it as a file, unlike a symlink
                 which Dropbox would follow and duplicate the whole show).
      - Linux:   a symbolic link.
    """
    try:
        if not os.path.isdir(shortcut_dir):
            return f"Shortcut folder does not exist: {shortcut_dir}"

        if os.name == "nt":
            link = os.path.join(shortcut_dir, name + ".lnk")
            return _create_lnk(target, link)

        elif sys.platform == "darwin":
            link = os.path.join(shortcut_dir, name)
            if os.path.lexists(link):
                try:
                    os.remove(link)
                except Exception:
                    pass
            r = subprocess.run(
                ["osascript",
                 "-e", 'tell application "Finder"',
                 "-e", f"set a to make alias file to POSIX file {_as_quote(target)} "
                       f"at POSIX file {_as_quote(shortcut_dir)}",
                 "-e", f"set name of a to {_as_quote(name)}",
                 "-e", "end tell"],
                capture_output=True, text=True)
            if r.returncode != 0:
                # Fall back to a symlink if the Finder alias couldn't be made.
                try:
                    os.symlink(target, link)
                    return ""
                except Exception as e:
                    return (r.stderr or "").strip() or str(e)
            return ""

        else:
            link = os.path.join(shortcut_dir, name)
            if os.path.lexists(link):
                os.remove(link)
            os.symlink(target, link)
            return ""

    except Exception as e:
        return str(e)


def _set_birthtime_macos(path: str, now: float) -> None:
    """Set the birthtime (Date Created) on macOS using setattrlist(2).
    os.utime() only covers atime/mtime; birthtime needs a direct syscall."""
    try:
        import ctypes, struct
        libc = ctypes.CDLL(None, use_errno=True)   # libSystem on macOS

        ATTR_BIT_MAP_COUNT = 5
        ATTR_CMN_CRTIME    = 0x00000200

        # struct attrlist (24 bytes):
        #   u_short bitmapcount, u_short reserved, u_int32_t commonattr,
        #   u_int32_t volattr, u_int32_t dirattr, u_int32_t fileattr, u_int32_t forkattr
        al = struct.pack('=HHIIIII',
                         ATTR_BIT_MAP_COUNT, 0, ATTR_CMN_CRTIME, 0, 0, 0, 0)

        # struct timespec (16 bytes on 64-bit macOS):
        #   __darwin_time_t tv_sec (8 bytes), long tv_nsec (8 bytes)
        ts = struct.pack('=qq', int(now), int((now % 1) * 1_000_000_000))

        al_buf = ctypes.create_string_buffer(al)
        ts_buf = ctypes.create_string_buffer(ts)

        libc.setattrlist(
            path.encode('utf-8'), al_buf,
            ts_buf, ctypes.c_size_t(len(ts)),
            ctypes.c_ulong(0)
        )
    except Exception:
        pass


def _set_file_times_windows(path: str, now: float) -> None:
    """Set creation time AND last-write time on Windows using SetFileTime.

    os.utime() opens with GENERIC_WRITE internally, which Dropbox / mapped
    network drives often refuse.  Opening with FILE_WRITE_ATTRIBUTES (which
    is all SetFileTime actually needs) succeeds where os.utime silently fails,
    explaining why Created updated but Modified did not.  We set both in one
    handle open so FILE_FLAG_BACKUP_SEMANTICS (required for directories) only
    needs to be applied once.
    """
    try:
        import ctypes, ctypes.wintypes as wt

        # Convert Unix timestamp → Windows FILETIME
        # (100-nanosecond intervals since 1601-01-01 UTC)
        EPOCH_AS_FILETIME = 116_444_736_000_000_000
        ft_val = int(now * 10_000_000) + EPOCH_AS_FILETIME

        class FILETIME(ctypes.Structure):
            _fields_ = [('dwLowDateTime',  wt.DWORD),
                        ('dwHighDateTime', wt.DWORD)]

        ft  = FILETIME(ft_val & 0xFFFFFFFF, ft_val >> 32)
        k32 = ctypes.windll.kernel32          # type: ignore

        # FILE_FLAG_BACKUP_SEMANTICS is required to open a directory handle
        handle = k32.CreateFileW(
            path,
            0x0100,       # FILE_WRITE_ATTRIBUTES
            0x0007,       # FILE_SHARE_READ | WRITE | DELETE
            None,
            3,            # OPEN_EXISTING
            0x02000000,   # FILE_FLAG_BACKUP_SEMANTICS (required for dirs)
            None
        )
        if handle == ctypes.c_void_p(-1).value:
            return
        try:
            # SetFileTime(hFile, lpCreationTime, lpLastAccessTime, lpLastWriteTime)
            # Set creation time and last-write time; leave last-access as-is.
            k32.SetFileTime(handle, ctypes.byref(ft), None, ctypes.byref(ft))
        finally:
            k32.CloseHandle(handle)
    except Exception:
        pass


def _reset_timestamps(path: str) -> None:
    """Reset atime, mtime, and birth/creation time to now.
    On Windows we skip os.utime entirely — it uses GENERIC_WRITE internally
    which network shares often deny, causing silent failure.  SetFileTime
    with FILE_WRITE_ATTRIBUTES (used by _set_file_times_windows) is what
    the filesystem actually requires and handles all three timestamps."""
    now = time.time()
    if sys.platform == 'darwin':
        try:
            os.utime(path, None)    # atime + mtime
        except Exception:
            pass
        _set_birthtime_macos(path, now)
    elif os.name == 'nt':
        _set_file_times_windows(path, now)   # creation + last-write via SetFileTime
    else:
        try:
            os.utime(path, None)
        except Exception:
            pass


def find_zero_byte_files(src: str) -> list:
    """Return relative paths of any 0-byte files under src (Dropbox placeholders)."""
    result = []
    for root, _, files in os.walk(src):
        for f in files:
            full = os.path.join(root, f)
            try:
                if os.path.getsize(full) == 0:
                    result.append(os.path.relpath(full, src))
            except OSError:
                pass
    return result


def copy_and_rename(src: str, dest_dir: str, show_name: str,
                    progress_cb=None, exclude_dirs=None, rename_dirs=None) -> tuple:
    """
    Copy the ENTIRE 'NEW SHOW' template tree (every file and folder,
    including empty ones) into dest_dir, naming the copied root folder
    after show_name. Then rename any file or folder whose name contains
    'FULLSHOW' so that 'FULLSHOW' is replaced with show_name.

    `exclude_dirs` is an optional collection of folder NAMES to skip entirely
    (matched by basename at any depth) — used to omit the CAD folder that
    doesn't apply to the selected CAD application.

    `rename_dirs` is an optional {old_name: new_name} map applied to folders by
    exact basename after copying — used to rename the kept CAD folder to 'CAD'.

    Returns (files_copied, folders_renamed, errors).
    """
    exclude = set(exclude_dirs or ())
    renames = dict(rename_dirs or {})
    dest_show = os.path.join(dest_dir, show_name)
    if os.path.exists(dest_show):
        raise FileExistsError(f'"{show_name}" already exists in destination.')

    # Count files up front for progress reporting, skipping excluded folders.
    total_files = 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in exclude]   # don't descend/count them
        total_files += len(files)

    counter = {"n": 0}
    errors  = []

    def _copy(s, d):
        try:
            shutil.copy2(s, d)
            _reset_timestamps(d)    # reset atime, mtime, and birth/creation time
        except Exception as e:
            errors.append(f"{s}: {e}")
        counter["n"] += 1
        if progress_cb:
            progress_cb(counter["n"], total_files + 1)  # +1 = rename pass

    def _ignore(directory, names):
        # Tell copytree which entries in this directory to skip.
        return {n for n in names if n in exclude}

    # copytree recreates the whole directory structure — including EMPTY
    # folders — and calls _copy for every file (excluded folders are skipped).
    shutil.copytree(src, dest_show, copy_function=_copy, ignore=_ignore)

    # Rename FULLSHOW items, walking bottom-up so a renamed parent folder
    # never invalidates the paths of children still to be processed.
    # _rename_with_retry handles the Windows [WinError 5] "Access is denied"
    # that occurs on network drives (Y:/) when Explorer or a sync client
    # briefly holds a lock on a newly-created folder.
    import time

    def _rename_with_retry(old: str, new: str, retries: int = 6, delay: float = 0.5):
        for attempt in range(retries):
            try:
                os.rename(old, new)
                return None          # success
            except OSError as e:
                if attempt < retries - 1:
                    time.sleep(delay)
                else:
                    return str(e)    # give up, return error message

    renamed = 0
    for root, dirs, files in os.walk(dest_show, topdown=False):
        for name in files:
            if "FULLSHOW" in name:
                old = os.path.join(root, name)
                new = os.path.join(root, name.replace("FULLSHOW", show_name))
                err = _rename_with_retry(old, new)
                if err:
                    errors.append(f"rename {old}: {err}")
                else:
                    renamed += 1
        for name in dirs:
            new_name = None
            if "FULLSHOW" in name:
                new_name = name.replace("FULLSHOW", show_name)
            elif name in renames:
                new_name = renames[name]
            if new_name and new_name != name:
                old = os.path.join(root, name)
                new = os.path.join(root, new_name)
                err = _rename_with_retry(old, new)
                if err:
                    errors.append(f"rename {old}: {err}")
                else:
                    renamed += 1

    if progress_cb:
        progress_cb(total_files + 1, total_files + 1)

    # Reset timestamps on all directories in the new show folder.
    # Done last (after renaming) so rename operations don't re-dirty
    # a parent folder's mtime before we get a chance to reset it.
    for root, dirs, _ in os.walk(dest_show, topdown=False):
        try:
            _reset_timestamps(root)
        except Exception:
            pass

    return total_files - len([e for e in errors if "rename" not in e]), renamed, errors


# ── Per-user settings persistence ────────────────────────────────────────────
#
# The app itself lives in a shared Dropbox folder run by many people on many
# machines, so settings are intentionally stored *locally* in each user's
# OS-standard application-data directory — never inside the Dropbox folder.
# This scopes settings to each (machine + OS user account) automatically, with
# no risk of Dropbox sync conflicts between users.

APP_NAME = "FuseShowCreator"

def _settings_dir() -> str:
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    elif os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, APP_NAME)

def settings_path() -> str:
    return os.path.join(_settings_dir(), "settings.json")

def load_settings() -> dict:
    """Return the saved settings dict, or {} if none / unreadable."""
    try:
        with open(settings_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def save_settings(settings: dict) -> bool:
    """Persist the settings dict to the per-user config file. Best-effort."""
    try:
        os.makedirs(_settings_dir(), exist_ok=True)
        with open(settings_path(), "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        return True
    except Exception:
        return False
