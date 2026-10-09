import { useEffect, useState } from 'react';

export function isStandalone(): boolean {
  return window.matchMedia('(display-mode: standalone)').matches || (navigator as { standalone?: boolean }).standalone === true;
}

export function isIos(): boolean {
  return /iphone|ipad|ipod/i.test(navigator.userAgent);
}

/** Browsers only give out the camera on HTTPS (or localhost). */
export function cameraAvailable(): boolean {
  return window.isSecureContext && typeof navigator.mediaDevices?.getUserMedia === 'function';
}

export type CameraProblem = 'insecure' | 'blocked' | 'missing' | 'busy' | 'unknown';

export function describeCameraError(error: unknown): CameraProblem {
  const name = error instanceof DOMException ? error.name : '';
  if (name === 'NotAllowedError' || name === 'SecurityError') return 'blocked';
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'missing';
  if (name === 'NotReadableError' || name === 'AbortError') return 'busy';
  return 'unknown';
}

export const cameraProblemText: Record<CameraProblem, string> = {
  insecure:
    "The browser blocks the camera on pages that aren't secure. Open the https:// address the BabyCue server printed, then accept the certificate warning once.",
  blocked: 'The camera is blocked for BabyCue. Allow it in the browser (lock icon next to the address), then try again.',
  missing: "This device doesn't have a camera BabyCue can use.",
  busy: 'The camera is being used by another app. Close it and try again.',
  unknown: "The camera couldn't start. Try again.",
};

/** Opens the camera, preferring the back one, and returns the stream. */
export function openCamera(): Promise<MediaStream> {
  return navigator.mediaDevices.getUserMedia({
    audio: false,
    video: { facingMode: { ideal: 'environment' }, width: { ideal: 640 }, height: { ideal: 360 }, frameRate: { ideal: 15, max: 30 } },
  });
}

type InstallEvent = Event & { prompt(): Promise<void> };

/** Chrome offers its own install prompt; this keeps it until the user taps our button. */
export function useInstallPrompt(): (() => void) | null {
  const [event, setEvent] = useState<InstallEvent | null>(null);
  useEffect(() => {
    const onPrompt = (e: Event) => {
      e.preventDefault();
      setEvent(e as InstallEvent);
    };
    const onInstalled = () => setEvent(null);
    window.addEventListener('beforeinstallprompt', onPrompt);
    window.addEventListener('appinstalled', onInstalled);
    return () => {
      window.removeEventListener('beforeinstallprompt', onPrompt);
      window.removeEventListener('appinstalled', onInstalled);
    };
  }, []);
  return event ? () => void event.prompt() : null;
}

/** Keeps the screen on while `active` (the baby phone and the live view must not fall asleep). */
export function useWakeLock(active: boolean): void {
  useEffect(() => {
    if (!active || !('wakeLock' in navigator)) return;
    let lock: WakeLockSentinel | null = null;
    let cancelled = false;
    const acquire = () => {
      navigator.wakeLock
        .request('screen')
        .then((l) => {
          if (cancelled) void l.release();
          else lock = l;
        })
        .catch(() => undefined);
    };
    const onVisible = () => {
      if (document.visibilityState === 'visible') acquire();
    };
    acquire();
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      cancelled = true;
      document.removeEventListener('visibilitychange', onVisible);
      void lock?.release();
    };
  }, [active]);
}

/** Plays a one-off shake on the element whenever `key` changes to something truthy (not on first render). */
export function useShake(el: React.RefObject<HTMLElement | null>, key: string, amount: number, onMount = false): void {
  const [first, setFirst] = useState(!onMount);
  useEffect(() => {
    if (first) {
      setFirst(false);
      return;
    }
    if (!key || !el.current?.animate) return;
    const a = amount;
    el.current.animate(
      [{ transform: 'translateX(0)' }, { transform: `translateX(-${a}px)` }, { transform: `translateX(${a}px)` }, { transform: `translateX(-${a / 2}px)` }, { transform: `translateX(${a / 2}px)` }, { transform: 'translateX(0)' }],
      { duration: 420, easing: 'ease-out' },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
}
