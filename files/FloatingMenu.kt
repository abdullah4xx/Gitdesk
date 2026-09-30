package dev.gitdesk.client

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import java.util.Locale

/**
 * Floating quick-controls: a translucent ⋮ button opens a glass panel with live FPS / RTT / bitrate,
 * a bitrate switcher (2 / 4 / 6 Mbps, applied live on the PC), an FPS-overlay toggle and Disconnect.
 * Auto-hides after a few seconds.
 */
class FloatingMenu(private val ctx: Context, private val cb: Callbacks) {

    interface Callbacks {
        fun onBitrate(kbps: Int)
        fun onHud(show: Boolean)
        fun onDisconnect()
    }

    private val handler = Handler(Looper.getMainLooper())
    private val autoHide = Runnable { hide() }
    private val fab = ctx.chip("⋮", 0x99131A2E.toInt(), 18f, 0) { toggle() }
    private val panel = LinearLayout(ctx)
    private val fpsV = ctx.label("–", 20f, Theme.WHITE, true)
    private val rttV = ctx.label("–", 20f, Theme.WHITE, true)
    private val mbpsV = ctx.label("–", 20f, Theme.WHITE, true)
    private val hudChip: TextView
    private val presets = listOf(2000 to "2 Mbps", 4000 to "4 Mbps", 6000 to "6 Mbps")
    private val presetViews = mutableListOf<TextView>()
    private var selected = 0
    private var hud = true

    init {
        hudChip = ctx.chip("FPS overlay: ON", Theme.CHIP, 12f, 10) { toggleHud() }
        panel.apply {
            orientation = LinearLayout.VERTICAL
            setPadding(ctx.dp(16), ctx.dp(14), ctx.dp(16), ctx.dp(16))
            background = ctx.pill(Theme.GLASS, 20)
            visibility = View.GONE
            alpha = 0f
            addView(ctx.label("GitDesk", 16f, Theme.WHITE, true))

            val stats = LinearLayout(ctx).apply {
                orientation = LinearLayout.HORIZONTAL
                for ((v, cap) in listOf(fpsV to "FPS", rttV to "RTT ms", mbpsV to "Mbps")) {
                    addView(stat(v, cap), LinearLayout.LayoutParams(0, Theme.WRAP, 1f))
                }
            }
            addView(stats, gap(12))

            addView(ctx.label("Quality (live)", 11f, Theme.MUTED), gap(12))
            val row = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL }
            presets.forEachIndexed { i, (kbps, text) ->
                val c = ctx.chip(text, Theme.CHIP, 12f, 6) { select(kbps, true) }
                presetViews += c
                row.addView(c, LinearLayout.LayoutParams(0, Theme.WRAP, 1f).apply {
                    if (i > 0) leftMargin = ctx.dp(6)
                })
            }
            addView(row, gap(6))

            val bottom = LinearLayout(ctx).apply {
                orientation = LinearLayout.HORIZONTAL
                addView(hudChip, LinearLayout.LayoutParams(0, Theme.WRAP, 1f))
                addView(ctx.chip("Disconnect", Theme.RED, 12f, 10) { cb.onDisconnect() },
                    LinearLayout.LayoutParams(0, Theme.WRAP, 1f).apply { leftMargin = ctx.dp(6) })
            }
            addView(bottom, gap(12))
        }
        fab.visibility = View.GONE
    }

    fun install(root: FrameLayout) {
        root.addView(panel, FrameLayout.LayoutParams(ctx.dp(290), Theme.WRAP, Gravity.TOP or Gravity.END).apply {
            setMargins(0, ctx.dp(64), ctx.dp(12), 0)
        })
        root.addView(fab, FrameLayout.LayoutParams(ctx.dp(44), ctx.dp(44), Gravity.TOP or Gravity.END).apply {
            setMargins(0, ctx.dp(12), ctx.dp(12), 0)
        })
    }

    /** Show the ⋮ button only while a stream is actually on screen. */
    fun setActive(active: Boolean) {
        fab.visibility = if (active) View.VISIBLE else View.GONE
        if (!active) {
            handler.removeCallbacks(autoHide)
            panel.animate().cancel()
            panel.visibility = View.GONE
            panel.alpha = 0f
        }
    }

    fun updateStats(fps: Int, mbps: Float, rttMs: Float) {
        fpsV.text = fps.toString()
        rttV.text = String.format(Locale.US, "%.0f", rttMs)
        mbpsV.text = String.format(Locale.US, "%.1f", mbps)
    }

    fun setBitrate(kbps: Int) = select(kbps, false)

    private fun select(kbps: Int, notify: Boolean) {
        selected = kbps
        presets.forEachIndexed { i, (k, _) ->
            presetViews[i].background = ctx.pill(if (k == kbps) Theme.INDIGO else Theme.CHIP, 20)
        }
        if (notify) {
            cb.onBitrate(kbps)
            poke()
        }
    }

    private fun toggleHud() {
        hud = !hud
        hudChip.text = "FPS overlay: " + if (hud) "ON" else "OFF"
        cb.onHud(hud)
        poke()
    }

    private fun toggle() = if (panel.visibility == View.VISIBLE) hide() else show()

    private fun show() {
        panel.animate().cancel()
        panel.translationY = -ctx.dp(8).toFloat()
        panel.visibility = View.VISIBLE
        panel.animate().alpha(1f).translationY(0f).setDuration(180).start()
        poke()
    }

    private fun hide() {
        handler.removeCallbacks(autoHide)
        panel.animate().cancel()
        panel.animate().alpha(0f).translationY(-ctx.dp(8).toFloat()).setDuration(150)
            .withEndAction { panel.visibility = View.GONE }.start()
    }

    private fun poke() {
        handler.removeCallbacks(autoHide)
        handler.postDelayed(autoHide, 6000)
    }

    private fun stat(v: TextView, caption: String) = LinearLayout(ctx).apply {
        orientation = LinearLayout.VERTICAL
        gravity = Gravity.CENTER
        addView(v)
        addView(ctx.label(caption, 10f, Theme.MUTED))
    }

    private fun gap(dpTop: Int) = LinearLayout.LayoutParams(Theme.MATCH, Theme.WRAP).apply { topMargin = ctx.dp(dpTop) }
}
