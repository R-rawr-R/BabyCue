import { expect, test } from 'vitest';
import { addEvents, diffSamples } from '../history';
import type { RelayStatus } from '../net/relayStatus';

const live: RelayStatus = { inputConnected: true, fps: 5, frames: 1, viewers: 1, alert: null, detection: null };
const idle: RelayStatus = { ...live, inputConnected: false };
const now = new Date(2026, 0, 1, 3, 12);
const titles = (p: Parameters<typeof diffSamples>[0], n: Parameters<typeof diffSamples>[1]) =>
  diffSamples(p, n, now).map((e) => e.title);

test('first poll', () => {
  expect(titles(undefined, live)).toEqual(['Baby phone camera connected']);
  expect(titles(undefined, idle)).toEqual([]);
  expect(titles(undefined, null)).toEqual(["Can't reach the home PC"]);
});

test('losing and regaining the server', () => {
  expect(titles(live, null)).toEqual(['Connection lost']);
  expect(titles(null, null)).toEqual([]);
  expect(titles(null, live)).toEqual(['Connection is back', 'Baby phone camera connected']);
});

test('the camera going away', () => {
  expect(titles(live, idle)).toEqual(['Baby phone camera disconnected']);
});

test('a new alert is recorded once', () => {
  const alerting = { ...live, alert: { level: 'crit' as const, title: 'Look now', detail: '' } };
  expect(diffSamples(live, alerting, now)).toMatchObject([{ title: 'Look now', kind: 'crit' }]);
  expect(titles(alerting, alerting)).toEqual([]);
});

test('newest events come first and the list is capped', () => {
  const a = diffSamples(undefined, live, now);
  const b = diffSamples(live, idle, now);
  expect(addEvents(addEvents([], a), b).map((e) => e.title)).toEqual([
    'Baby phone camera disconnected',
    'Baby phone camera connected',
  ]);
  const many = Array.from({ length: 80 }, () => a[0]);
  expect(addEvents([], many)).toHaveLength(50);
});

test('confirmed position changes are recorded, passing frames are not', () => {
  const at = (label: 'supine' | 'side' | 'prone', stable = true): RelayStatus => ({
    ...live,
    detection: { posture: { label, source: 'MediaPipe', sinceS: 0, stable }, hazards: [] },
  });
  expect(titles(live, at('supine'))).toEqual(['Sleeping on their back']);
  expect(titles(at('supine'), at('side', false))).toEqual([]);
  expect(diffSamples(at('supine'), at('side'), now)).toMatchObject([{ title: 'Rolled onto side', kind: 'warn' }]);
  expect(diffSamples(at('prone'), at('supine'), now)).toMatchObject([{ title: 'Back on their back', kind: 'ok' }]);
  // A roll-over that raised an alert is recorded once, by the alert.
  const tummy = { ...at('prone'), alert: { level: 'crit' as const, title: 'Baby is on their tummy', detail: '' } };
  expect(titles(at('supine'), tummy)).toEqual(['Baby is on their tummy']);
});
