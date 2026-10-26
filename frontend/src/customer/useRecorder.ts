import { useCallback, useRef, useState } from 'react'

const MAX_SECONDS = 45

function pickMime(): string {
  const options = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus']
  return options.find((t) => typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(t)) ?? ''
}

/** Microphone capture. The stream is stopped as soon as recording ends, and the
 *  recording only ever exists in memory until it is posted for transcription. */
export function useRecorder() {
  const [recording, setRecording] = useState(false)
  const recorder = useRef<MediaRecorder | null>(null)
  const chunks = useRef<Blob[]>([])
  const resolver = useRef<((b: Blob | null) => void) | null>(null)
  const timer = useRef<number | undefined>(undefined)

  const supported = typeof window !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== 'undefined'

  const start = useCallback(async (onAutoStop: (blob: Blob | null) => void) => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
    const mime = pickMime()
    const rec = new MediaRecorder(stream, mime ? { mimeType: mime, audioBitsPerSecond: 32000 } : undefined)
    chunks.current = []
    rec.ondataavailable = (e) => e.data.size && chunks.current.push(e.data)
    rec.onstop = () => {
      stream.getTracks().forEach((t) => t.stop())
      const blob = chunks.current.length ? new Blob(chunks.current, { type: rec.mimeType || 'audio/webm' }) : null
      chunks.current = []
      setRecording(false)
      resolver.current?.(blob)
      resolver.current = null
    }
    recorder.current = rec
    rec.start()
    setRecording(true)
    timer.current = window.setTimeout(() => {
      if (rec.state !== 'recording') return
      resolver.current = onAutoStop // time limit reached: still send what was said
      rec.stop()
    }, MAX_SECONDS * 1000)
  }, [])

  const stop = useCallback(
    () =>
      new Promise<Blob | null>((resolve) => {
        window.clearTimeout(timer.current)
        const rec = recorder.current
        if (!rec || rec.state !== 'recording') return resolve(null)
        resolver.current = resolve
        rec.stop()
      }),
    [],
  )

  return { supported, recording, start, stop }
}
