import type { PostureLabel, Sample } from './net/relayStatus';
import { postureChange } from './safeSleep';

export type EventKind = 'ok' | 'warn' | 'crit';

export interface HistoryEvent {
  id: string;
  title: string;
  at: Date;
  kind: EventKind;
}

const MAX_EVENTS = 50;

/** Newest first, capped. */
export function addEvents(events: HistoryEvent[], added: HistoryEvent[]): HistoryEvent[] {
  return [...added.slice().reverse(), ...events].slice(0, MAX_EVENTS);
}

/**
 * The events a change between two polls amounts to. `prev` is `undefined` for the first poll.
 * Only things the app really observed are recorded: the link to the PC, the camera, any alert the server sends,
 * and changes of the baby's confirmed sleep position.
 */
export function diffSamples(prev: Sample | undefined, next: Sample, now: Date): HistoryEvent[] {
  const out: HistoryEvent[] = [];
  const push = (title: string, kind: EventKind) => out.push({ id: `${now.getTime()}-${out.length}`, title, kind, at: now });

  if (next === null) {
    if (prev !== null) push(prev === undefined ? "Can't reach the home PC" : 'Connection lost', 'warn');
    return out;
  }
  if (prev === null) push('Connection is back', 'ok');
  const wasLive = prev ? prev.inputConnected : false;
  if (next.inputConnected && !wasLive) push('Baby phone camera connected', 'ok');
  if (!next.inputConnected && prev && prev.inputConnected) push('Baby phone camera disconnected', 'warn');
  const newAlert = next.alert && next.alert.title !== (prev ? prev.alert?.title : undefined);
  if (next.alert && newAlert) push(next.alert.title, next.alert.level);
  const before = settledPosture(prev);
  const after = settledPosture(next);
  // A roll-over that raised an alert is already recorded by that alert.
  const change = after && !newAlert ? postureChange(before, after) : null;
  if (change) push(change, after === 'supine' ? 'ok' : after === 'prone' ? 'crit' : 'warn');
  return out;
}

function settledPosture(sample: Sample | undefined): PostureLabel | null {
  const posture = sample?.detection?.posture;
  return posture && posture.stable ? posture.label : null;
}

export function formatTime(at: Date): string {
  return at.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}
