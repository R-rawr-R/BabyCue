/**
 * What the server's `GET /status` says, and how the parent screens describe it.
 *
 * The app never invents a result. `alert` and `detection` come only from the server's safe-sleep models
 * (sleep position and toys in the crib); a server running without them sends neither, and the app then
 * only says whether the camera is streaming.
 */

export type AlertLevel = 'warn' | 'crit';

export interface RelayAlert {
  level: AlertLevel;
  title: string;
  detail: string;
}

export type PostureLabel = 'supine' | 'side' | 'prone' | 'unknown';

export interface Posture {
  label: PostureLabel;
  /** Which model saw it: `MediaPipe`, or `FiDIP` when MediaPipe lost the torso. */
  source: string;
  sinceS: number;
  /** Held long enough to count as the baby's position, not a passing frame. */
  stable: boolean;
}

export interface Hazard {
  label: string;
  score: number;
  /** `null` when the baby's position is unknown, so closeness cannot be judged. */
  nearBaby: boolean | null;
}

/** The latest fresh safe-sleep analysis. `null` when the server has none (models off, no camera, or stale). */
export interface Detection {
  posture: Posture | null;
  hazards: Hazard[];
}

export interface RelayStatus {
  inputConnected: boolean;
  fps: number;
  frames: number;
  viewers: number;
  alert: RelayAlert | null;
  detection: Detection | null;
}

/** `null` means the server could not be reached. */
export type Sample = RelayStatus | null;

export type Tone = 'ok' | 'warn' | 'unk';

export interface LiveView {
  tone: Tone;
  title: string;
  sub: string;
  connection: 'Connected' | 'Reconnecting';
  lost: boolean;
  videoLabel: string;
}

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null;

function parseAlert(raw: unknown): RelayAlert | null {
  if (!isRecord(raw)) return null;
  const { level, title, detail } = raw;
  if ((level !== 'warn' && level !== 'crit') || typeof title !== 'string' || title === '') return null;
  return { level, title, detail: typeof detail === 'string' ? detail : '' };
}

const POSTURES: readonly string[] = ['supine', 'side', 'prone', 'unknown'];
const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

function parsePosture(raw: unknown): Posture | null {
  if (!isRecord(raw) || typeof raw.label !== 'string' || !POSTURES.includes(raw.label)) return null;
  return {
    label: raw.label as PostureLabel,
    source: typeof raw.source === 'string' ? raw.source : '',
    sinceS: isNum(raw.since_s) ? Math.max(0, raw.since_s) : 0,
    stable: raw.stable === true,
  };
}

function parseHazard(raw: unknown): Hazard | null {
  if (!isRecord(raw) || typeof raw.label !== 'string' || raw.label === '' || !isNum(raw.score)) return null;
  const near = raw.near_baby;
  return { label: raw.label, score: raw.score, nearBaby: typeof near === 'boolean' ? near : null };
}

export function parseDetection(raw: unknown): Detection | null {
  if (!isRecord(raw)) return null;
  const hazards = Array.isArray(raw.hazards) ? raw.hazards.map(parseHazard).filter((h): h is Hazard => h !== null) : [];
  return { posture: parsePosture(raw.posture), hazards };
}

export function parseRelayStatus(raw: unknown): RelayStatus | null {
  if (!isRecord(raw) || typeof raw.input_connected !== 'boolean') return null;
  const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : 0);
  return {
    inputConnected: raw.input_connected,
    fps: num(raw.fps),
    frames: num(raw.frames),
    viewers: num(raw.viewers),
    alert: parseAlert(raw.alert),
    detection: parseDetection(raw.detection),
  };
}

export function liveView(name: string, sample: Sample): LiveView {
  if (sample === null) {
    return {
      tone: 'unk',
      title: `Can't see ${name}`,
      sub: 'Looking for the home PC',
      connection: 'Reconnecting',
      lost: true,
      videoLabel: 'Video paused while reconnecting',
    };
  }
  if (sample.alert && sample.alert.level === 'warn') {
    return {
      tone: 'warn',
      title: sample.alert.title,
      sub: sample.alert.detail,
      connection: 'Connected',
      lost: false,
      videoLabel: sample.alert.title,
    };
  }
  if (!sample.inputConnected) {
    return {
      tone: 'unk',
      title: `Can't see ${name}`,
      sub: 'Waiting for the baby phone',
      connection: 'Connected',
      lost: false,
      videoLabel: 'No video yet',
    };
  }
  const fps = Math.round(sample.fps);
  return {
    tone: 'ok',
    title: `${name}'s camera is live`,
    sub: fps > 0 ? `Streaming · ${fps} frame${fps === 1 ? '' : 's'} a second` : 'Streaming',
    connection: 'Connected',
    lost: false,
    videoLabel: `Live video of ${name}'s room`,
  };
}
