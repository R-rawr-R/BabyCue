/** The server's database: the baby's name and the log of every detection. */
import { BABY_PATH, DETECTIONS_PATH } from './wireProtocol';

export interface Baby {
  name: string;
  createdAt: string;
}

export type LogLevel = 'ok' | 'warn' | 'crit';

export interface LoggedDetection {
  id: number;
  /** Local date and time on the PC, ISO 8601 with its UTC offset. */
  at: string;
  kind: 'posture' | 'hazard' | 'hazard-cleared' | 'alert';
  label: string;
  detail: string;
  level: LogLevel | null;
  source: string | null;
  score: number | null;
}

const TIMEOUT_MS = 5000;

async function request(path: string, init?: RequestInit): Promise<unknown> {
  const abort = new AbortController();
  const cutoff = setTimeout(() => abort.abort(new Error('timed out')), TIMEOUT_MS);
  try {
    const response = await fetch(path, { ...init, cache: 'no-store', signal: abort.signal });
    const body = (await response.json().catch(() => null)) as { error?: unknown } | null;
    if (!response.ok) throw new Error(typeof body?.error === 'string' ? body.error : `The server answered ${response.status}`);
    return body;
  } finally {
    clearTimeout(cutoff);
  }
}

function parseBaby(raw: unknown): Baby | null {
  const baby = (raw as { baby?: { name?: unknown; created_at?: unknown } } | null)?.baby;
  if (!baby || typeof baby.name !== 'string') return null;
  return { name: baby.name, createdAt: typeof baby.created_at === 'string' ? baby.created_at : '' };
}

/** The baby on record, or `null` when nobody has named them yet. Rejects if the server cannot be reached. */
export async function fetchBaby(): Promise<Baby | null> {
  return parseBaby(await request(BABY_PATH));
}

export async function saveBabyName(name: string): Promise<Baby> {
  const baby = parseBaby(
    await request(BABY_PATH, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) }),
  );
  if (!baby) throw new Error('The server did not save the name');
  return baby;
}

export async function fetchDetections(limit = 200): Promise<LoggedDetection[]> {
  const raw = (await request(`${DETECTIONS_PATH}?limit=${limit}`)) as { detections?: unknown } | null;
  return Array.isArray(raw?.detections) ? (raw.detections as LoggedDetection[]) : [];
}

/** "Sat 10 Oct, 5:41 AM": the day matters in a log that spans nights. */
export function formatLogTime(at: string): string {
  const date = new Date(at);
  if (Number.isNaN(date.getTime())) return at;
  return date.toLocaleString([], { weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });
}

const POSTURE_TEXT: Record<string, string> = {
  supine: 'Sleeping on their back',
  side: 'Rolled onto their side',
  prone: 'Rolled onto their tummy',
  unknown: "Couldn't see the baby's position",
};

/** One line a parent can read. */
export function describeDetection(entry: LoggedDetection): string {
  switch (entry.kind) {
    case 'posture':
      return POSTURE_TEXT[entry.label] ?? entry.label;
    case 'hazard':
      return entry.score === null ? entry.detail : `${entry.detail} (${Math.round(entry.score * 100)}%)`;
    case 'hazard-cleared':
      return entry.detail;
    case 'alert':
      return entry.label;
  }
}
