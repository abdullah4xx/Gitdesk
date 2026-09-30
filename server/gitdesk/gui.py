"""PyQt6 front-end: status, resolution, FPS, latency (RTT), bitrate, Start/Stop."""
import dataclasses
import threading

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import (QApplication, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                             QPushButton, QSpinBox, QVBoxLayout, QWidget)

from .config import Config
from .encoder import available_encoders
from .engine import Engine

QSS = """
* { color:#E2E8F0; font-size:13px; }
QWidget#root { background:#0B1020; }
QFrame#card { background:#131A2E; border:1px solid #1F2A48; border-radius:14px; }
QLabel { background:transparent; }
QLabel#title { font-size:24px; font-weight:700; color:#FFFFFF; }
QLabel#sub, QLabel#k { color:#94A3B8; }
QLabel#k { font-size:10px; letter-spacing:1px; }
QLabel#v { font-size:22px; font-weight:600; color:#C7D2FE; }
QComboBox, QSpinBox { background:#0F1526; border:1px solid #26314F; border-radius:8px; padding:6px 10px; }
QComboBox QAbstractItemView { background:#0F1526; selection-background-color:#4F46E5; }
QComboBox:disabled, QSpinBox:disabled { color:#64748B; }
QPushButton#go { background:#6366F1; color:#FFFFFF; border:none; border-radius:12px;
                 padding:14px; font-size:15px; font-weight:600; }
QPushButton#go:hover { background:#7C7FF5; }
QPushButton#go[running="true"] { background:#DC2626; }
QPushButton#go:disabled { background:#334155; color:#94A3B8; }
"""

RESOLUTIONS = [  # (label, (w, h)); (0, 0) = match the device screen
    ("1280×800 · recommended", (1280, 800)),
    ("1280×720", (1280, 720)),
    ("1920×1080 (needs a fast decoder)", (1920, 1080)),
    ("Auto (match device)", (0, 0)),
]

STATE_UI = {  # state -> (label, dot colour)
    "idle": ("Idle", "#64748B"),
    "starting": ("Starting…", "#F59E0B"),
    "running": ("Waiting for GitDesk app…", "#6366F1"),
    "streaming": ("Streaming", "#22C55E"),
    "stopping": ("Stopping…", "#F59E0B"),
    "error": ("Error", "#EF4444"),
}


class Card(QFrame):
    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(2)
        k, self.v = QLabel(title), QLabel("—")
        k.setObjectName("k")
        self.v.setObjectName("v")
        lay.addWidget(k)
        lay.addWidget(self.v)

    def set(self, text: str) -> None:
        self.v.setText(text)


