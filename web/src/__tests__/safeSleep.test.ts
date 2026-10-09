import { expect, test } from 'vitest';
import { formatDuration, hazardName, hazardsView, postureView } from '../safeSleep';

test('each confirmed position has its tone', () => {
  const at = (label: 'supine' | 'side' | 'prone') => postureView({ label, source: 'FiDIP', sinceS: 75, stable: true });
  expect(at('supine')).toEqual({ tone: 'ok', title: 'On their back', sub: 'For 1 min · FiDIP' });
  expect(at('side').tone).toBe('warn');
  expect(at('prone').tone).toBe('crit');
});

test('an unconfirmed or unseen position is never presented as fact', () => {
  expect(postureView({ label: 'prone', source: 'FiDIP', sinceS: 1, stable: false })).toMatchObject({
    tone: 'unk',
    title: 'Checking position',
  });
  expect(postureView({ label: 'unknown', source: '', sinceS: 0, stable: true }).title).toBe('Position unclear');
  expect(postureView(null).tone).toBe('unk');
});

test('the crib check counts toys', () => {
  expect(hazardsView({ posture: null, hazards: [] })).toMatchObject({ tone: 'ok', title: 'No toys seen' });
  const two = hazardsView({
    posture: null,
    hazards: [
      { label: 'soft-toy', score: 0.8, nearBaby: false },
      { label: 'hard-toy', score: 0.7, nearBaby: null },
    ],
  });
  expect(two).toEqual({ tone: 'warn', title: '2 toys in the crib', sub: 'Keep the crib bare' });
  expect(hazardName('soft-toy')).toBe('Soft toy');
});

test('durations read naturally', () => {
  expect([5, 61, 3725].map(formatDuration)).toEqual(['5 s', '1 min', '1 h 2 min']);
});
