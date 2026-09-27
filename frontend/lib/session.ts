"use client";

import React from "react";

/* State a person typed or chose, kept for this browser tab (sessionStorage): it survives a reload and moving
   between pages, and is gone when the tab closes. The first render uses `initial`, as the server rendered
   it; the saved value is applied once mounted. `revive` repairs a saved value that only made sense while the
   page was open — a request in flight, say. Storage that is unavailable or full only means nothing is kept. */
export function useSessionState<T>(key: string, initial: T, revive?: (saved: T) => T) {
  const [value, setValue] = React.useState<T>(initial);
  // State, not a ref: the first write waits for the render that already holds the saved value, so a
  // default is never written over what was kept (Strict Mode mounts twice and would read it back).
  const [restored, setRestored] = React.useState(false);
  React.useEffect(() => {
    try {
      const raw = window.sessionStorage.getItem(key);
      if (raw !== null) {
        const saved = JSON.parse(raw) as T;
        setValue(revive ? revive(saved) : saved);
      }
    } catch { /* nothing kept */ }
    setRestored(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  React.useEffect(() => {
    if (!restored) return;
    try { window.sessionStorage.setItem(key, JSON.stringify(value)); } catch { /* not kept */ }
  }, [key, value, restored]);
  return [value, setValue] as const;
}
