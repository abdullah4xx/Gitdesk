package dev.gitdesk.client

import android.content.Context
import android.view.SurfaceView

/** SurfaceView that letter-boxes itself to the video aspect ratio. */
class AspectSurfaceView(ctx: Context) : SurfaceView(ctx) {
    private var vw = 0
    private var vh = 0

    fun setVideoSize(w: Int, h: Int) {
        if (w == vw && h == vh) return
        vw = w
        vh = h
        requestLayout()
    }

    override fun onMeasure(widthSpec: Int, heightSpec: Int) {
        val mw = MeasureSpec.getSize(widthSpec)
        val mh = MeasureSpec.getSize(heightSpec)
        if (vw == 0 || vh == 0) {
            setMeasuredDimension(mw, mh)
            return
        }
        var w = mw
        var h = mw * vh / vw
        if (h > mh) {
            h = mh
            w = mh * vw / vh
        }
        setMeasuredDimension(w, h)
    }
}
