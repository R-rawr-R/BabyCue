/**
 * How the safe-sleep results read on the parent phone. Only what the server's models reported is shown:
 * a position that has not held yet is "checking", and an unseen body is "unclear", never a guess.
 */
import type { Detection, Hazard, Posture, PostureLabel } from './net/relayStatus';

export type CardTone = 'ok' | 'warn' | 'crit' | 'unk';

export interface CardView {
  tone: CardTone;
  title: string;
  sub: string;
}

const POSTURE_NAME: Record<PostureLabel, string> = {
  supine: 'On their back',
  side: 'On their side',
  prone: 'On their tummy',
  unknown: 'Position unclear',
};

const POSTURE_TONE: Record<PostureLabel, CardTone> = { supine: 'ok', side: 'warn', prone: 'crit', unknown: 'unk' };

export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min`;
  return `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`;
}

export function postureView(posture: Posture | null): CardView {
  if (posture === null) return { tone: 'unk', title: 'Position unclear', sub: "Can't see the baby's body yet" };
  if (posture.label === 'unknown') {
    return { tone: 'unk', title: 'Position unclear', sub: "Can't see the baby's body well enough" };
  }
  const name = POSTURE_NAME[posture.label];
  if (!posture.stable) {
    return { tone: 'unk', title: 'Checking position', sub: `Looks ${name.toLowerCase()} so far` };
  }
  const via = posture.source ? ` · ${posture.source}` : '';
  return { tone: POSTURE_TONE[posture.label], title: name, sub: `For ${formatDuration(posture.sinceS)}${via}` };
}

export function hazardName(label: string): string {
  const words = label.replace(/[-_]+/g, ' ').trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function hazardWhere(hazard: Hazard): string {
  if (hazard.nearBaby === true) return 'Near baby';
  if (hazard.nearBaby === false) return 'In view';
  return 'Seen';
}

export function hazardsView(detection: Detection): CardView {
  const n = detection.hazards.length;
  if (n === 0) return { tone: 'ok', title: 'No toys seen', sub: 'The crib looks bare' };
  const near = detection.hazards.some((h) => h.nearBaby === true);
  return {
    tone: 'warn',
    title: n === 1 ? '1 toy in the crib' : `${n} toys in the crib`,
    sub: near ? 'Close to the baby' : 'Keep the crib bare',
  };
}

/** A short history line when the confirmed position changes, e.g. "Rolled onto tummy". */
export function postureChange(prev: PostureLabel | null, next: PostureLabel): string | null {
  if (prev === next || next === 'unknown') return null;
  if (next === 'prone') return 'Rolled onto tummy';
  if (next === 'side') return 'Rolled onto side';
  return prev === null ? 'Sleeping on their back' : 'Back on their back';
}
