"""Virtual display creation + GStreamer capture source.

Capture is NON-exclusive: ximagesrc reads a region of the root window (XShm) and Mutter's ScreenCast
API is a shared stream, so neither takes over the desktop. The only thing that can touch the top bar is
the RandR reconfiguration, so it is made reversible: the primary output is recorded, re-asserted after
the virtual output is added and again on cleanup, and `restore_display()` cleans up after crashes.

X11     : real RandR output (VIRTUAL1 / any disconnected output) with a custom CVT-RB mode,
          fallback to a RandR 1.5 logical monitor (`--setmonitor`) on an enlarged framebuffer.
Wayland : GNOME Mutter `RecordVirtual` (experimental) -> PipeWire node -> pipewiresrc.
"""
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable


class DisplayError(RuntimeError):
    pass


@dataclass
class CaptureTarget:
    width: int
    height: int
    source: str                    # GStreamer source fragment ending in raw video caps
    kind: str                      # "x11" | "wayland"
    cleanup: Callable[[], None]
    origin: tuple = (0, 0)         # top-left of the virtual monitor in desktop coordinates


def session_type() -> str:
    t = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if t in ("x11", "wayland"):
        return t
    return "wayland" if os.environ.get("WAYLAND_DISPLAY") else "x11"


def create_display(w: int, h: int, fps: int) -> CaptureTarget:
    cls = MutterVirtual if session_type() == "wayland" else X11Virtual
    return cls(w, h, fps).create()


# ───────────────────────────── X11 ─────────────────────────────
_GEOM = re.compile(r"^(\S+) connected (?:primary )?(\d+)x(\d+)\+(\d+)\+(\d+)", re.M)


def _xr(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["xrandr", *args], capture_output=True, text=True)


def restore_display() -> list[str]:
    """Undo leftovers of a crashed/killed session (virtual outputs, GitDesk modes, logical monitor) and
    re-assert the primary output so the desktop panel stays where it belongs. Safe to call any time."""
    done: list[str] = []
    if session_type() != "x11" or not shutil.which("xrandr"):
        return done
    q = _xr("--query").stdout
    primary = X11Virtual.find_primary(q)
    if not _xr("--delmonitor", X11Virtual.NAME).returncode:
        done.append("removed logical monitor")
    out = None
    for line in q.splitlines():
        m = re.match(r"^(\S+) (?:dis)?connected", line)
        if m:
            out = m.group(1)
            continue
        m = re.match(r"^\s+(GitDesk_\S+)", line)
        if m and out:
            mode = m.group(1)
            if "*" in line:                       # currently active on this output
                _xr("--output", out, "--off")
                done.append(f"disabled {out}")
            _xr("--delmode", out, mode)
            _xr("--rmmode", mode)
            done.append(f"removed mode {mode}")
    if primary:
        _xr("--output", primary, "--primary")
    return done


class X11Virtual:
    NAME = "GitDesk"

    def __init__(self, w: int, h: int, fps: int):
        self.w, self.h, self.fps = w, h, fps
        self.mode = f"GitDesk_{w}x{h}_{fps}"
        self.out = None            # RandR output in use
        self.monitor = False       # True when using --setmonitor fallback
        self.fb = None             # original framebuffer size (fallback only)
        self.rect = (w, h, 0, 0)
        self.primary = None        # output that carried the desktop panel before we changed anything

    @staticmethod
    def find_primary(q: str):
        m = re.search(r"^(\S+) connected primary", q, re.M)
        if m:
            return m.group(1)
        m = re.search(r"^(\S+) connected (?:\d+)x(?:\d+)\+0\+0", q, re.M)   # implicit primary: origin output
        return m.group(1) if m else None

    def _keep_primary(self) -> None:
        if self.primary and self.find_primary(_xr("--query").stdout) != self.primary:
            _xr("--output", self.primary, "--primary")

    def _geom(self, out: str):
        m = re.search(rf"^{re.escape(out)} connected (?:primary )?(\d+)x(\d+)\+(\d+)\+(\d+)",
                      _xr("--query").stdout, re.M)
        return tuple(map(int, m.groups())) if m else None

    def _modeline(self) -> list[str]:
        """CVT reduced-blanking timing: 160px H-blank, 31 line V-blank."""
        w, h = self.w, self.h
        ht, vt = w + 160, h + 31
        clk = ht * vt * self.fps / 1e6
        return [f"{clk:.2f}", str(w), str(w + 48), str(w + 80), str(ht),
                str(h), str(h + 3), str(h + 8), str(vt), "+HSync", "-VSync"]

    def _try_output(self, out: str, edge_x: int) -> bool:
        _xr("--newmode", self.mode, *self._modeline())   # error if it already exists — harmless
        if _xr("--addmode", out, self.mode).returncode:
            return False
        if _xr("--output", out, "--mode", self.mode, "--pos", f"{edge_x}x0").returncode:
            _xr("--delmode", out, self.mode)
            return False
        g = self._geom(out)
        if not g:
            _xr("--output", out, "--off")
            _xr("--delmode", out, self.mode)
            return False
        self.out, self.rect = out, g
        return True

    def _setmonitor(self, sw: int, sh: int, edge_x: int) -> None:
        self.fb = (sw, sh)
        fw, fh = max(sw, edge_x + self.w), max(sh, self.h)
        if _xr("--fb", f"{fw}x{fh}").returncode:
            raise DisplayError("xrandr could not enlarge the framebuffer")
        mmw, mmh = round(self.w * 25.4 / 96), round(self.h * 25.4 / 96)
        r = _xr("--setmonitor", self.NAME, f"{self.w}/{mmw}x{self.h}/{mmh}+{edge_x}+0", "none")
        if r.returncode:
            _xr("--fb", f"{sw}x{sh}")
            raise DisplayError(f"xrandr --setmonitor failed: {r.stderr.strip()}")
        self.monitor, self.rect = True, (self.w, self.h, edge_x, 0)

    def create(self) -> CaptureTarget:
        if not shutil.which("xrandr"):
            raise DisplayError("xrandr not found — sudo apt install x11-xserver-utils")
        q = _xr("--query").stdout
        m = re.search(r"current (\d+) x (\d+)", q)
        if not m:
            raise DisplayError("cannot query the X server (is DISPLAY set?)")
        sw, sh = map(int, m.groups())
        self.primary = self.find_primary(q)
        edge_x = max((int(g[3]) + int(g[1]) for g in _GEOM.findall(q)), default=sw)
        # prefer Intel-style VIRTUAL* outputs, then any disconnected output
        cands = sorted(re.findall(r"^(\S+) disconnected", q, re.M),
                       key=lambda n: not n.upper().startswith("VIRTUAL"))
        if not any(self._try_output(o, edge_x) for o in cands):
            _xr("--rmmode", self.mode)
            self._setmonitor(sw, sh, edge_x)
        self._keep_primary()
        cw, ch, x, y = self.rect
        disp = os.environ.get("DISPLAY", ":0")
        src = (f"ximagesrc display-name={disp} use-damage=false show-pointer=true "
               f"startx={x} starty={y} endx={x + cw - 1} endy={y + ch - 1} "
               f"! video/x-raw,framerate={self.fps}/1")
        return CaptureTarget(cw, ch, src, "x11", self.cleanup, (x, y))

    def cleanup(self) -> None:
        if self.monitor:
            _xr("--delmonitor", self.NAME)
            if self.fb:
                _xr("--fb", f"{self.fb[0]}x{self.fb[1]}")
        if self.out:
            _xr("--output", self.out, "--off")
            _xr("--delmode", self.out, self.mode)
        _xr("--rmmode", self.mode)
        self._keep_primary()


