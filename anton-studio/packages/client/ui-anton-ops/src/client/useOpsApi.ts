import { useCallback, useEffect, useState } from 'react'

/** Fetch state for one Ops Center API read, plus a manual re-fetch trigger. */
export type OpsApiState<T> = { data: T | null; loading: boolean; error: boolean; refetch: () => void }

/**
 * Fetches one Ops Center API path (proxied through apiproxy to anton's
 * FastAPI dashboard — see packages/host/apiproxy/src/index.ts) and tracks
 * loading/error state. Re-fetches whenever `path` changes, or `refetch()` is
 * called (e.g. a screen returning from a child editor after a write this
 * hook has no other way to observe); ignores a response that resolves after
 * the component has moved on to a new path/revision or unmounted.
 */
export function useOpsApi<T>(path: string): OpsApiState<T> {
  const [state, setState] = useState<{ data: T | null; loading: boolean; error: boolean }>(
    { data: null, loading: true, error: false },
  )
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    let cancelled = false
    setState({ data: null, loading: true, error: false })
    fetch(path)
      .then((r) => {
        if (!r.ok) throw new Error(`${path}: ${r.status}`)
        return r.json() as Promise<T>
      })
      .then((data) => { if (!cancelled) setState({ data, loading: false, error: false }) })
      .catch(() => { if (!cancelled) setState({ data: null, loading: false, error: true }) })
    return () => { cancelled = true }
  }, [path, revision])

  const refetch = useCallback(() => { setRevision(r => r + 1) }, [])

  return { ...state, refetch }
}
