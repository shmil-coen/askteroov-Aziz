# -*- coding: utf-8 -*-
"""
שם ואייקון של אפליקציות מותקנות — דרך ADB, קריאה בלבד.

אנדרואיד לא מאפשר ל-ADB לקבל אייקון ישירות: האייקון והשם נמצאים בתוך קובץ
ה-APK. כדי לא להעתיק את כל הקובץ (לפעמים מאות MB), קוראים ממנו רק את החלקים
שצריך — ישירות מהמכשיר, בקטעים (dd) — ומפענחים:
  AndroidManifest.xml  → מזהי המשאבים של השם (label) והאייקון (icon)
  resources.arsc       → תרגום המזהים לטקסט (השם) ולנתיב קובץ התמונה
אם הקריאה בקטעים נכשלת — מעתיקים את ה-APK המלא (עד גודל מסוים) כגיבוי.
התוצאות נשמרות במטמון (workspace/app_cache), כך שבפעם הבאה הן מופיעות מיד.
"""
from __future__ import annotations

import io
import json
import os
import re
import struct
import subprocess
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional

from . import config

CACHE_DIR = config.WORKSPACE_DIR / "app_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
_PAGE = 256 * 1024               # גודל קטע קריאה מהמכשיר
_MAX_REMOTE = 60 * 1024 * 1024   # מקסימום נתונים לקריאה בקטעים לאפליקציה אחת
_MAX_PULL = 150 * 1024 * 1024    # מקסימום גודל APK להעתקה מלאה (גיבוי)

# מזהי מאפיינים של אנדרואיד
_ATTR_LABEL = 0x01010001
_ATTR_ICON = 0x01010002
_ATTR_DRAWABLE = 0x01010199
_ATTR_NAME = 0x01010003
_ATTR_PERMISSION = 0x01010006

# סוגי ערכים (Res_value.dataType)
_T_REF = 0x01
_T_STRING = 0x03
_T_COLOR_FIRST, _T_COLOR_LAST = 0x1C, 0x1F


# ---------------------------------------------------------------------- הרצת adb

def _run_bytes(cmd: list[str], timeout: float = 30) -> bytes:
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=timeout, creationflags=_FLAGS)
        return p.stdout or b""
    except (OSError, subprocess.TimeoutExpired):
        return b""


def _run_text(cmd: list[str], timeout: float = 20) -> str:
    return _run_bytes(cmd, timeout).decode("utf-8", "replace")


def _q(path: str) -> str:
    """ציטוט נתיב לפקודת shell במכשיר."""
    return "'" + path.replace("'", "'\\''") + "'"


# ---------------------------------------------------------------------- מבנה נתונים

@dataclass
class AppEntry:
    package: str
    apk_path: str = ""
    system: bool = False
    label: str = ""            # שם האפליקציה (ריק = לא ידוע)
    version: str = ""
    size: int = 0              # גודל ה-APK בבייטים
    icon_file: str = ""        # קובץ תמונה שמור במטמון (או ריק)
    icon_bg_file: str = ""     # רקע של אייקון אדפטיבי (תמונה), אם יש
    icon_bg_color: str = ""    # רקע של אייקון אדפטיבי (צבע #AARRGGBB), אם יש
    adaptive: bool = False     # אייקון אדפטיבי (שכבות) — להצגה צריך חיתוך
    note: str = ""             # הערה (למשל למה לא נמצא אייקון)
    removed_for_user: bool = False   # הוסרה מהמשתמש (pm uninstall --user 0)

    @property
    def display_name(self) -> str:
        return self.label or self.package


def list_apps(adb: str, include_system: bool = False) -> list[AppEntry]:
    """רשימת אפליקציות + נתיב ה-APK של כל אחת (pm list packages -f)."""
    # "הצג גם אפליקציות מערכת" = כל האפליקציות; אחרת רק שהמשתמש התקין (-3)
    filt = [] if include_system else ["-3"]
    # -u כולל גם אפליקציות שהוסרו מהמשתמש (אפליקציות מערכת שהוסרו ב--user 0)
    out = _run_text([adb, "shell", "pm", "list", "packages", "-f", "-u"] + filt, timeout=40)
    inst_out = _run_text([adb, "shell", "pm", "list", "packages"] + filt, timeout=40)
    installed = {l.split(":", 1)[1].strip() for l in inst_out.splitlines()
                 if l.strip().startswith("package:")}
    apps: list[AppEntry] = []
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("package:"):
            continue
        body = line[len("package:"):]
        if "=" not in body:
            continue
        path, pkg = body.rsplit("=", 1)       # בנתיב עצמו יכולים להופיע '='
        if pkg.strip():
            path = path.strip()
            is_sys = not path.startswith("/data/")
            name = pkg.strip()
            apps.append(AppEntry(package=name, apk_path=path, system=is_sys,
                                 removed_for_user=bool(installed) and name not in installed))
    apps.sort(key=lambda a: a.package.lower())
    return apps


