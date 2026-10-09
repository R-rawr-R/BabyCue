import { Check, LogOut, OctagonAlert, TriangleAlert } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { startAlarm, stopAlarm, testAlarm, unlockAudio } from '../alarm';
import { BackgroundAlarms } from '../components/BackgroundAlarms';
import { Button } from '../components/Button';
import { HazardCard } from '../components/HazardCard';
import { PostureCard } from '../components/PostureCard';
import { StatusCard } from '../components/StatusCard';
import { VideoPanel } from '../components/VideoPanel';
import { useShake, useWakeLock } from '../device';
import { haptic } from '../haptics';
import { addEvents, diffSamples, formatTime, type EventKind, type HistoryEvent } from '../history';
import { useDetectionLog } from '../hooks/useDetectionLog';
import { useRelayStatus } from '../hooks/useRelayStatus';
import { describeDetection, formatLogTime } from '../net/database';
import { liveView, type Detection, type RelayStatus, type Sample } from '../net/relayStatus';
import { CriticalScreen } from './CriticalScreen';

const SNOOZE_MS = 2 * 60 * 1000;

type Tab = 'live' | 'history';

/** Canned samples for the design preview (long-press the title on the first screen). Never sent anywhere. */
const base: RelayStatus = { inputConnected: true, fps: 8, frames: 100, viewers: 1, alert: null, detection: null };
const onBack: Detection = { posture: { label: 'supine', source: 'MediaPipe', sinceS: 1260, stable: true }, hazards: [] };
const PREVIEW: { key: string; label: string; sample: Sample }[] = [
  { key: 'calm', label: 'All calm', sample: { ...base, detection: onBack } },
  {
    key: 'tummy',
    label: 'Rolled to tummy',
    sample: {
      ...base,
      alert: { level: 'crit', title: 'Baby is on their tummy', detail: 'Example: lying face-down for 12 s · FiDIP' },
      detection: { posture: { label: 'prone', source: 'FiDIP', sinceS: 12, stable: true }, hazards: [] },
    },
  },
  {
    key: 'toy',
    label: 'Toy in crib',
    sample: {
      ...base,
      alert: { level: 'warn', title: 'Toy in the crib', detail: 'Example: soft toy near baby (82%)' },
      detection: { ...onBack, hazards: [{ label: 'soft-toy', score: 0.82, nearBaby: true }] },
    },
  },
  { key: 'plain', label: 'No detection', sample: base },
  {
    key: 'warn',
    label: 'Heads up',
    sample: { ...base, alert: { level: 'warn', title: 'Something needs a look', detail: 'Example heads-up message' } },
  },
  {
    key: 'crit',
    label: 'Critical',
    sample: { ...base, alert: { level: 'crit', title: 'Example critical alert', detail: 'This is a preview, not a real alert.' } },
  },
  { key: 'lost', label: 'Connection lost', sample: null },
  { key: 'wait', label: 'No camera', sample: { ...base, inputConnected: false } },
];

const kindIcon: Record<EventKind, typeof Check> = { ok: Check, warn: TriangleAlert, crit: OctagonAlert };

