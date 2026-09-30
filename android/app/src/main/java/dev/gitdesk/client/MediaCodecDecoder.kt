package dev.gitdesk.client

import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaCodecList
import android.media.MediaFormat
import android.os.Build
import android.os.SystemClock
import android.view.Surface

/**
 * H.264/AVC decoder rendering straight into a Surface.
 * Modes form a fallback ladder for devices with quirky hardware decoders (e.g. Snapdragon 662):
 *   FAST     hardware decoder + real-time priority + low-latency hint
 *   PLAIN    hardware decoder, no vendor hints
 *   SOFTWARE Google software decoder (slowest, but always renders)
 */
class MediaCodecDecoder(
    surface: Surface,
    width: Int,
    height: Int,
    private val mode: Int,
    private val onError: (String) -> Unit,
) {
    private val codec: MediaCodec = pickCodec(mode)
    private val drain = Thread(::drainLoop, "gd-drain")
    @Volatile private var running = true

    val createdAt: Long = SystemClock.elapsedRealtime()
    @Volatile var renderedTotal = 0L
        private set
    @Volatile var fedTotal = 0L
        private set
    @Volatile var lastRenderAt = 0L
        private set
    @Volatile var lastFeedAt = 0L
        private set
    val name: String get() = codec.name

    init {
        try {
            val fmt = MediaFormat.createVideoFormat(MediaFormat.MIMETYPE_VIDEO_AVC, width, height)
            fmt.setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, 2 * 1024 * 1024)
            if (mode == MODE_FAST) {
                if (Build.VERSION.SDK_INT >= 23) fmt.setInteger(MediaFormat.KEY_PRIORITY, 0)   // real-time
                if (Build.VERSION.SDK_INT >= 30) fmt.setInteger(MediaFormat.KEY_LOW_LATENCY, 1)
            }
            codec.configure(fmt, surface, null, 0)
            codec.start()
        } catch (e: Exception) {
            try { codec.release() } catch (_: Exception) {}
            throw e
        }
        drain.start()
    }

    /** Returns false if the frame had to be dropped (caller should request a keyframe). */
    fun feed(buf: ByteArray, off: Int, len: Int, ptsUs: Long, keyframe: Boolean): Boolean {
        if (!running) return true
        return try {
            val i = codec.dequeueInputBuffer(15_000)
            if (i < 0) return false
            val ib = codec.getInputBuffer(i) ?: return false
            if (len > ib.capacity()) {
                codec.queueInputBuffer(i, 0, 0, ptsUs, 0)
                return false
            }
            ib.clear()
            ib.put(buf, off, len)
            codec.queueInputBuffer(i, 0, len, ptsUs, if (keyframe) MediaCodec.BUFFER_FLAG_KEY_FRAME else 0)
            fedTotal++
            lastFeedAt = SystemClock.elapsedRealtime()
            true
        } catch (e: MediaCodec.CodecException) {
            if (running) onError("codec error: ${e.message}")
            true
        } catch (e: IllegalStateException) {
            true   // released concurrently
        }
    }

    private fun drainLoop() {
        val info = MediaCodec.BufferInfo()
        while (running) {
            try {
                val i = codec.dequeueOutputBuffer(info, 10_000)
                if (i >= 0) {
                    codec.releaseOutputBuffer(i, true)     // render immediately, no vsync scheduling
                    renderedTotal++
                    lastRenderAt = SystemClock.elapsedRealtime()
                }
            } catch (e: MediaCodec.CodecException) {
                if (running) onError("codec error: ${e.message}")
                break
            } catch (e: IllegalStateException) {
                break
            }
        }
    }

    fun release() {
        if (!running) return
        running = false
        try { drain.join(300) } catch (_: InterruptedException) {}
        try { codec.stop() } catch (_: Exception) {}
        try { codec.release() } catch (_: Exception) {}
    }

    private fun pickCodec(mode: Int): MediaCodec {
        if (mode >= MODE_SOFTWARE) {
            val sw = MediaCodecList(MediaCodecList.REGULAR_CODECS).codecInfos.firstOrNull { info ->
                !info.isEncoder && isSoftware(info) &&
                    info.supportedTypes.any { it.equals(MediaFormat.MIMETYPE_VIDEO_AVC, ignoreCase = true) }
            }
            if (sw != null) return MediaCodec.createByCodecName(sw.name)
        }
        return MediaCodec.createDecoderByType(MediaFormat.MIMETYPE_VIDEO_AVC)
    }

    private fun isSoftware(i: MediaCodecInfo): Boolean =
        if (Build.VERSION.SDK_INT >= 29) i.isSoftwareOnly
        else i.name.startsWith("OMX.google.") || i.name.startsWith("c2.android.")

    companion object {
        const val MODE_FAST = 0
        const val MODE_PLAIN = 1
        const val MODE_SOFTWARE = 2
    }
}
