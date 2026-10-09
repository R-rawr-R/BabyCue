import { useEffect, useRef, useState } from 'react';
import { VIEW_PATH } from '../net/wireProtocol';

/**
 * Shows the server's /view stream (multipart JPEG): an <img> plays it natively, and is pointed at the stream
 * again whenever it drops. /view accepts up to four viewers; a refused one retries.
 */
export function VideoPanel({ label, lost, streaming }: { label: string; lost: boolean; streaming: boolean }) {
  const [src, setSrc] = useState<string | null>(null);
  const retry = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    if (!streaming || lost) {
      setSrc(null);
      return;
    }
    setSrc(`${VIEW_PATH}?t=${Date.now()}`);
    return () => clearTimeout(retry.current);
  }, [streaming, lost]);

  return (
    <div className="video" role="img" aria-label={label}>
      <div className="glow" />
      <div className="inset" />
      {src ? (
        <img
          src={src}
          alt=""
          onError={() => {
            clearTimeout(retry.current);
            retry.current = setTimeout(() => setSrc(`${VIEW_PATH}?t=${Date.now()}`), 1500);
          }}
        />
      ) : null}
      {lost ? (
        <div className="lost">
          <span className="spinner" />
          Reconnecting…
        </div>
      ) : null}
    </div>
  );
}
