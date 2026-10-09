import { useEffect, useState } from 'react';
import { fetchDetections, type LoggedDetection } from '../net/database';

const REFRESH_MS = 5000;

/** The server's detection log, refreshed while `active`. `null` until the first answer; keeps the last list on error. */
export function useDetectionLog(active: boolean): { entries: LoggedDetection[] | null; failed: boolean } {
  const [entries, setEntries] = useState<LoggedDetection[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!active) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const next = await fetchDetections();
        if (!alive) return;
        setEntries(next);
        setFailed(false);
      } catch {
        if (alive) setFailed(true);
      }
      if (alive) timer = setTimeout(load, REFRESH_MS);
    };
    void load();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [active]);

  return { entries, failed };
}
