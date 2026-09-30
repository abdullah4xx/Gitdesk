package dev.gitdesk.client

import android.animation.ObjectAnimator
import android.animation.ValueAnimator
import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Bitmap
import android.graphics.RenderEffect
import android.graphics.Shader
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.view.Gravity
import android.view.View
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView

/**
 * Full-screen glass overlay: blurred backdrop (last video frame, or an indigo gradient) + centred card.
 * Doubles as the friendly error screen (title + message + action buttons).
 * Blur: the last frame is captured at 1/12 scale (already soft when stretched) and, on Android 12+,
 * additionally run through RenderEffect for a real Gaussian blur.
 */
class LoadingOverlay(ctx: Context) : FrameLayout(ctx) {
    private val backdrop = ImageView(ctx)
    private val spinner = ProgressBar(ctx, null, android.R.attr.progressBarStyleLarge)
    private val title = ctx.label("", 22f, Theme.WHITE, true)
    private val sub = ctx.label("", 14f, Theme.MUTED)
    private val hint = ctx.label(
        "Tip: enable USB debugging, plug in the cable, then press “Start streaming” on your PC.",
        12f, Theme.MUTED
    )
    private val actions = LinearLayout(ctx)
    private var pulse: ObjectAnimator? = null

    init {
        isClickable = true                       // swallow touches while visible
        backdrop.scaleType = ImageView.ScaleType.FIT_XY
        addView(backdrop, FrameLayout.LayoutParams(Theme.MATCH, Theme.MATCH))
        addView(View(ctx).apply { setBackgroundColor(0x8C070B18.toInt()) },
            FrameLayout.LayoutParams(Theme.MATCH, Theme.MATCH))

        spinner.indeterminateTintList = ColorStateList.valueOf(Theme.INDIGO)
        sub.gravity = Gravity.CENTER
        sub.maxWidth = ctx.dp(380)
        hint.gravity = Gravity.CENTER
        hint.maxWidth = ctx.dp(380)
        actions.orientation = LinearLayout.HORIZONTAL

        val card = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(ctx.dp(32), ctx.dp(28), ctx.dp(32), ctx.dp(24))
            background = ctx.pill(0xCC131A2E.toInt(), 24)
            addView(spinner, LinearLayout.LayoutParams(ctx.dp(48), ctx.dp(48)))
            addView(title, lp(ctx, 16))
            addView(sub, lp(ctx, 6))
            addView(actions, lp(ctx, 18))
            addView(hint, lp(ctx, 18))
        }
        addView(card, FrameLayout.LayoutParams(Theme.WRAP, Theme.WRAP, Gravity.CENTER))
        setBackdrop(null)
        visibility = View.GONE
    }

    private fun lp(ctx: Context, topDp: Int) = LinearLayout.LayoutParams(Theme.WRAP, Theme.WRAP).apply {
        topMargin = ctx.dp(topDp)
        gravity = Gravity.CENTER_HORIZONTAL
    }

    /** Spinner state: "waiting for the stream". */
    fun showLoading(t: String, s: String) {
        title.text = t
        sub.text = s
        spinner.visibility = View.VISIBLE
        actions.removeAllViews()
        actions.visibility = View.GONE
        hint.visibility = View.VISIBLE
        startPulse()
        reveal()
    }

    /** Message state (errors, disconnected): no spinner, one or more action buttons. */
    fun showActions(t: String, msg: String, items: List<Pair<String, () -> Unit>>) {
        title.text = t
        sub.text = msg
        spinner.visibility = View.GONE
        hint.visibility = View.GONE
        stopPulse()
        actions.removeAllViews()
        items.forEachIndexed { i, (text, fn) ->
            val b = context.chip(text, if (i == 0) Theme.INDIGO else Theme.CHIP, 14f, 18) { fn() }
            actions.addView(b, LinearLayout.LayoutParams(Theme.WRAP, Theme.WRAP).apply {
                if (i > 0) leftMargin = context.dp(10)
            })
        }
        actions.visibility = View.VISIBLE
        reveal()
    }

    /** Only touches the subtitle while the spinner is showing (never overwrites an error message). */
    fun setSubtitle(s: String) {
        if (spinner.visibility == View.VISIBLE) sub.text = s
    }

    fun setBackdrop(bmp: Bitmap?) {
        if (bmp != null) {
            backdrop.setImageBitmap(bmp)
            if (Build.VERSION.SDK_INT >= 31) {
                backdrop.setRenderEffect(RenderEffect.createBlurEffect(28f, 28f, Shader.TileMode.CLAMP))
            }
        } else {
            backdrop.setImageDrawable(
                GradientDrawable(
                    GradientDrawable.Orientation.TL_BR,
                    intArrayOf(0xFF0B1020.toInt(), 0xFF1E1B4B.toInt(), 0xFF0B1020.toInt())
                )
            )
            if (Build.VERSION.SDK_INT >= 31) backdrop.setRenderEffect(null)
        }
    }

    fun hide() {
        if (visibility != View.VISIBLE) return
        stopPulse()
        animate().cancel()
        animate().alpha(0f).setDuration(260).withEndAction {
            visibility = View.GONE
            setBackdrop(null)
        }.start()
    }

    private fun reveal() {
        animate().cancel()
        if (visibility != View.VISIBLE) {
            alpha = 0f
            visibility = View.VISIBLE
        }
        animate().alpha(1f).setDuration(220).start()
    }

    private fun startPulse() {
        if (pulse?.isRunning == true) return
        pulse = ObjectAnimator.ofFloat(sub, "alpha", 1f, 0.45f).apply {
            duration = 900
            repeatMode = ValueAnimator.REVERSE
            repeatCount = ValueAnimator.INFINITE
            start()
        }
    }

    private fun stopPulse() {
        pulse?.cancel()
        pulse = null
        sub.alpha = 1f
    }
}
