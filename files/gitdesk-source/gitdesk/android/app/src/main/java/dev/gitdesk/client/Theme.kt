package dev.gitdesk.client

import android.content.Context
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.widget.TextView

object Theme {
    const val MATCH = -1
    const val WRAP = -2
    val BG = 0xFF0B1020.toInt()
    val CARD = 0xFF131A2E.toInt()
    val GLASS = 0xE6131A2E.toInt()
    val CHIP = 0xFF1E2A4A.toInt()
    val INDIGO = 0xFF6366F1.toInt()
    val INDIGO_L = 0xFFC7D2FE.toInt()
    val MUTED = 0xFF94A3B8.toInt()
    val RED = 0xFFDC2626.toInt()
    val WHITE = 0xFFFFFFFF.toInt()
}

fun Context.dp(v: Int): Int = (v * resources.displayMetrics.density).toInt()

fun Context.pill(color: Int, radiusDp: Int): GradientDrawable = GradientDrawable().apply {
    setColor(color)
    cornerRadius = dp(radiusDp).toFloat()
}

fun Context.label(t: String, sp: Float, color: Int, bold: Boolean = false): TextView = TextView(this).apply {
    text = t
    textSize = sp
    setTextColor(color)
    if (bold) setTypeface(typeface, Typeface.BOLD)
}

fun Context.chip(t: String, fill: Int, sp: Float = 14f, padH: Int = 16, onClick: () -> Unit): TextView =
    TextView(this).apply {
        text = t
        textSize = sp
        setTextColor(Theme.WHITE)
        gravity = Gravity.CENTER
        setPadding(dp(padH), dp(10), dp(padH), dp(10))
        background = pill(fill, 20)
        setOnClickListener { onClick() }
    }