/** Parent phone: live video, how baby is, alerts, and the night's history. */
export function LiveScreen({ name, preview, onLeave }: { name: string; preview: boolean; onLeave: () => void }) {
  useWakeLock(true);
  const [tab, setTab] = useState<Tab>('live');
  const [previewKey, setPreviewKey] = useState('calm');
  const [events, setEvents] = useState<HistoryEvent[]>([]);
  const [quiet, setQuiet] = useState<Record<string, number>>({});
  const [, tick] = useState(0);
  const root = useRef<HTMLDivElement>(null);

  const polled = useRelayStatus(!preview);
  const detectionLog = useDetectionLog(tab === 'history' && !preview);
  const shown: Sample | undefined = preview ? PREVIEW.find((p) => p.key === previewKey)?.sample : polled;
  const sample: Sample = shown === undefined ? null : shown;
  const view = useMemo(() => liveView(name, sample), [name, sample]);
  const connecting = shown === undefined;

  useShake(root, sample?.alert?.level === 'warn' ? sample.alert.title : '', 5);
  useShake(root, shown === null ? 'lost' : '', 3);

  // Record what changed, and buzz for it.
  const previous = useRef<Sample | undefined>(undefined);
  useEffect(() => {
    if (shown === undefined) return;
    const before = previous.current;
    previous.current = shown;
    if (!preview) {
      const added = diffSamples(before, shown, new Date());
      if (added.length > 0) setEvents((e) => addEvents(e, added));
    }
    // Losing the PC or the baby camera means the parent is no longer watching: say so out loud.
    const lostPc = shown === null && before !== null && before !== undefined;
    const lostCamera = !!before && !!shown && before.inputConnected && !shown.inputConnected;
    if (shown === null && before !== null) haptic('lost');
    else if (shown?.alert && shown.alert.title !== before?.alert?.title) {
      haptic(shown.alert.level === 'crit' ? 'critical' : 'warn');
    }
    if (!preview && (lostPc || lostCamera)) startAlarm('lost');
  }, [shown, preview]);

  const alert = sample?.alert ?? null;
  const hidden = alert ? (quiet[alert.title] ?? 0) > Date.now() : false;
  const mute = (until: number) => {
    if (!alert) return;
    setQuiet((q) => ({ ...q, [alert.title]: until }));
    if (until !== Infinity) setTimeout(() => tick((n) => n + 1), until - Date.now() + 50);
  };

  // The alarm sound: a critical alert rings until it is acknowledged, snoozed or over; a heads-up chimes once.
  const alarmLevel = alert && !hidden && !preview ? alert.level : null;
  useEffect(() => {
    if (alarmLevel) startAlarm(alarmLevel);
    else stopAlarm();
  }, [alarmLevel, alert?.title]);
  useEffect(() => stopAlarm, []);
  // An alarm the push message started (below) stops once the status shows the alert is over.
  useEffect(() => {
    if (!alarmLevel && shown !== undefined) stopAlarm({ keepTest: true });
  }, [alarmLevel, shown]);
  // A push alarm reached the phone while this page is still running (perhaps hidden): sound it now, without
  // waiting for the next status check, which a phone may hold back while the app is in the background.
  useEffect(() => {
    if (preview || !('serviceWorker' in navigator)) return;
    const onMessage = (event: MessageEvent) => {
      const data = event.data as { type?: unknown; level?: unknown; test?: unknown } | null;
      if (data?.type !== 'babycue-alarm') return;
      if (data.test) testAlarm();
      else startAlarm(data.level === 'crit' ? 'crit' : 'warn');
    };
    navigator.serviceWorker.addEventListener('message', onMessage);
    return () => navigator.serviceWorker.removeEventListener('message', onMessage);
  }, [preview]);
  // Browsers only allow sound after a touch; any tap on this screen keeps it allowed.
  useEffect(() => {
    document.addEventListener('pointerdown', unlockAudio);
    return () => document.removeEventListener('pointerdown', unlockAudio);
  }, []);

  if (alert && alert.level === 'crit' && !hidden) {
    return (
      <CriticalScreen
        title={alert.title}
        detail={alert.detail}
        onChecking={() => mute(Infinity)}
        onSnooze={() => mute(Date.now() + SNOOZE_MS)}
      />
    );
  }

  const dotClass = view.lost ? 'c-unk' : 'c-ok';

  return (
    <div className="app">
      <div ref={root} className="screen">
        {tab === 'live' ? (
          <div className="scroll">
            <div className="live up">
              <div className="live-head">
                <h2>{name}'s room</h2>
                <span className={`conn ${dotClass}`} role="status" aria-live="polite">
                  <span className="dot" />
                  {connecting ? 'Connecting' : view.connection}
                </span>
                <Button className="leave" haptic="leave" aria-label="Disconnect" title="Disconnect" onClick={onLeave}>
                  <LogOut size={20} strokeWidth={2.75} aria-hidden />
                </Button>
              </div>
              <VideoPanel
                label={view.videoLabel}
                lost={view.lost || connecting}
                streaming={preview ? false : sample?.inputConnected === true}
              />
              <StatusCard tone={view.tone} title={view.title} sub={view.sub} />
              {preview ? null : <BackgroundAlarms />}
              {sample?.inputConnected && sample.detection ? (
                <div className="safe-sleep">
                  <PostureCard posture={sample.detection.posture} />
                  <HazardCard detection={sample.detection} />
                </div>
              ) : null}
              {preview ? (
                <div className="preview-box">
                  <p className="preview-note">Design preview. These are examples, not real readings.</p>
                  <div className="chips">
                    {PREVIEW.map((p) => (
                      <button
                        key={p.key}
                        type="button"
                        className="chip"
                        aria-pressed={p.key === previewKey}
                        onClick={() => {
                          haptic('select');
                          setPreviewKey(p.key);
                        }}
                      >
                        {p.label}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        ) : (
          <div className="scroll">
            <div className="history">
              <h2>Tonight</h2>
              {events.length === 0 ? <p className="empty">Nothing yet. Changes show up here as they happen.</p> : null}
              {events.map((e, i) => {
                const Icon = kindIcon[e.kind];
                return (
                  <div key={e.id} className={`row ${e.kind}`} style={{ animationDelay: `${Math.min(i, 6) * 0.08}s` }}>
                    <span className="ic">
                      <Icon size={22} strokeWidth={2.75} aria-hidden />
                    </span>
                    <div>
                      <div className="t">{e.title}</div>
                      <div className="time">{formatTime(e.at)}</div>
                    </div>
                  </div>
                );
              })}
              <h2 style={{ marginTop: 24 }}>Detection log</h2>
              <p className="empty">Every detection, saved on the home PC.</p>
              {detectionLog.failed ? <p className="empty">Can't load the log from the home PC right now.</p> : null}
              {detectionLog.entries?.length === 0 ? <p className="empty">No detections yet.</p> : null}
              {(detectionLog.entries ?? []).map((entry) => {
                const kind = entry.level === 'crit' ? 'crit' : entry.level === 'warn' ? 'warn' : 'ok';
                const Icon = kindIcon[kind];
                return (
                  <div key={`log-${entry.id}`} className={`row ${kind}`}>
                    <span className="ic">
                      <Icon size={22} strokeWidth={2.75} aria-hidden />
                    </span>
                    <div>
                      <div className="t">{describeDetection(entry)}</div>
                      <div className="time">
                        <time dateTime={entry.at}>{formatLogTime(entry.at)}</time>
                        {entry.kind === 'alert' && entry.detail ? ` · ${entry.detail}` : ''}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {alert && alert.level === 'warn' && !hidden && tab === 'live' ? (
          <div className="banner" role="alert">
            <div className="top">
              <span className="ic">
                <TriangleAlert size={22} strokeWidth={2.75} aria-hidden />
              </span>
              <div>
                <div className="kicker">Heads up</div>
                <div className="what">{alert.title}</div>
              </div>
            </div>
            <div className="actions">
              <Button className="gotit" haptic="confirm" onClick={() => mute(Infinity)}>
                Got it
              </Button>
              <Button className="quiet" haptic="soft" onClick={() => mute(Date.now() + SNOOZE_MS)}>
                Snooze
              </Button>
            </div>
          </div>
        ) : null}

        <nav className="nav" aria-label="Main" role="tablist">
          {(['live', 'history'] as const).map((k) => (
            <Button key={k} className="tab" haptic="tab" role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>
              {k === 'live' ? 'Live' : 'History'}
            </Button>
          ))}
        </nav>
      </div>
    </div>
  );
}
