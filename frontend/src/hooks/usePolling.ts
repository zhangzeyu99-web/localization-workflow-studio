import { useEffect } from 'react'

export interface UsePollingOptions {
  intervalMs: number
  enabled: boolean
  skipWhenHidden?: boolean
}

export type PollTick = (isStale: () => boolean) => void | Promise<void>

// Generic polling primitive shared by the app's setInterval-based pollers:
// wraps a window.setInterval with a shared in-flight promise dedupe (a tick
// never starts while the previous tick from the same interval is still
// awaiting) and an optional document.hidden skip. `deps` mirrors a
// useEffect dependency array: the interval is torn down and recreated
// whenever these values change, exactly like the original per-poller
// useEffect blocks. The tick receives `isStale()`, which flips to true once
// this effect instance is cleaned up, so async callbacks can avoid applying
// results after teardown (mirrors the previous ad-hoc `cancelled` flags).
export function usePolling(tick: PollTick, options: UsePollingOptions, deps: React.DependencyList) {
  useEffect(() => {
    if (!options.enabled) return undefined
    let cancelled = false
    let inFlight = false
    const run = () => {
      if (options.skipWhenHidden && document.hidden) return
      if (inFlight) return
      inFlight = true
      Promise.resolve(tick(() => cancelled)).finally(() => {
        inFlight = false
      })
    }
    const poller = window.setInterval(run, options.intervalMs)
    return () => {
      cancelled = true
      window.clearInterval(poller)
    }
    // Deps are supplied by each call site to mirror the original per-poller
    // useEffect dependency arrays; see usage in hooks/use*Polling.ts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
}
