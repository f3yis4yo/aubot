import { createContext, useContext, useEffect, useLayoutEffect, useRef } from 'react'
import type { StaffUser } from '../types'
import type { PushEvent } from '../useSocket'

export interface StaffCtx {
  user: StaffUser
  live: boolean
  openCases: number
  refreshCounts: () => void
  subscribe: (fn: (e: PushEvent) => void) => () => void
}

export const Ctx = createContext<StaffCtx | null>(null)
export const useStaff = () => useContext(Ctx)!

/** Subscribe a page to live staff events; the handler can change every render. */
export function useStaffEvents(fn: (e: PushEvent) => void) {
  const { subscribe } = useStaff()
  const ref = useRef(fn)
  useLayoutEffect(() => {
    ref.current = fn
  })
  useEffect(() => subscribe((e) => ref.current(e)), [subscribe])
}