# ---------------------------------------------------------------------- קריאה בקטעים

class RemoteFile(io.RawIOBase):
    """קובץ שנמצא במכשיר, נקרא לפי דרישה בקטעים (dd) — בלי להעתיק את כולו."""

    def __init__(self, adb: str, path: str, size: int):
        super().__init__()
        self.adb, self.path, self.size = adb, path, size
        self.pos = 0
        self._pages: dict[int, bytes] = {}
        self.fetched = 0

    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.pos

    def seek(self, off, whence=0):
        if whence == 0:
            self.pos = off
        elif whence == 1:
            self.pos += off
        else:
            self.pos = self.size + off
        return self.pos

    def _page(self, k: int) -> bytes:
        page = self._pages.get(k)
        if page is not None:
            return page
        expected = min(_PAGE, self.size - k * _PAGE)
        data = _run_bytes([self.adb, "exec-out",
                           f"dd if={_q(self.path)} bs={_PAGE} skip={k} count=1 2>/dev/null"],
                          timeout=40)
        if len(data) != expected:
            raise OSError(f"קריאה חלקית מהמכשיר ({len(data)} מתוך {expected})")
        self.fetched += len(data)
        if self.fetched > _MAX_REMOTE:
            raise OSError("האפליקציה גדולה מדי לקריאה בקטעים")
        self._pages[k] = data
        return data

    def readinto(self, b):
        n = min(len(b), max(0, self.size - self.pos))
        if n <= 0:
            return 0
        out = bytearray()
        while len(out) < n:
            cur = self.pos + len(out)
            page = self._page(cur // _PAGE)
            off = cur % _PAGE
            out += page[off:off + (n - len(out))]
        b[:n] = out
        self.pos += n
        return n


def _remote_size(adb: str, path: str) -> int:
    out = _run_text([adb, "shell", "stat", "-c", "%s", _q(path)], timeout=15).strip()
    return int(out) if out.isdigit() else 0


# ---------------------------------------------------------------------- מאגר מחרוזות

def _string_pool(buf: bytes, off: int) -> Callable[[int], str]:
    _t, hsz, _size = struct.unpack_from("<HHI", buf, off)
    count, _styles, flags, strings_start, _ss = struct.unpack_from("<IIIII", buf, off + 8)
    utf8 = bool(flags & 0x100)
    offsets = struct.unpack_from(f"<{count}I", buf, off + hsz) if count else ()
    base = off + strings_start
    cache: dict[int, str] = {}

    def get(i: int) -> str:
        if i < 0 or i >= count:
            return ""
        if i in cache:
            return cache[i]
        p = base + offsets[i]
        try:
            if utf8:
                n = buf[p]; p += 1                 # אורך ב-UTF16 (לא בשימוש)
                if n & 0x80:
                    p += 1
                n = buf[p]; p += 1                 # אורך בבייטים
                if n & 0x80:
                    n = ((n & 0x7F) << 8) | buf[p]; p += 1
                s = buf[p:p + n].decode("utf-8", "replace")
            else:
                n = struct.unpack_from("<H", buf, p)[0]; p += 2
                if n & 0x8000:
                    n = ((n & 0x7FFF) << 16) | struct.unpack_from("<H", buf, p)[0]; p += 2
                s = buf[p:p + 2 * n].decode("utf-16-le", "replace")
        except (IndexError, struct.error):
            s = ""
        cache[i] = s
        return s

    return get


# ---------------------------------------------------------------------- XML בינארי

def _axml_elements(buf: bytes, names: set[str]) -> list[tuple[str, dict]]:
    """מחזיר [(שם_אלמנט, {מזהה_מאפיין_או_שם: (סוג, ערך, מחרוזת_גולמית)})]."""
    typ, hsz, _size = struct.unpack_from("<HHI", buf, 0)
    if typ != 0x0003:
        raise ValueError("לא XML בינארי")
    off = hsz
    strings = None
    resmap: list[int] = []
    out = []
    while off + 8 <= len(buf):
        ctype, chsz, csize = struct.unpack_from("<HHI", buf, off)
        if csize < 8:
            break
        if ctype == 0x0001 and strings is None:
            strings = _string_pool(buf, off)
        elif ctype == 0x0180:
            n = (csize - chsz) // 4
            resmap = list(struct.unpack_from(f"<{n}I", buf, off + chsz))
        elif ctype == 0x0102 and strings is not None:
            ext = off + chsz
            _ns, name, astart, asize, acount = struct.unpack_from("<IIHHH", buf, ext)
            ename = strings(name)
            if ename in names:
                attrs = {}
                for i in range(acount):
                    a = ext + astart + i * asize
                    _ans, aname, araw, _vs, _r0, vtype, vdata = struct.unpack_from(
                        "<IIIHBBI", buf, a)
                    key = resmap[aname] if aname < len(resmap) and resmap[aname] \
                        else strings(aname)
                    raw = strings(araw) if araw != 0xFFFFFFFF else None
                    attrs[key] = (vtype, vdata, raw)
                out.append((ename, attrs))
        off += csize
    return out


# ---------------------------------------------------------------------- resources.arsc

class Arsc:
    """מפענח resources.arsc — רק מה שצריך כדי לתרגם מזהה משאב לערך."""

    def __init__(self, buf: bytes):
        self.buf = buf
        typ, hsz, _size = struct.unpack_from("<HHI", buf, 0)
        if typ != 0x0002:
            raise ValueError("לא טבלת משאבים")
        self.strings = None
        self.types: dict[tuple[int, int], list[int]] = {}   # (package, type) → חלקי TYPE
        off = hsz
        while off + 8 <= len(buf):
            ctype, chsz, csize = struct.unpack_from("<HHI", buf, off)
            if csize < 8:
                break
            if ctype == 0x0001 and self.strings is None:
                self.strings = _string_pool(buf, off)
            elif ctype == 0x0200:
                self._scan_package(off, chsz, csize)
            off += csize

    def _scan_package(self, off: int, hsz: int, size: int):
        pkg_id = struct.unpack_from("<I", self.buf, off + 8)[0]
        p, end = off + hsz, off + size
        while p + 8 <= end:
            ctype, _chsz, csize = struct.unpack_from("<HHI", self.buf, p)
            if csize < 8:
                break
            if ctype == 0x0201:
                tid = self.buf[p + 8]
                self.types.setdefault((pkg_id, tid), []).append(p)
            p += csize

    def _entry_offset(self, chunk: int, eidx: int) -> Optional[int]:
        buf = self.buf
        hsz = struct.unpack_from("<H", buf, chunk + 2)[0]
        flags = buf[chunk + 9]
        count, entries_start = struct.unpack_from("<II", buf, chunk + 12)
        idx = chunk + hsz
        if flags & 0x01:                       # sparse: זוגות (אינדקס, היסט/4)
            lo, hi = 0, count - 1
            while lo <= hi:
                mid = (lo + hi) // 2
                v = struct.unpack_from("<I", buf, idx + 4 * mid)[0]
                if (v & 0xFFFF) == eidx:
                    return chunk + entries_start + (v >> 16) * 4
                if (v & 0xFFFF) < eidx:
                    lo = mid + 1
                else:
                    hi = mid - 1
            return None
        if eidx >= count:
            return None
        if flags & 0x02:                       # offset16
            v = struct.unpack_from("<H", buf, idx + 2 * eidx)[0]
            return None if v == 0xFFFF else chunk + entries_start + v * 4
        v = struct.unpack_from("<I", buf, idx + 4 * eidx)[0]
        return None if v == 0xFFFFFFFF else chunk + entries_start + v

    def lookup(self, resid: int) -> list[tuple[str, int, int, int]]:
        """[(שפה, צפיפות, סוג, ערך)] לכל הגרסאות של המשאב."""
        pkg, tid, eidx = resid >> 24, (resid >> 16) & 0xFF, resid & 0xFFFF
        res = []
        buf = self.buf
        for chunk in self.types.get((pkg, tid), []):
            try:
                e = self._entry_offset(chunk, eidx)
                if e is None:
                    continue
                esize, eflags = struct.unpack_from("<HH", buf, e)
                if eflags & 0x0008:            # compact entry
                    vtype, vdata = eflags >> 8, struct.unpack_from("<I", buf, e + 4)[0]
                elif eflags & 0x0001:          # map/complex — לא נחוץ לנו
                    continue
                else:
                    _vs, _r0, vtype, vdata = struct.unpack_from("<HBBI", buf, e + esize)
                cfg = chunk + 20
                lang = buf[cfg + 8:cfg + 10]
                lang_s = lang.decode("latin-1").rstrip("\x00") if lang[0] < 0x80 else ""
                density = struct.unpack_from("<H", buf, cfg + 14)[0]
                res.append((lang_s, density, vtype, vdata))
            except (IndexError, struct.error):
                continue
        return res

    def resolve(self, resid: int, depth: int = 0) -> list[tuple[str, int, int, int]]:
        """כמו lookup, אבל עוקב אחרי הפניות (@string/x → ...) עד 5 רמות."""
        out = []
        for lang, dens, vtype, vdata in self.lookup(resid):
            if vtype == _T_REF and depth < 5 and vdata:
                for l2, d2, t2, v2 in self.resolve(vdata, depth + 1):
                    out.append((lang or l2, dens or d2, t2, v2))
            else:
                out.append((lang, dens, vtype, vdata))
        return out

    def string(self, i: int) -> str:
        return self.strings(i) if self.strings else ""


def _density_rank(d: int) -> int:
    return -1 if d in (0xFFFE, 0xFFFF) else d


def _pick_label(arsc: Optional[Arsc], vtype: int, vdata: int, raw: Optional[str]) -> str:
    if raw:
        return raw
    if arsc is None:
        return ""
    if vtype == _T_STRING:
        return arsc.string(vdata)
    if vtype != _T_REF:
        return ""
    vals = [(l, arsc.string(v)) for l, _d, t, v in arsc.resolve(vdata) if t == _T_STRING]
    for want in ("iw", "he", "", "en"):
        for l, s in vals:
            if l == want and s:
                return s
    return vals[0][1] if vals else ""


def _best_files(arsc: Arsc, resid: int) -> list[str]:
    """נתיבי קבצים של משאב, מהצפיפות הגבוהה לנמוכה (תמונות לפני XML)."""
    vals = [(d, arsc.string(v)) for _l, d, t, v in arsc.resolve(resid) if t == _T_STRING]
    vals.sort(key=lambda dv: (dv[1].lower().endswith(".xml"), -_density_rank(dv[0])))
    return [p for _d, p in vals if p]


def _color_of(arsc: Arsc, resid: int) -> str:
    for _l, _d, t, v in arsc.resolve(resid):
        if _T_COLOR_FIRST <= t <= _T_COLOR_LAST:
            return f"#{v:08X}"
    return ""


_IMG = (".png", ".webp", ".jpg")


def _heuristic_icon(zf: zipfile.ZipFile) -> Optional[str]:
    """גיבוי: התמונה הגדולה ביותר שנראית כמו אייקון אפליקציה."""
    best, best_size = None, 0
    for zi in zf.infolist():
        n = zi.filename.lower()
        if not n.startswith("res/") or not n.endswith(_IMG):
            continue
        if ("ic_launcher" in n and "foreground" not in n and "background" not in n) \
                or "app_icon" in n:
            if zi.file_size > best_size:
                best, best_size = zi.filename, zi.file_size
    return best


# ---------------------------------------------------------------------- פענוח APK

def parse_apk(zf: zipfile.ZipFile) -> dict:
    """מחזיר {'label', 'icon': bytes|None, 'icon_ext', 'bg': bytes|None,
    'bg_ext', 'bg_color', 'adaptive'}."""
    res = {"label": "", "icon": None, "icon_ext": ".png", "bg": None, "bg_ext": ".png",
           "bg_color": "", "adaptive": False}
    names = set(zf.namelist())
    manifest = zf.read("AndroidManifest.xml")
    arsc = Arsc(zf.read("resources.arsc")) if "resources.arsc" in names else None

    app_attrs = {}
    for ename, attrs in _axml_elements(manifest, {"application"}):
        app_attrs = attrs
        break
    if _ATTR_LABEL in app_attrs:
        t, v, raw = app_attrs[_ATTR_LABEL]
        res["label"] = _pick_label(arsc, t, v, raw)

    icon_path = None
    if arsc is not None and _ATTR_ICON in app_attrs:
        t, v, _raw = app_attrs[_ATTR_ICON]
        if t == _T_REF:
            files = _best_files(arsc, v)
            imgs = [f for f in files if f.lower().endswith(_IMG) and f in names]
            if imgs:
                icon_path = imgs[0]
            else:
                # אייקון אדפטיבי (XML עם שכבות foreground/background)
                xmls = [f for f in files if f.lower().endswith(".xml") and f in names]
                if xmls:
                    try:
                        layers = {n: a for n, a in _axml_elements(
                            zf.read(xmls[0]), {"foreground", "background"})}
                    except (ValueError, struct.error):
                        layers = {}
                    fg = layers.get("foreground", {}).get(_ATTR_DRAWABLE)
                    bg = layers.get("background", {}).get(_ATTR_DRAWABLE)
                    if fg and fg[0] == _T_REF:
                        fimgs = [f for f in _best_files(arsc, fg[1])
                                 if f.lower().endswith(_IMG) and f in names]
                        if fimgs:
                            icon_path = fimgs[0]
                            res["adaptive"] = True
                    if res["adaptive"] and bg:
                        if bg[0] == _T_REF:
                            bimgs = [f for f in _best_files(arsc, bg[1])
                                     if f.lower().endswith(_IMG) and f in names]
                            if bimgs:
                                res["bg"] = zf.read(bimgs[0])
                                res["bg_ext"] = os.path.splitext(bimgs[0])[1].lower()
                            else:
                                res["bg_color"] = _color_of(arsc, bg[1])
                        elif _T_COLOR_FIRST <= bg[0] <= _T_COLOR_LAST:
                            res["bg_color"] = f"#{bg[1]:08X}"
    if icon_path is None:
        icon_path = _heuristic_icon(zf)
        res["adaptive"] = False
    if icon_path:
        res["icon"] = zf.read(icon_path)
        res["icon_ext"] = os.path.splitext(icon_path)[1].lower()
    return res


# ---------------------------------------------------------------------- מידע + מטמון

def _dumpsys(adb: str, pkg: str) -> str:
    return _run_text([adb, "shell", "dumpsys", "package", pkg], timeout=20)


def _field(text: str, key: str) -> str:
    m = re.search(rf"\b{re.escape(key)}=([^\s]+(?: [0-9:]+)?)", text)
    return m.group(1).strip() if m else ""


def app_details(adb: str, pkg: str) -> dict:
    """מידע מפורט על אפליקציה (dumpsys package) — לחלון המידע."""
    t = _dumpsys(adb, pkg)
    granted = len(re.findall(r"granted=true", t))
    return {
        "package": pkg,
        "versionName": _field(t, "versionName"),
        "versionCode": _field(t, "versionCode"),
        "firstInstallTime": _field(t, "firstInstallTime"),
        "lastUpdateTime": _field(t, "lastUpdateTime"),
        "installer": _field(t, "installerPackageName") or _field(t, "installInitiatingPackageName"),
        "minSdk": _field(t, "minSdk"),
        "targetSdk": _field(t, "targetSdk"),
        "codePath": _field(t, "codePath"),
        "dataDir": _field(t, "dataDir"),
        "grantedPermissions": str(granted),
    }


def _cache_paths(pkg: str) -> tuple[Path, Path]:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", pkg)
    return CACHE_DIR / f"{safe}.json", CACHE_DIR / safe


def load_app(adb: str, app: AppEntry) -> AppEntry:
    """ממלא שם, גרסה, גודל ואייקון לאפליקציה — מהמטמון אם אפשר."""
    meta_file, stem = _cache_paths(app.package)
    app.size = _remote_size(adb, app.apk_path) if app.apk_path else 0
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        if meta.get("apk_path") == app.apk_path and meta.get("size") == app.size \
                and app.size:
            for k in ("label", "version", "icon_file", "icon_bg_file", "icon_bg_color",
                      "adaptive", "note"):
                setattr(app, k, meta.get(k, getattr(app, k)))
            if not app.icon_file or Path(app.icon_file).is_file():
                return app
    except (OSError, ValueError):
        pass

    app.version = _field(_dumpsys(adb, app.package), "versionName")
    parsed = None
    if app.size and app.apk_path:
        try:
            with zipfile.ZipFile(RemoteFile(adb, app.apk_path, app.size)) as zf:
                parsed = parse_apk(zf)
        except Exception as e:  # קריאה בקטעים נכשלה → העתקה מלאה (אם לא גדול מדי)
            app.note = str(e)[:120]
            if app.size <= _MAX_PULL:
                tmp = CACHE_DIR / "_tmp.apk"
                _run_bytes([adb, "pull", app.apk_path, str(tmp)], timeout=180)
                try:
                    with zipfile.ZipFile(tmp) as zf:
                        parsed = parse_apk(zf)
                        app.note = ""
                except Exception as e2:
                    app.note = str(e2)[:120]
                finally:
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
    if parsed:
        app.label = parsed["label"] or ""
        app.adaptive = parsed["adaptive"]
        app.icon_bg_color = parsed["bg_color"]
        if parsed["icon"]:
            f = stem.with_suffix(parsed["icon_ext"])
            f.write_bytes(parsed["icon"])
            app.icon_file = str(f)
        if parsed["bg"]:
            f = Path(str(stem) + "_bg" + parsed["bg_ext"])
            f.write_bytes(parsed["bg"])
            app.icon_bg_file = str(f)
        if not parsed["icon"]:
            app.note = app.note or "לא נמצא אייקון בקובץ"
    try:
        meta = asdict(app)
        meta_file.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return app


def apk_package_name(path) -> str:
    """שם החבילה (package) מתוך AndroidManifest של קובץ APK מקומי; ריק אם לא זוהה."""
    try:
        with zipfile.ZipFile(path) as zf:
            manifest = zf.read("AndroidManifest.xml")
        for _ename, attrs in _axml_elements(manifest, {"manifest"}):
            pv = attrs.get("package")
            if pv and pv[2]:
                return pv[2]
    except Exception:      # noqa: BLE001 — קובץ פגום / לא apk
        pass
    return ""


def admin_receiver_from_zip(zf: "zipfile.ZipFile") -> str:
    """רכיב מנהל-התקן (receiver עם BIND_DEVICE_ADMIN) מתוך zip פתוח של APK — 'pkg/comp' או ''."""
    manifest = zf.read("AndroidManifest.xml")
    pkg = ""
    for _e, attrs in _axml_elements(manifest, {"manifest"}):
        pv = attrs.get("package")
        if pv and pv[2]:
            pkg = pv[2]
        break
    for _ename, attrs in _axml_elements(manifest, {"receiver"}):
        perm = attrs.get(_ATTR_PERMISSION)
        name = attrs.get(_ATTR_NAME)
        if perm and perm[2] and "BIND_DEVICE_ADMIN" in perm[2] and name and name[2]:
            comp = name[2]
            if comp.startswith("."):
                comp = pkg + comp
            elif "." not in comp:
                comp = pkg + "." + comp
            return f"{pkg}/{comp}"
    return ""


def apk_admin_receiver(path) -> str:
    """כמו admin_receiver_from_zip, לקובץ APK מקומי; ריק אם לא נמצא/פגום."""
    try:
        with zipfile.ZipFile(path) as zf:
            return admin_receiver_from_zip(zf)
    except Exception:      # noqa: BLE001
        return ""


def admin_receiver_on_device(adb: str, pkg: str) -> str:
    """מזהה את רכיב מנהל-ההתקן מתוך ה-APK המותקן במכשיר (קריאת manifest בלבד)."""
    out = _run_text([adb, "shell", "pm", "list", "packages", "-f", pkg], timeout=15)
    apk_path = ""
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("package:") and line.endswith("=" + pkg):
            apk_path = line[len("package:"):].rsplit("=", 1)[0]
            break
    if not apk_path:
        return ""
    try:
        size = _remote_size(adb, apk_path)
        if not size:
            return ""
        with zipfile.ZipFile(RemoteFile(adb, apk_path, size)) as zf:
            return admin_receiver_from_zip(zf)
    except Exception:      # noqa: BLE001
        return ""