class MainWindow(QWidget):
    state_sig = pyqtSignal(str, str)

    def __init__(self, base: Config):
        super().__init__()
        self.base, self.engine = base, None
        self.setObjectName("root")
        self.setWindowTitle("GitDesk")
        self.setMinimumWidth(460)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(14)

        title, sub = QLabel("GitDesk"), QLabel("Use your Android device as a USB second monitor")
        title.setObjectName("title")
        sub.setObjectName("sub")
        root.addWidget(title)
        root.addWidget(sub)

        row = QHBoxLayout()
        self.dot, self.status, self.device = QLabel("●"), QLabel("Idle"), QLabel("")
        self.device.setObjectName("sub")
        for w in (self.dot, self.status):
            row.addWidget(w)
        row.addStretch()
        row.addWidget(self.device)
        root.addLayout(row)

        grid = QGridLayout()
        grid.setSpacing(10)
        self.cards = {k: Card(k) for k in ("RESOLUTION", "FPS", "LATENCY (RTT)", "BITRATE")}
        for i, c in enumerate(self.cards.values()):
            grid.addWidget(c, i // 2, i % 2)
        root.addLayout(grid)

        box = QFrame()
        box.setObjectName("card")
        g = QGridLayout(box)
        g.setContentsMargins(16, 14, 16, 14)
        g.setVerticalSpacing(10)
        self.res = QComboBox()
        self.res.addItems([label for label, _ in RESOLUTIONS])
        self.fps = QComboBox()
        self.fps.addItems(["60", "30"])
        self.br = QSpinBox()
        self.br.setRange(base.min_bitrate_kbps // 1000, base.max_bitrate_kbps // 1000)
        self.br.setValue(base.bitrate_kbps // 1000)
        self.br.setSuffix(" Mbps")
        self.enc = QComboBox()
        self.enc.addItems(["auto"] + available_encoders())
        for i, (name, w) in enumerate((("Resolution", self.res), ("Frame rate", self.fps),
                                       ("Bitrate", self.br), ("Encoder", self.enc))):
            g.addWidget(QLabel(name), i, 0)
            g.addWidget(w, i, 1)
        g.setColumnStretch(1, 1)
        root.addWidget(box)

        self.btn = QPushButton("Start streaming")
        self.btn.setObjectName("go")
        self.btn.clicked.connect(self.toggle)
        root.addWidget(self.btn)
        self.note = QLabel("")
        self.note.setObjectName("sub")
        self.note.setWordWrap(True)
        root.addWidget(self.note)

        self.state_sig.connect(self._on_state)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(500)
        self._status("idle")

    # ── actions ──
    def _cfg(self) -> Config:
        w, h = RESOLUTIONS[self.res.currentIndex()][1]
        return dataclasses.replace(self.base, width=w, height=h, fps=int(self.fps.currentText()),
                                   bitrate_kbps=self.br.value() * 1000, encoder=self.enc.currentText())

    def toggle(self) -> None:
        e = self.engine
        if e and e.state in ("starting", "running"):
            self.btn.setEnabled(False)
            threading.Thread(target=e.stop, daemon=True).start()
        else:
            self.engine = Engine(self._cfg(), on_state=self.state_sig.emit)
            threading.Thread(target=self.engine.start, daemon=True).start()

    # ── UI updates (GUI thread) ──
    def _status(self, key: str) -> None:
        label, colour = STATE_UI[key]
        self.status.setText(label)
        self.dot.setStyleSheet(f"color:{colour}; background:transparent;")

    def _on_state(self, state: str, msg: str) -> None:
        busy = state in ("starting", "running")
        self.btn.setText("Stop" if busy else "Start streaming")
        self.btn.setProperty("running", busy)
        self.btn.style().unpolish(self.btn)
        self.btn.style().polish(self.btn)
        self.btn.setEnabled(state != "stopping")
        for w in (self.res, self.fps, self.br, self.enc):
            w.setEnabled(not busy)
        self._status(state)
        self.note.setText(msg)
        if state == "running" and self.engine:
            self.device.setText(self.engine.device)
            self.cards["RESOLUTION"].set(f"{self.engine.res[0]}×{self.engine.res[1]}")
        elif state in ("idle", "error"):
            self.device.setText("")
            for c in self.cards.values():
                c.set("—")

    def _tick(self) -> None:
        e = self.engine
        s = e.stats if e and e.state == "running" else None
        if not s:
            return
        self._status("streaming" if s.connected else "running")
        self.cards["FPS"].set(f"{s.fps:.0f}" if s.connected else "—")
        self.cards["LATENCY (RTT)"].set(f"{s.rtt_ms:.1f} ms" if s.connected and s.rtt_ms else "—")
        self.cards["BITRATE"].set(f"{s.kbps / 1000:.1f} Mbps" if s.connected else "—")
        if s.connected:
            self.note.setText(f"Encoder: {s.encoder} · target {s.target_kbps / 1000:.1f} Mbps · dropped {s.dropped}")

    def closeEvent(self, ev) -> None:
        if self.engine:
            self.engine.stop()
        super().closeEvent(ev)


def run_gui(cfg: Config) -> int:
    app = QApplication([])
    app.setStyleSheet(QSS)
    win = MainWindow(cfg)
    win.show()
    return app.exec()
