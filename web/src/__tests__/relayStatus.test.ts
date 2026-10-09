import { expect, test } from 'vitest';
import { liveView, parseDetection, parseRelayStatus, type RelayStatus } from '../net/relayStatus';

const live: RelayStatus = { inputConnected: true, fps: 7.6, frames: 10, viewers: 1, alert: null, detection: null };

test('the server /status shape is parsed', () => {
  expect(parseRelayStatus({ input_connected: true, frames: 5, bad_frames: 0, fps: 7.5, viewers: 2 })).toEqual({
    inputConnected: true,
    fps: 7.5,
    frames: 5,
    viewers: 2,
    alert: null,
    detection: null,
  });
});

test('garbage is rejected', () => {
  expect(parseRelayStatus(null)).toBeNull();
  expect(parseRelayStatus({ fps: 1 })).toBeNull();
});

test('an alert is only taken when it is well formed', () => {
  const ok = parseRelayStatus({ input_connected: true, alert: { level: 'crit', title: 'T', detail: 'D' } });
  expect(ok?.alert).toEqual({ level: 'crit', title: 'T', detail: 'D' });
  expect(parseRelayStatus({ input_connected: true, alert: { level: 'boom', title: 'T' } })?.alert).toBeNull();
});

test('a live camera never claims more than it knows', () => {
  const v = liveView('Mila', live);
  expect(v).toMatchObject({ tone: 'ok', title: "Mila's camera is live", lost: false, connection: 'Connected' });
  expect(v.sub).toBe('Streaming · 8 frames a second');
});

test('no camera is shown as not seeing the baby', () => {
  expect(liveView('Mila', { ...live, inputConnected: false })).toMatchObject({ tone: 'unk', title: "Can't see Mila" });
});

test('an unreachable server is a lost connection', () => {
  expect(liveView('Mila', null)).toMatchObject({ tone: 'unk', lost: true, connection: 'Reconnecting' });
});

test('a warning from the server is shown as the warning tone', () => {
  const v = liveView('Mila', { ...live, alert: { level: 'warn', title: 'Heads', detail: 'Look' } });
  expect(v).toMatchObject({ tone: 'warn', title: 'Heads', sub: 'Look' });
});

test('safe-sleep results are parsed strictly', () => {
  const parsed = parseRelayStatus({
    input_connected: true,
    detection: {
      posture: { label: 'prone', source: 'FiDIP', since_s: 12, stable: true },
      hazards: [{ label: 'soft-toy', score: 0.82, near_baby: true }, { label: '', score: 1 }, { label: 'x' }],
    },
  });
  expect(parsed?.detection).toEqual({
    posture: { label: 'prone', source: 'FiDIP', sinceS: 12, stable: true },
    hazards: [{ label: 'soft-toy', score: 0.82, nearBaby: true }],
  });
  expect(parseDetection({ posture: { label: 'upside-down' }, hazards: 'no' })).toEqual({ posture: null, hazards: [] });
  expect(parseDetection(null)).toBeNull();
});
