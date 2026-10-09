import { useEffect, useState } from 'react';
import { STATUS_PATH } from '../net/wireProtocol';
import { parseRelayStatus, type Sample } from '../net/relayStatus';

const POLL_MS = 2000;
const TIMEOUT_MS = 3000;
/** One missed poll is not an outage; two in a row is. */
const MISSES_BEFORE_LOST = 2;

/** Polls the server's /status. `undefined` until the first answer; `null` once the server is unreachable. */
export function useRelayStatus(enabled: boolean): Sample | undefined {
  const [sample, setSample] = useState<Sample | undefined>(undefined);

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    let misses = 0;
    let timer: ReturnType<typeof setTimeout>;
    setSample(undefined);

    const poll = async () => {
      const abort = new AbortController();
      const cutoff = setTimeout(() => abort.abort(), TIMEOUT_MS);
      try {
        const response = await fetch(STATUS_PATH, { signal: abort.signal, cache: 'no-store' });
        const parsed = response.ok ? parseRelayStatus(await response.json()) : null;
        if (!alive) return;
        if (parsed) {
          misses = 0;
          setSample(parsed);
        } else {
          misses += 1;
        }
      } catch {
        if (!alive) return;
        misses += 1;
      } finally {
        clearTimeout(cutoff);
      }
      if (alive && misses >= MISSES_BEFORE_LOST) setSample(null);
      if (alive) timer = setTimeout(poll, POLL_MS);
    };
    void poll();

    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [enabled]);

  return sample;
}
