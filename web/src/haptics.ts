/**
 * Haptic feedback, named by what the touch means. Browsers can only vibrate in patterns (no strength control), so
 * the kinds differ by length and rhythm: [on, off, on, ...] in milliseconds. Works in Chrome on Android; iPhone
 * Safari has no vibration API, so there it silently does nothing.
 */
export const PATTERNS = {
  // -- touches --
  /** Any ordinary press: the lightest touch. */
  tap: 8,
  /** Moving between tabs: a little firmer than a tap, still one pulse. */
  tab: 12,
  /** Picking one of several options (role, preview chip): a quick double flick. */
  select: [6, 35, 6],
  /** A progress mark while holding to stop. */
  tick: 5,

  // -- what a button does --
  /** Acknowledge: "I'm checking now", "Got it": a firm double press. */
  confirm: [18, 45, 30],
  /** Put off for later (snooze): one soft, longer pulse. */
  soft: 28,
  /** Leave or disconnect: two light taps. */
  leave: [10, 30, 10],

  // -- outcomes --
  /** It worked (connected, camera allowed): short, then longer. */
  success: [12, 50, 26],
  /** It failed (camera blocked, nothing to connect to): three buzzes, the last one long. */
  error: [60, 40, 60, 40, 110],
  /** The hold-to-stop finished: heavy and clearly final. */
  stop: [30, 40, 90],

  // -- the page tells you something --
  /** A heads-up: a gentle double nudge. */
  warn: [30, 70, 30],
  /** Critical alert: long and insistent, hard to sleep through. */
  critical: [250, 120, 250, 120, 250],
  /** The connection to the PC dropped. */
  lost: [60],
} as const satisfies Record<string, number | readonly number[]>;

export type Haptic = keyof typeof PATTERNS;

/** Play a named haptic. Never throws: feedback is a nicety. */
export function haptic(kind: Haptic): void {
  try {
    const pattern = PATTERNS[kind];
    navigator.vibrate?.(typeof pattern === 'number' ? pattern : [...pattern]);
  } catch {
    // Not supported, or blocked until the page has been touched.
  }
}
