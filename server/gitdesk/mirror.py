"""Android -> Linux screen mirroring by driving scrcpy (works on GNOME/Wayland).

scrcpy opens an ordinary window, so no compositor-specific capture is needed. On a Wayland session we
first try SDL's native Wayland driver and fall back to XWayland if scrcpy dies right away.
"""
import os
import shutil
import subprocess
import threading
import time

from .adb import Adb, AdbError


class MirrorError(RuntimeError):
    pass


def available() -> bool:
    return shutil.which("scrcpy") is not None


class Mirror:
    """start() returns immediately; on_exit(message) is called (from a worker thread) when mirroring ends."""

    def __init__(self, serial: str = "", bitrate_mbps: int = 8, fps: int = 60, max_size: int = 0,
                 control: bool = True, on_exit=None):
        self.serial, self.bitrate_mbps, self.fps = serial, bitrate_mbps, fps
        self.max_size, self.control, self.on_exit = max_size, control, on_exit
        self._proc = None
        self._thread = None
        self._stop = threading.Event()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        exe = shutil.which("scrcpy")
        if not exe:
            raise MirrorError("scrcpy not found — install it: sudo apt install scrcpy")
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(exe,), daemon=True, name="mirror")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        p = self._proc
        if p is not None and p.poll() is None:
            p.terminate()

    # ── worker thread ──
    def _cmd(self, exe: str, serial: str) -> list[str]:
        cmd = [exe, "-s", serial, "--window-title", "GitDesk — Android screen",
               "-b", f"{int(self.bitrate_mbps)}M", "--max-fps", str(self.fps)]
        if self.max_size:
            cmd += ["-m", str(self.max_size)]
        if not self.control:
            cmd.append("-n")                 # view only: no touch/keyboard forwarding
        return cmd

    def _run(self, exe: str) -> None:
        msg = "Mirroring stopped"
        try:
            serial = Adb(self.serial).wait_for_device(timeout=15, cancel=self._stop)
            msg = self._supervise(self._cmd(exe, serial))
        except AdbError as e:
            msg = str(e)
        except OSError as e:
            msg = f"cannot start scrcpy: {e}"
        finally:
            self._proc = None
            if self.on_exit:
                self.on_exit(msg)

    def _supervise(self, cmd: list[str]) -> str:
        attempts = [True, False] if os.environ.get("WAYLAND_DISPLAY") else [False]
        last_err = ""
        for native_wayland in attempts:
            if self._stop.is_set():
                return "Mirroring stopped"
            env = os.environ.copy()
            if native_wayland:
                env["SDL_VIDEODRIVER"] = "wayland"
            t0 = time.monotonic()
            self._proc = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL,
                                          stderr=subprocess.PIPE, text=True)
            err = self._proc.communicate()[1] or ""
            rc = self._proc.returncode
            if self._stop.is_set():
                return "Mirroring stopped"
            if rc == 0:
                return "Mirror window closed"
            lines = [ln for ln in err.splitlines() if ln.strip()]
            last_err = lines[-1] if lines else ""
            if native_wayland and time.monotonic() - t0 < 3:
                continue                     # native Wayland driver unavailable -> retry via XWayland
            break
        return f"scrcpy exited with an error: {last_err}" if last_err else "scrcpy exited with an error"
