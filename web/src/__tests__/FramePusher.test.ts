import { expect, test } from 'vitest';
import { FramePusher, describeFailure, type LinkState, type PusherDeps } from '../streaming/FramePusher';

function harness(statuses: (number | Error)[]) {
  const states: LinkState[] = [];
  const sleeps: number[] = [];
  const holder: { pusher?: FramePusher } = {};
  const deps: PusherDeps = {
    capture: async () => new Blob(['x']),
    upload: async () => {
      const next = statuses.shift();
      if (next === undefined) {
        holder.pusher?.stop();
        return 204;
      }
      if (next instanceof Error) throw next;
      return next;
    },
    sleep: async (ms) => void sleeps.push(ms),
  };
  const pusher = new FramePusher(deps, (s) => states.push(s));
  holder.pusher = pusher;
  const done = () => new Promise((r) => setTimeout(r, 20));
  return { pusher, states, sleeps, done };
}

test('every picture is posted and reported once as connected', async () => {
  const h = harness([204, 204, 204]);
  h.pusher.start();
  await h.done();
  expect(h.states.map((s) => s.kind)).toEqual(['connecting', 'connected']);
  expect(h.pusher.framesSent).toBe(3);
});

test('failures back off 0.5 s, 1 s, 2 s... and success resets the delay', async () => {
  const h = harness([new TypeError('Failed to fetch'), 500, 409, 204, new Error('x')]);
  h.pusher.start();
  await h.done();
  expect(h.sleeps).toEqual([500, 1000, 2000, 500]);
  const retries = h.states.filter((s) => s.kind === 'retrying');
  expect(retries.map((s) => (s as { reason: string }).reason)).toEqual([
    'Cannot reach the home PC (Failed to fetch)',
    'The server answered 500',
    'Another phone is already sending video',
    'x',
  ]);
});

test('the delay is capped at 5 s', async () => {
  const h = harness(Array.from({ length: 8 }, () => 500));
  h.pusher.start();
  await h.done();
  expect(Math.max(...h.sleeps)).toBe(5000);
});

test('nothing is reported after stop', async () => {
  const h = harness([204]);
  h.pusher.start();
  h.pusher.stop();
  await h.done();
  expect(h.states.filter((s) => s.kind === 'connected')).toEqual([]);
});

test('a camera that stops giving pictures is not reported as streaming', async () => {
  const states: LinkState[] = [];
  let captures = 0;
  const holder: { pusher?: FramePusher } = {};
  const pusher = new FramePusher(
    {
      capture: async () => {
        captures += 1;
        if (captures > 40) holder.pusher?.stop();
        return captures === 1 ? new Blob(['x']) : null;
      },
      upload: async () => 204,
      sleep: async () => undefined,
    },
    (s) => states.push(s),
  );
  holder.pusher = pusher;
  pusher.start();
  await new Promise((r) => setTimeout(r, 20));
  expect(states.map((s) => s.kind)).toEqual(['connecting', 'connected', 'no-picture']);
});

test('failure messages are friendly', () => {
  expect(describeFailure(new TypeError('Failed to fetch'))).toBe('Cannot reach the home PC (Failed to fetch)');
});