# ─────────────────────── Wayland (GNOME) ───────────────────────
class MutterVirtual:
    BUS = "org.gnome.Mutter.ScreenCast"

    def __init__(self, w: int, h: int, fps: int):
        self.w, self.h, self.fps = w, h, fps

    def create(self) -> CaptureTarget:
        try:
            import gi
            from gi.repository import Gio, GLib
        except ImportError:
            raise DisplayError("PyGObject missing — sudo apt install python3-gi")

        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        none = Gio.DBusCallFlags.NONE

        def proxy(path, iface):
            return Gio.DBusProxy.new_sync(bus, Gio.DBusProxyFlags.NONE, None, self.BUS, path, iface, None)

        try:
            sc = proxy("/org/gnome/Mutter/ScreenCast", self.BUS)
            spath = sc.call_sync("CreateSession", GLib.Variant("(a{sv})", ({},)), none, -1, None).unpack()[0]
            sess = proxy(spath, self.BUS + ".Session")
            opts = {"cursor-mode": GLib.Variant("u", 1)}          # 1 = cursor embedded in frames
            stpath = sess.call_sync("RecordVirtual", GLib.Variant("(a{sv})", (opts,)), none, -1, None).unpack()[0]
        except GLib.Error as e:
            raise DisplayError(f"Mutter ScreenCast unavailable (needs GNOME >= 42 on Wayland): {e.message}")

        loop, node = GLib.MainLoop(), []

        def on_added(_c, _s, _p, _i, _n, params):
            node.append(params.unpack()[0])
            loop.quit()

        sub = bus.signal_subscribe(self.BUS, self.BUS + ".Stream", "PipeWireStreamAdded",
                                   stpath, None, Gio.DBusSignalFlags.NONE, on_added)
        try:
            sess.call_sync("Start", None, none, -1, None)
            GLib.timeout_add_seconds(5, loop.quit)
            loop.run()
        finally:
            bus.signal_unsubscribe(sub)
        if not node:
            self._stop(sess)
            raise DisplayError("Mutter did not provide a PipeWire node")

        # PipeWire only delivers frames on damage, so a static desktop would stall the encoder ("0 FPS").
        # keepalive-time re-sends the last buffer when nothing new arrived, keeping a steady input rate.
        # width/height caps steer Mutter's virtual-monitor size; videorate makes the fps constant.
        keepalive = max(2 * 1000 // self.fps, 1)
        src = (f"pipewiresrc path={node[0]} do-timestamp=true always-copy=true keepalive-time={keepalive} "
               f"! video/x-raw,width={self.w},height={self.h} ! videorate "
               f"! video/x-raw,framerate={self.fps}/1")
        return CaptureTarget(self.w, self.h, src, "wayland", lambda: self._stop(sess))

    @staticmethod
    def _stop(sess) -> None:
        try:
            sess.call_sync("Stop", None, 0, -1, None)
        except Exception:
            pass
