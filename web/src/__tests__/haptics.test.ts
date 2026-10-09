import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { PATTERNS, haptic, type Haptic } from '../haptics';

const vibrate = vi.fn();

beforeEach(() => {
  vibrate.mockReset();
  vi.stubGlobal('navigator', { vibrate });
});
afterEach(() => vi.unstubAllGlobals());

test('a named haptic vibrates with its pattern', () => {
  haptic('tap');
  haptic('confirm');
  expect(vibrate).toHaveBeenNthCalledWith(1, 8);
  expect(vibrate).toHaveBeenNthCalledWith(2, [18, 45, 30]);
});

test('every kind feels different from the others', () => {
  const seen = new Set(Object.values(PATTERNS).map((p) => JSON.stringify(p)));
  expect(seen.size).toBe(Object.keys(PATTERNS).length);
});

test('patterns are plain on/off durations, and alerts are longer than touches', () => {
  const total = (k: Haptic) => {
    const p = PATTERNS[k];
    return typeof p === 'number' ? p : p.reduce((a, b) => a + b, 0);
  };
  for (const kind of Object.keys(PATTERNS) as Haptic[]) {
    const p = PATTERNS[kind];
    for (const part of typeof p === 'number' ? [p] : p) expect(part).toBeGreaterThan(0);
  }
  expect(total('critical')).toBeGreaterThan(total('warn'));
  expect(total('warn')).toBeGreaterThan(total('tap'));
  expect(total('error')).toBeGreaterThan(total('success'));
  expect(total('stop')).toBeGreaterThan(total('confirm'));
});

test('no vibration support or a blocked call does not throw', () => {
  vi.stubGlobal('navigator', {});
  expect(() => haptic('tap')).not.toThrow();
  vi.stubGlobal('navigator', {
    vibrate: () => {
      throw new Error('blocked');
    },
  });
  expect(() => haptic('error')).not.toThrow();
});
