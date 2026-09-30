package dev.gitdesk.client

import android.app.Activity
import android.content.SharedPreferences
import android.graphics.Bitmap
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.Gravity
import android.view.PixelCopy
import android.view.Surface
import android.view.SurfaceHolder
import android.view.View
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.TextView
import java.util.Locale

/**
 * Lifecycle model (fixes the black screen after entering/leaving immersive mode):
 *  - The SOCKET lives with the activity (onStart/onStop) and survives Surface re-creation.
 *  - The DECODER lives with (Surface + HELLO): it is rebuilt whenever the Surface is re-created and a
 *    keyframe is requested. The Surface buffer is pinned to the video size (setFixedSize), so system-bar
 *    and layout changes never resize the buffer under the codec.
 *  - A watchdog walks a decoder fallback ladder (FAST -> PLAIN -> SOFTWARE) if frames are fed but nothing
 *    renders, and finally shows a friendly error screen with Quick Reconnect.
 */
class MainActivity : Activity(), SocketClient.Listener, SurfaceHolder.Callback {

    private data class Hello(val w: Int, val h: Int, val fps: Int)

    private val ui = Handler(Looper.getMainLooper())
    private val decLock = Any()
    private lateinit var prefs: SharedPreferences
    private lateinit var surfaceView: AspectSurfaceView
    private lateinit var overlay: LoadingOverlay
    private lateinit var menu: FloatingMenu
    private lateinit var hud: TextView

    @Volatile private var surface: Surface? = null
    @Volatile private var decoder: MediaCodecDecoder? = null
    @Volatile private var client: SocketClient? = null
    @Volatile private var hello: Hello? = null
    @Volatile private var mode = MediaCodecDecoder.MODE_FAST

    private var streaming = false
    private var userDisconnected = false
    private var showHud = true
    private var stalls = 0
    private var healthyTicks = 0
    private var lastIdr = 0L
    private var startNote = ""
    private var tracked: MediaCodecDecoder? = null
    private var lastCount = 0L
    private var lastAt = 0L
    private var fpsNow = 0
    private var mbps = 0f
    private var rttMs = 0f

