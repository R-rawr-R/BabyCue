import { Plug } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Button } from '../components/Button';
import { HoldToStop } from '../components/HoldToStop';
import {
  cameraProblemText,
  describeCameraError,
  openCamera,
  useWakeLock,
  type CameraProblem,
} from '../device';
import { FRAME_PATH } from '../net/wireProtocol';
import { FramePusher, linkText, type LinkState } from '../streaming/FramePusher';

// Small, light pictures keep the delay low and the picture moving: about 15 a second at 480 px wide.
const MAX_WIDTH = 480;
const MIN_FRAME_GAP_MS = 66;
const JPEG_QUALITY = 0.5;
const UPLOAD_TIMEOUT_MS = 5000;

/** Baby phone: films the crib and sends every picture to the home PC. Dark, so it does not light up the room. */
export function BabyScreen({ onStop }: { onStop: () => void }) {
  useWakeLock(true);
  const video = useRef<HTMLVideoElement>(null);
  const [ready, setReady] = useState(false);
  const [problem, setProblem] = useState<CameraProblem | null>(null);
  const [link, setLink] = useState<LinkState | null>(null);
  const [attempt, setAttempt] = useState(0);

  // A phone that was locked or switched away from may have stopped the camera: open it again on return.
  useEffect(() => {
    const onVisible = () => {
      const stream = video.current?.srcObject as MediaStream | null;
      if (document.visibilityState === 'visible' && stream?.getTracks().some((t) => t.readyState === 'ended')) {
        setReady(false);
        setAttempt((n) => n + 1);
      }
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, []);

  useEffect(() => {
    let stream: MediaStream | null = null;
    let cancelled = false;
    openCamera()
      .then(async (s) => {
        if (cancelled) {
          s.getTracks().forEach((t) => t.stop());
          return;
        }
        stream = s;
        const el = video.current;
        if (!el) return;
        el.srcObject = s;
        await el.play();
        setReady(true);
      })
      .catch((error) => !cancelled && setProblem(describeCameraError(error)));
    return () => {
      cancelled = true;
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, [attempt]);

  const pusher = useMemo(() => {
    const canvas = document.createElement('canvas');
    let last = 0;
    return new FramePusher(
      {
        capture: async () => {
          const wait = MIN_FRAME_GAP_MS - (performance.now() - last);
          if (wait > 0) await new Promise((r) => setTimeout(r, wait));
          last = performance.now();
          const el = video.current;
          if (!el || el.readyState < 2 || el.videoWidth === 0) return null;
          const scale = Math.min(1, MAX_WIDTH / el.videoWidth);
          canvas.width = Math.round(el.videoWidth * scale);
          canvas.height = Math.round(el.videoHeight * scale);
          canvas.getContext('2d')?.drawImage(el, 0, 0, canvas.width, canvas.height);
          return new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', JPEG_QUALITY));
        },
        upload: async (jpeg) => {
          const abort = new AbortController();
          const cutoff = setTimeout(() => abort.abort(new Error('upload timed out')), UPLOAD_TIMEOUT_MS);
          try {
            const response = await fetch(FRAME_PATH, {
              method: 'POST',
              body: jpeg,
              headers: { 'Content-Type': 'image/jpeg' },
              cache: 'no-store',
              signal: abort.signal,
            });
            return response.status;
          } finally {
            clearTimeout(cutoff);
          }
        },
        sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
      },
      (state) => {
        setLink(state);
        // The camera went quiet without ending its track (seen after a screen lock): open it again.
        if (state.kind === 'no-picture') {
          setReady(false);
          setAttempt((n) => n + 1);
        }
      },
    );
  }, []);

  useEffect(() => {
    if (!ready) return;
    pusher.start();
    return () => pusher.stop();
  }, [pusher, ready]);

  const streaming = link?.kind === 'connected';

  return (
    <main className="baby">
      <div className="top">
        <Plug size={16} strokeWidth={2.75} aria-hidden />
        Keep plugged in
      </div>

      <div className="middle">
        <div className="preview" role="img" aria-label="Camera preview">
          <video ref={video} muted playsInline autoPlay />
          <div className="pill" style={{ color: streaming ? '#b9cb98' : '#f5c96f' }}>
            <span className="d" />
            <span style={{ color: 'var(--baby-text)' }}>{streaming ? 'Streaming' : 'Connecting'}</span>
          </div>
        </div>
        <div className="copy">
          <h1>Watching over your baby</h1>
          <p className="lead">Sending video to the home PC. Keep this phone plugged in and pointed at the crib.</p>
          <p className="link-text" role="status" aria-live="polite">
            {problem ? cameraProblemText[problem] : linkText(link)}
          </p>
        </div>
      </div>

      <div className="controls">
        {problem ? <Button className="quiet" haptic="leave" style={{ width: '100%' }} onClick={onStop}>Back</Button> : <HoldToStop onStop={onStop} />}
        <p className="tiny">Hold for 2 seconds so little hands can't stop it</p>
      </div>
    </main>
  );
}
