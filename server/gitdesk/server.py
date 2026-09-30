"""TCP server on 127.0.0.1:PORT. The phone reaches it through `adb reverse`. One client at a time.

Back-pressure design (fixes the "frozen at 0 FPS" failure mode):
  * The GStreamer thread NEVER blocks on the socket: access units go into a small bounded queue.
  * A dedicated sender thread drains the queue. If the phone falls behind and the queue fills, the
    new access unit is dropped, the stream is gated until the next IDR (queued units stay decodable)
    and an IDR is requested — so the picture recovers within ~1 frame instead of freezing.
  * A watchdog drops a connection whose send() has made no progress for STALL_S seconds.
"""
import queue
import select
import socket
import threading
import time
from dataclasses import dataclass

from . import protocol as P
from .encoder import EncoderError, Streamer

QMAX = 6          # minimum queued access units; the real size is max(QMAX, fps // 4) (~250 ms of frames)
STALL_S = 4.0     # kill a connection whose send() is stuck this long
IDR_MIN_GAP = 0.3


@dataclass
class Stats:
    connected: bool = False
    encoder: str = "-"
    fps: float = 0.0
    kbps: float = 0.0
    rtt_ms: float = 0.0
    target_kbps: int = 0
    dropped: int = 0


class StreamServer:
    def __init__(self, cfg, target, on_input=None, log=print):
        self.cfg, self.target, self.on_input, self.log = cfg, target, on_input, log
        self.stats = Stats()
        self._srv = None
        self._conn = None
        self._q = None
        self._streamer = None
        self._run = False
        self._need_key = True
        self._want_idr = False
        self._last_idr = 0.0
        self._tx_since = 0.0             # >0 while the sender is inside a video send()
        self._tx = threading.Lock()      # serialises writers (sender + pinger)
        self._slot = threading.Lock()    # one active session at a time
        self._frames = self._bytes = 0

    # ── lifecycle ──
    def listen(self) -> None:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", self.cfg.port))
        s.listen(1)
        self._srv, self._run = s, True
        threading.Thread(target=self._accept, daemon=True, name="accept").start()

    def stop(self) -> None:
        self._run = False
        if self._srv:
            for fn in (lambda: self._srv.shutdown(socket.SHUT_RDWR), self._srv.close):
                try:
                    fn()
                except OSError:
                    pass
        self._kill(self._conn)
        if self._slot.acquire(timeout=4):    # wait for the session to unwind
            self._slot.release()

    def _accept(self) -> None:
        while self._run:
            try:
                conn, _ = self._srv.accept()
            except OSError:
                break
            self._kill(self._conn)           # newest client wins
            threading.Thread(target=self._session, args=(conn,), daemon=True, name="session").start()

    # ── one client ──
    def _session(self, conn) -> None:
        with self._slot:
            if not self._run:
                conn.close()
                return
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 256 * 1024)
            q = queue.Queue(maxsize=max(QMAX, self.cfg.fps // 4))   # ~250 ms of frames absorbs USB jitter
            st = Streamer(self.cfg, self.target, self._on_au, lambda m: self._fail(conn, m))
            self.stats = Stats(target_kbps=self.cfg.bitrate_kbps)
            self._conn, self._q, self._streamer = conn, q, st
            self._need_key, self._want_idr, self._tx_since = True, False, 0.0
            self._frames = self._bytes = 0
            try:
                self._send(conn, P.pack_hello(self.target.width, self.target.height, self.cfg.fps))
                self.stats.encoder = st.start()
                self.stats.connected = True
                self.log(f"client connected — encoder {self.stats.encoder}")
                threading.Thread(target=self._sender, args=(conn, q, st), daemon=True, name="sender").start()
                threading.Thread(target=self._pinger, args=(conn,), daemon=True, name="pinger").start()
                self._reader(conn, st)
            except (OSError, ValueError, EncoderError) as e:
                self.log(f"session ended: {e}")
            finally:
                self._conn = None            # ends sender / pinger loops
                st.stop()
                self._streamer = self._q = None
                self.stats = Stats()
                try:
                    conn.close()
                except OSError:
                    pass

    def _reader(self, conn, st) -> None:
        while True:
            t, payload = P.recv_frame(conn)
            if t == P.T_PONG:
                rtt = (P.now_us() - P.unpack_ts(payload)) / 1000.0
                s = self.stats
                s.rtt_ms = rtt if not s.rtt_ms else s.rtt_ms * 0.7 + rtt * 0.3
            elif t == P.T_REQ_IDR:
                self._want_idr = True
            elif t == P.T_SET_BITRATE and len(payload) >= 4:
                applied = st.set_bitrate(P.unpack_u32(payload))
                if applied:
                    self.stats.target_kbps = applied
                    self.log(f"bitrate -> {applied} kbps")
            elif self.on_input:
                self.on_input(t, payload)        # TOUCH / KEY -> Part 3 injector

    # ── video path ──
    def _on_au(self, data: bytes, key: bool, pts_us: int) -> None:
        """Runs on the GStreamer thread: must never block."""
        q = self._q
        if q is None:
            return
        if self._need_key:                   # never start (or resume) mid-GOP
            if not key:
                return
            self._need_key = False
        try:
            q.put_nowait(P.pack_video(data, key, pts_us))
        except queue.Full:
            self._need_key = True            # already-queued units remain a valid prefix
            self._want_idr = True
            self.stats.dropped += 1
            return
        self._frames += 1
        self._bytes += len(data)

    def _sender(self, conn, q, st) -> None:
        while self._conn is conn:
            now = time.monotonic()
            if self._want_idr and now - self._last_idr > IDR_MIN_GAP:
                self._want_idr, self._last_idr = False, now
                st.request_keyframe()
            try:
                pkt = q.get(timeout=0.25)
            except queue.Empty:
                continue
            self._tx_since = time.monotonic()
            try:
                self._send(conn, pkt)
            except OSError:
                self._kill(conn)
                return
            finally:
                self._tx_since = 0.0

    def _pinger(self, conn) -> None:
        last = time.monotonic()
        while self._conn is conn:
            time.sleep(1.0)
            now = time.monotonic()
            since = self._tx_since
            if since and now - since > STALL_S:
                self.log("send stalled — dropping connection so the phone can reconnect")
                self._kill(conn)
                return
            dt, last = now - last, now
            f, b, self._frames, self._bytes = self._frames, self._bytes, 0, 0
            s = self.stats
            s.fps, s.kbps = f / dt, b * 8 / 1000 / dt
            self._send_ctl(conn, P.pack_ping() + P.pack_stats(s.fps, s.kbps, s.rtt_ms, s.target_kbps))

    # ── socket helpers ──
    def _send(self, conn, data: bytes) -> None:
        with self._tx:
            conn.sendall(data)

    def _send_ctl(self, conn, data: bytes) -> None:
        """Small control frames: skipped (not blocked on) if the link is congested."""
        if not self._tx.acquire(timeout=0.5):
            return
        try:
            if select.select([], [conn], [], 0)[1]:
                conn.sendall(data)
        except OSError:
            self._kill(conn)
        finally:
            self._tx.release()

    def _fail(self, conn, msg: str) -> None:
        self.log(f"stream error: {msg}")
        self._kill(conn)

    @staticmethod
    def _kill(conn) -> None:
        if conn is not None:
            try:
                conn.shutdown(socket.SHUT_RDWR)   # unblocks recv()/send() in every thread
            except OSError:
                pass
