import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { wsUrl } from './api'

export interface PushEvent {
  event: string
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- payload shape depends on the event name
  payload: any
}

/** Server-push WebSocket with exponential-backoff reconnect. Pass null to stay disconnected. */
export function useSocket(path: string | null, onEvent: (e: PushEvent) => void) {
  const [connected, setConnected] = useState(false)
  const handler = useRef(onEvent)
  useLayoutEffect(() => {
    handler.current = onEvent
  })

  useEffect(() => {
    if (!path) return
    let ws: WebSocket | null = null
    let retry = 0
    let timer: number | undefined
    let stopped = false

    const open = () => {
      ws = new WebSocket(wsUrl(path))
      ws.onopen = () => {
        retry = 0
        setConnected(true)
      }
      ws.onmessage = (msg) => {
        try {
          handler.current(JSON.parse(msg.data))
        } catch {
          /* ignore malformed frames */
        }
      }
      ws.onclose = (ev) => {
        setConnected(false)
        if (stopped || ev.code === 4401 || ev.code === 4403) return
        timer = window.setTimeout(open, Math.min(15000, 500 * 2 ** retry++))
      }
    }
    open()
    return () => {
      stopped = true
      window.clearTimeout(timer)
      ws?.close()
    }
  }, [path])

  return connected
}
