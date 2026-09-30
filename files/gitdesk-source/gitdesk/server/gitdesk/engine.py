"""Orchestrates: device detection -> virtual display -> adb reverse -> stream server -> app launch."""
import threading
import time

from .adb import Adb, AdbError
from .config import Config
from .display import create_display, restore_display
from .server import StreamServer


def fit(w: int, h: int, max_long: int) -> tuple[int, int]:
    s = min(1.0, max_long / max(w, h))
    return int(w * s) // 2 * 2, int(h * s) // 2 * 2      # H.264 needs even dimensions


class Engine:
    """States: idle | starting | running | stopping | error"""

    def __init__(self, cfg: Config, on_state=lambda state, msg: None, log=print):
        self.cfg, self.on_state, self.log = cfg, on_state, log
        cfg.bitrate_kbps = max(cfg.min_bitrate_kbps, min(cfg.bitrate_kbps, cfg.max_bitrate_kbps))
        self.state = "idle"
        self.device = ""
        self.res = (0, 0)
        self.adb = self.target = self.server = None
        self.on_input = None                     # set by Part 3: fn(type: int, payload: bytes)
        self._lock = threading.Lock()
        self._cancel = threading.Event()

    @property
    def stats(self):
        return self.server.stats if self.server else None

    def _set(self, state: str, msg: str = "") -> None:
        self.state = state
        self.on_state(state, msg)

    def start(self) -> None:
        self._cancel.clear()
        with self._lock:
            if self.state in ("starting", "running"):
                return
            c = self.cfg
            self._set("starting", "Looking for device…")
            try:
                self.adb = Adb(c.adb_serial)
                serial = self.adb.wait_for_device(
                    30, on_wait=lambda hint: self._set("starting", hint), cancel=self._cancel)
                self.device = f"{self.adb.model()} · {serial}"
                w, h = (c.width, c.height) if c.width and c.height else fit(*self.adb.screen_size(), c.max_long_side)
                self._set("starting", f"Creating {w}×{h}@{c.fps} virtual display…")
                for line in restore_display():        # clear leftovers of a previous crashed session
                    self.log(f"cleanup: {line}")
                self.target = create_display(w, h, c.fps)
                self.res = (self.target.width, self.target.height)
                self.adb.reverse(c.port)
                self.server = StreamServer(c, self.target, on_input=self._dispatch_input, log=self.log)
                self.server.listen()
                if c.auto_launch and not self.adb.launch(c.package, c.activity):
                    self.log("GitDesk app not installed — open it manually on the device")
                self._set("running", "Waiting for the GitDesk app to connect…")
            except Exception as e:  # noqa: BLE001 — surface everything to the UI
                self._teardown()
                if self._cancel.is_set():
                    self._set("idle", "Cancelled")
                else:
                    self._set("error", str(e))
                return
            threading.Thread(target=self._watchdog, daemon=True, name="watchdog").start()

    def stop(self) -> None:
        self._cancel.set()
        with self._lock:                         # waits for a pending start() to unwind
            if self.state == "idle":
                return
            self._set("stopping", "Stopping…")
            self._teardown()
            self._set("idle", "Stopped")

    def _dispatch_input(self, t: int, payload: bytes) -> None:
        if self.on_input:
            self.on_input(t, payload)

    def _teardown(self) -> None:
        if self.server:
            self.server.stop()
        if self.adb:
            self.adb.unreverse(self.cfg.port)
        if self.target:
            try:
                self.target.cleanup()
            except Exception as e:  # noqa: BLE001
                self.log(f"display cleanup failed: {e}")
        self.server = self.target = None

    def _watchdog(self) -> None:
        """Stop cleanly if the cable is pulled."""
        while self.state == "running":
            time.sleep(2)
            try:
                devs = self.adb.devices()
            except AdbError:
                continue
            if self.state == "running" and not any(s == self.adb.serial and st == "device" for s, st in devs):
                with self._lock:
                    self._teardown()
                    self._set("error", "Device disconnected")
                return