    // ───────────────────────────── setup ─────────────────────────────
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = getSharedPreferences("gitdesk", MODE_PRIVATE)
        installCrashBoundary()
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        if (Build.VERSION.SDK_INT >= 28) {
            val lp = window.attributes
            lp.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
            window.attributes = lp
        }
        setContentView(buildUi())
        overlay.showLoading("Starting…", startNote.ifEmpty { "Looking for GitDesk on your PC" })
    }

    /** Last-resort error boundary: after an uncaught crash the next launch starts in compatibility mode. */
    private fun installCrashBoundary() {
        mode = prefs.getInt("mode", MediaCodecDecoder.MODE_FAST)
        if (prefs.getBoolean("crashed", false)) {
            prefs.edit().putBoolean("crashed", false).apply()
            mode = maxOf(mode, MediaCodecDecoder.MODE_PLAIN)
            startNote = "Recovered from an unexpected error — using compatibility mode."
        }
        val prev = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { t, e ->
            prefs.edit().putBoolean("crashed", true).commit()
            prev?.uncaughtException(t, e)
        }
    }

    private fun buildUi(): FrameLayout {
        val root = FrameLayout(this).apply { setBackgroundColor(Theme.BG) }

        surfaceView = AspectSurfaceView(this)
        surfaceView.holder.addCallback(this)
        root.addView(surfaceView, FrameLayout.LayoutParams(Theme.MATCH, Theme.MATCH, Gravity.CENTER))

        hud = label("", 12f, Theme.WHITE).apply {
            setPadding(dp(10), dp(4), dp(10), dp(4))
            background = pill(0x99000000.toInt(), 12)
            visibility = View.GONE
        }
        root.addView(hud, FrameLayout.LayoutParams(Theme.WRAP, Theme.WRAP, Gravity.TOP or Gravity.START).apply {
            setMargins(dp(12), dp(12), 0, 0)
        })

        menu = FloatingMenu(this, object : FloatingMenu.Callbacks {
            override fun onBitrate(kbps: Int) {
                client?.setBitrate(kbps)
            }

            override fun onHud(show: Boolean) {
                showHud = show
                hud.visibility = if (show && streaming) View.VISIBLE else View.GONE
            }

            override fun onDisconnect() {
                disconnect()
            }
        })
        menu.install(root)

        overlay = LoadingOverlay(this)
        root.addView(overlay, FrameLayout.LayoutParams(Theme.MATCH, Theme.MATCH))
        return root
    }

    @Suppress("DEPRECATION")
    private fun immersive() {
        window.decorView.systemUiVisibility =
            View.SYSTEM_UI_FLAG_LAYOUT_STABLE or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION or
                View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or
                View.SYSTEM_UI_FLAG_FULLSCREEN or View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) {
            immersive()
            requestIdr()            // repaint after system-UI transitions
        }
    }

    // ─────────────────────────── lifecycle ───────────────────────────
    private val ticker = object : Runnable {
        override fun run() {
            try {
                tick()
            } catch (e: Exception) {
                // error boundary: a UI/health-check bug must never take the app down
            }
            ui.postDelayed(this, 500)
        }
    }

    override fun onStart() {
        super.onStart()
        if (!userDisconnected) startClient()
    }

    override fun onStop() {
        stopClient()
        super.onStop()
    }

    override fun onResume() {
        super.onResume()
        ui.post(ticker)
    }

    override fun onPause() {
        ui.removeCallbacks(ticker)
        super.onPause()
    }

    // Surface: only the decoder follows it — the socket keeps running.
    override fun surfaceCreated(holder: SurfaceHolder) {
        surface = holder.surface
        ensureDecoder()
    }

    override fun surfaceChanged(holder: SurfaceHolder, format: Int, width: Int, height: Int) {
        requestIdr()
    }

    override fun surfaceDestroyed(holder: SurfaceHolder) {
        releaseDecoder()
        surface = null
    }

    // ──────────────────────── connection control ────────────────────────
    private fun startClient() {
        if (client != null) return
        overlay.showLoading("Connecting…", startNote.ifEmpty { "Looking for GitDesk on your PC" })
        startNote = ""
        client = SocketClient(this).also { it.start() }
    }

    private fun stopClient() {
        client?.stop()
        client = null
        hello = null
        releaseDecoder()
    }

    private fun disconnect() {
        userDisconnected = true
        captureBackdrop { bmp ->
            stopClient()
            streaming = false
            menu.setActive(false)
            hud.visibility = View.GONE
            overlay.setBackdrop(bmp)
            overlay.showActions(
                "Disconnected",
                "Streaming is paused. Reconnect whenever you're ready.",
                listOf("Reconnect" to { reconnect() })
            )
        }
    }

    private fun reconnect() {
        userDisconnected = false
        stalls = 0
        startClient()
    }

    /** "Quick Reconnect": fresh socket + fresh decoder chain. [safe] jumps straight to the software decoder. */
    private fun quickReconnect(safe: Boolean) {
        userDisconnected = false
        stopClient()
        stalls = 0
        healthyTicks = 0
        streaming = false
        mode = if (safe) MediaCodecDecoder.MODE_SOFTWARE else MediaCodecDecoder.MODE_FAST
        overlay.setBackdrop(null)
        startClient()
    }

    // ──────────────────────────── decoder ────────────────────────────
    private fun ensureDecoder() {
        val h = hello ?: return
        var created = false
        synchronized(decLock) {
            val s = surface ?: return
            if (decoder != null) return
            try {
                decoder = MediaCodecDecoder(s, h.w, h.h, mode) { msg -> ui.post { onDecoderProblem(msg, true) } }
                created = true
            } catch (e: Exception) {
                val m = e.message ?: e.javaClass.simpleName
                ui.post { onDecoderProblem("decoder init failed: $m", true) }
            }
        }
        if (created) requestIdr(true)
    }

    private fun releaseDecoder() {
        synchronized(decLock) {
            decoder?.release()
            decoder = null
        }
    }

    private fun requestIdr(force: Boolean = false) {
        val now = SystemClock.elapsedRealtime()
        if (force || now - lastIdr > 500) {
            lastIdr = now
            client?.requestKeyframe()
        }
    }

    // ───────────────────── health check (UI thread, 2 Hz) ─────────────────────
    private fun tick() {
        val d = decoder ?: return
        val now = SystemClock.elapsedRealtime()
        if (d !== tracked) {
            tracked = d
            lastCount = 0
            lastAt = now
            fpsNow = 0
        }
        val total = d.renderedTotal
        if (now > lastAt) fpsNow = ((total - lastCount) * 1000 / (now - lastAt)).toInt()
        lastCount = total
        lastAt = now

        val idle = now - maxOf(d.lastRenderAt, d.createdAt)
        val feeding = now - d.lastFeedAt < 1500
        when {
            total > 0 && idle < HEALTHY_MS -> onHealthy()
            d.fedTotal > 0 && feeding && idle > STALL_MS -> onDecoderProblem("no picture from decoder", false)
            !streaming && d.fedTotal == 0L && now - d.createdAt > 3000 -> {
                overlay.setSubtitle("Connected — waiting for video from your PC…")
                requestIdr()
            }
            streaming && now - d.lastFeedAt > 2500 -> requestIdr()   // PC went quiet: ask for a fresh keyframe
        }
        if (streaming) {
            hud.text = String.format(Locale.US, "%d fps · %.1f Mbps · %.0f ms", fpsNow, mbps, rttMs)
            menu.updateStats(fpsNow, mbps, rttMs)
        }
    }

    private fun onHealthy() {
        if (!streaming) {
            streaming = true
            overlay.hide()
            menu.setActive(true)
            hud.visibility = if (showHud) View.VISIBLE else View.GONE
        }
        if (++healthyTicks == 6) {                       // ~3 s of steady picture
            stalls = 0
            if (prefs.getInt("mode", -1) != mode) prefs.edit().putInt("mode", mode).apply()
        }
    }

    /**
     * hard = the codec threw / failed to start  -> advance the fallback ladder immediately.
     * soft = frames fed but nothing rendered     -> first retry the same decoder (missed keyframe), then advance.
     */
    private fun onDecoderProblem(reason: String, hard: Boolean) {
        if (hello == null) return
        healthyTicks = 0
        stalls++
        val next = if (hard || stalls >= 2) mode + 1 else mode
        if (next > MediaCodecDecoder.MODE_SOFTWARE) {
            showFatal(reason)
            return
        }
        val switching = next != mode
        mode = next
        streaming = false
        menu.setActive(false)
        hud.visibility = View.GONE
        overlay.showLoading(
            "Optimizing video…",
            if (switching) "Switching to a compatibility decoder" else "Resyncing the stream"
        )
        releaseDecoder()
        ensureDecoder()
    }

    private fun showFatal(reason: String) {
        streaming = false
        menu.setActive(false)
        hud.visibility = View.GONE
        releaseDecoder()
        overlay.setBackdrop(null)
        overlay.showActions(
            "Video couldn't start",
            "This device's video decoder didn't respond ($reason). " +
                "Quick Reconnect restarts the connection; Safe mode uses the software decoder.",
            listOf(
                "Quick Reconnect" to { quickReconnect(false) },
                "Safe mode" to { quickReconnect(true) }
            )
        )
    }

    // ─────────────────── blurred "last frame" backdrop ───────────────────
    private fun captureBackdrop(after: (Bitmap?) -> Unit) {
        val sv = surfaceView
        if (Build.VERSION.SDK_INT < 24 || !streaming || sv.width == 0 || sv.height == 0) {
            after(null)
            return
        }
        try {
            // Copy at 1/12 scale: cheap, and already soft when stretched back over the screen.
            val bmp = Bitmap.createBitmap(maxOf(sv.width / 12, 8), maxOf(sv.height / 12, 8), Bitmap.Config.ARGB_8888)
            PixelCopy.request(sv, bmp, { result -> after(if (result == PixelCopy.SUCCESS) bmp else null) }, ui)
        } catch (e: Exception) {
            after(null)
        }
    }

    // ─────────────── SocketClient.Listener (socket thread) ───────────────
    override fun onState(msg: String) {
        ui.post { overlay.setSubtitle(msg) }
    }

    override fun onHello(width: Int, height: Int, fps: Int) {
        releaseDecoder()
        hello = Hello(width, height, fps)
        ui.post {
            healthyTicks = 0
            surfaceView.holder.setFixedSize(width, height)   // pin the buffer: layout changes can't resize it
            surfaceView.setVideoSize(width, height)
            overlay.showLoading("Starting stream…", "Waiting for the first frame")
        }
        ensureDecoder()
    }

    override fun onVideo(buf: ByteArray, off: Int, len: Int, keyframe: Boolean, ptsUs: Long) {
        val d = decoder ?: return
        if (!d.feed(buf, off, len, ptsUs, keyframe)) requestIdr()
    }

    override fun onStats(fps: Float, kbps: Int, rttMs: Float, targetKbps: Int) {
        ui.post {
            mbps = kbps / 1000f
            this.rttMs = rttMs
            if (targetKbps > 0) menu.setBitrate(targetKbps)
        }
    }

    override fun onDisconnected() {
        hello = null
        ui.post {
            val wasStreaming = streaming
            streaming = false
            menu.setActive(false)
            hud.visibility = View.GONE
            val show = { overlay.showLoading("Connection lost", "Reconnecting to your PC…") }
            if (wasStreaming) {
                captureBackdrop { bmp ->
                    releaseDecoder()
                    overlay.setBackdrop(bmp)
                    show()
                }
            } else {
                releaseDecoder()
                show()
            }
        }
    }

    override fun onDestroy() {
        stopClient()
        super.onDestroy()
    }

    companion object {
        private const val HEALTHY_MS = 1500L
        private const val STALL_MS = 3000L
    }
}
