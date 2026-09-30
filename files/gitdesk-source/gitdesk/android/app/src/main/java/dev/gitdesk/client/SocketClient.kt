package dev.gitdesk.client

import java.io.BufferedInputStream
import java.io.DataInputStream
import java.io.IOException
import java.net.InetSocketAddress
import java.net.Socket
import java.nio.ByteBuffer
import java.util.concurrent.Executors
import java.util.concurrent.RejectedExecutionException

/**
 * Connects to the PC via `adb reverse` (device 127.0.0.1:PORT -> PC). Auto-reconnects.
 * Single-use: create a new instance after stop().
 * Frame format (both directions): [type u8][len u32 BE][payload].
 *
 * All writes go through a single-thread executor: they are safe to request from the UI thread
 * (socket I/O on the main thread throws NetworkOnMainThreadException).
 */
class SocketClient(private val cb: Listener, private val port: Int = 12345) {

    interface Listener {
        fun onState(msg: String)
        fun onHello(width: Int, height: Int, fps: Int)
        fun onVideo(buf: ByteArray, off: Int, len: Int, keyframe: Boolean, ptsUs: Long)
        fun onStats(fps: Float, kbps: Int, rttMs: Float, targetKbps: Int) {}
        fun onDisconnected()
    }

    @Volatile private var running = false
    @Volatile private var sock: Socket? = null
    @Volatile private var helloSeen = false
    private val txExec = Executors.newSingleThreadExecutor { r -> Thread(r, "gd-tx") }

    fun start() {
        if (running) return
        running = true
        Thread(::loop, "gd-socket").start()
    }

    fun stop() {
        running = false
        val s = sock
        Thread { try { s?.close() } catch (_: IOException) {} }.start()
        txExec.shutdownNow()
    }

    fun requestKeyframe() = send(T_REQ_IDR, ByteArray(0))

    fun setBitrate(kbps: Int) = send(T_SET_BITRATE, ByteBuffer.allocate(4).putInt(kbps).array())

    fun send(type: Int, payload: ByteArray) {
        val msg = ByteBuffer.allocate(5 + payload.size)
            .put(type.toByte()).putInt(payload.size).put(payload).array()
        try {
            txExec.execute {
                try {
                    val s = sock ?: return@execute
                    val o = s.getOutputStream()
                    o.write(msg)
                    o.flush()
                } catch (_: IOException) {
                }
            }
        } catch (_: RejectedExecutionException) {
        }
    }

    private fun loop() {
        while (running) {
            helloSeen = false
            try {
                cb.onState("Connecting to PC…")
                val s = Socket()
                s.tcpNoDelay = true
                s.connect(InetSocketAddress("127.0.0.1", port), 1500)
                s.soTimeout = 5000          // server pings every second: silence == dead link
                sock = s
                serve(s)
            } catch (_: IOException) {
            } finally {
                try { sock?.close() } catch (_: IOException) {}
                sock = null
            }
            if (!running) break
            if (helloSeen) cb.onDisconnected()
            cb.onState("Waiting for GitDesk on your PC…")
            try { Thread.sleep(800) } catch (_: InterruptedException) { break }
        }
    }

    private fun serve(s: Socket) {
        val inp = DataInputStream(BufferedInputStream(s.getInputStream(), 1 shl 16))
        while (running) {
            val type = inp.readUnsignedByte()
            val len = inp.readInt()
            if (len < 0 || len > MAX_PAYLOAD) throw IOException("bad frame length $len")
            val p = ByteArray(len)
            inp.readFully(p)
            when (type) {
                T_HELLO -> if (len >= 9) {
                    val bb = ByteBuffer.wrap(p)
                    bb.position(3)                                  // "GD" + version
                    val w = bb.getShort().toInt() and 0xFFFF
                    val h = bb.getShort().toInt() and 0xFFFF
                    val fps = bb.get().toInt() and 0xFF
                    helloSeen = true
                    cb.onHello(w, h, fps)
                }
                T_VIDEO -> if (helloSeen && len > 9) {
                    val key = (p[0].toInt() and 1) != 0
                    val pts = ByteBuffer.wrap(p, 1, 8).getLong()
                    cb.onVideo(p, 9, len - 9, key, pts)
                }
                T_PING -> send(T_PONG, p)
                T_STATS -> if (len >= 12) {
                    val bb = ByteBuffer.wrap(p)
                    val fps = (bb.getShort().toInt() and 0xFFFF) / 10f
                    val kbps = bb.getInt()
                    val rtt = (bb.getShort().toInt() and 0xFFFF) / 10f
                    val target = bb.getInt()
                    cb.onStats(fps, kbps, rtt, target)
                }
                T_BYE -> return
            }
        }
    }

    companion object {
        const val T_HELLO = 0x01
        const val T_VIDEO = 0x02
        const val T_PING = 0x03
        const val T_BYE = 0x04
        const val T_STATS = 0x05
        const val T_PONG = 0x11
        const val T_REQ_IDR = 0x13
        const val T_SET_BITRATE = 0x14
        private const val MAX_PAYLOAD = 16 shl 20
    }
}
