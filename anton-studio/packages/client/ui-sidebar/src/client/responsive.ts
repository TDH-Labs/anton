import { useEffect, useState } from 'react'

/** README, "Interactions & Behavior" — "Below roughly 1180px the live strip unpins." */
const LIVE_STRIP_UNPIN_QUERY = '(max-width: 1180px)'

/**
 * Whether the viewport is narrow enough that the live strip should unpin.
 * Shared by LiveStrip.tsx (to stop rendering itself) and OpsCockpit.tsx (to
 * stop reserving the 322px it would otherwise occupy) — both must agree on
 * the same breakpoint or the ops overlay leaves a blank gap where the strip
 * used to be.
 */
export function useLiveStripUnpinned(): boolean {
  const [unpinned, setUnpinned] = useState(() => (
    typeof window === 'undefined' ? false : window.matchMedia(LIVE_STRIP_UNPIN_QUERY).matches
  ))

  useEffect(() => {
    const mql = window.matchMedia(LIVE_STRIP_UNPIN_QUERY)
    const onChange = () => { setUnpinned(mql.matches) }
    onChange()
    mql.addEventListener('change', onChange)
    return () => { mql.removeEventListener('change', onChange) }
  }, [])

  return unpinned
}
