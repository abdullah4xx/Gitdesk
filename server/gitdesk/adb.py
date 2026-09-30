"""Thin ADB wrapper. Uses `adb reverse` so the phone's localhost:PORT reaches the PC server."""
import re
import shutil
import subprocess
import threading
import time


class AdbError(RuntimeError):
    pass


class Adb:
    def __init__(self, serial: str = ""):
        self.exe = shutil.which("adb")
        if not self.exe:
            raise AdbError("adb not found — install it: sudo apt install adb")
        self.serial = serial

    def _cmd(self, *args, timeout: float = 10, use_serial: bool = True) -> str:
        cmd = [self.exe] + (["-s", self.serial] if use_serial and self.serial else []) + list(args)
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise AdbError(f"adb timed out: {' '.join(args)}")
        if r.returncode:
            raise AdbError((r.stderr or r.stdout).strip() or f"adb {args[0]} failed")
        return r.stdout

    def devices(self) -> list[tuple[str, str]]:
        out = self._cmd("devices", use_serial=False)
        rows = [ln.split("\t") for ln in out.splitlines() if "\t" in ln]
        return [(r[0].strip(), r[1].strip()) for r in rows]

    def wait_for_device(self, timeout: float = 30.0, on_wait=None, cancel: threading.Event | None = None) -> str:
        cancel = cancel or threading.Event()
        self._cmd("start-server", use_serial=False, timeout=20)
        end = time.monotonic() + timeout
        while True:
            devs = self.devices()
            ready = [s for s, st in devs if st == "device" and (not self.serial or s == self.serial)]
            if ready:
                self.serial = ready[0]
                return self.serial
            if any(st == "unauthorized" for _, st in devs):
                hint = "Device unauthorized — accept the USB debugging prompt on the phone."
            else:
                hint = "No device found — enable USB debugging and connect the cable."
            if on_wait:
                on_wait(hint)
            if cancel.is_set():
                raise AdbError("cancelled")
            if time.monotonic() > end:
                raise AdbError(hint)
            cancel.wait(1.0)

    def model(self) -> str:
        return self._cmd("shell", "getprop", "ro.product.model").strip() or "Android"

    def screen_size(self) -> tuple[int, int]:
        """Landscape (w, h) of the device; honours `wm size` overrides (last match wins)."""
        found = re.findall(r"(\d+)x(\d+)", self._cmd("shell", "wm", "size"))
        if not found:
            raise AdbError("cannot read device screen size")
        w, h = map(int, found[-1])
        return max(w, h), min(w, h)

    def reverse(self, port: int) -> None:
        self._cmd("reverse", f"tcp:{port}", f"tcp:{port}")

    def unreverse(self, port: int) -> None:
        try:
            self._cmd("reverse", "--remove", f"tcp:{port}")
        except AdbError:
            pass

    def launch(self, package: str, activity: str) -> bool:
        try:
            self._cmd("shell", "am", "start", "-n", f"{package}/{activity}")
            return True
        except AdbError:
            return False  # app not installed yet — user can open it manually
