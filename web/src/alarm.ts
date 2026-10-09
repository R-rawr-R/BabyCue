/**
 * Alarm sounds, made with Web Audio so there is no sound file to load.
 *
 * Browsers only let a page make sound after the user has touched it, so `unlockAudio` must run inside a tap.
 * A critical alarm repeats until `stopAlarm`; the other sounds play once. They play while the app is open (also in
 * the background, as long as the phone keeps it running); once the phone suspends the app, the background alarm (a
 * push notification with the phone's own sound) takes over.
 */

export type AlarmSound = 'crit' | 'warn' | 'lost';

let context: AudioContext | null = null;
let repeat: ReturnType<typeof setInterval> | undefined;
let ringing = false;
/** The ringing alarm is only the Test button's, so it may stop on its own. */
let testing = false;

const CRIT_REPEAT_MS = 1600;

function audio(): AudioContext | null {
  if (context) return context;
  // iPhone: the "playback" session plays through the silent switch, like an alarm clock. Without it the ring/silent
  // switch mutes Web Audio, and a parent with the phone on silent would hear nothing. (Safari 17+; ignored elsewhere.)
  const session = (navigator as { audioSession?: { type: string } }).audioSession;
  if (session) session.type = 'playback';
  const Ctor = window.AudioContext ?? (window as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) return null;
  context = new Ctor();
  return context;
}

function running(): AudioContext | null {
  const ctx = audio();
  if (ctx && ctx.state !== 'running') void ctx.resume().catch(() => undefined);
  return ctx;
}

/** Call from a tap: allows sound for the rest of the session. */
export function unlockAudio(): void {
  running();
}

function tone(ctx: AudioContext, start: number, freq: number, length: number, volume: number, type: OscillatorType = 'square'): void {
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, start);
  // Short ramps avoid clicks.
  gain.gain.setValueAtTime(0, start);
  gain.gain.linearRampToValueAtTime(volume, start + 0.02);
  gain.gain.setValueAtTime(volume, start + length - 0.03);
  gain.gain.linearRampToValueAtTime(0, start + length);
  osc.connect(gain).connect(ctx.destination);
  osc.start(start);
  osc.stop(start + length);
}

const SOUNDS: Record<AlarmSound, (ctx: AudioContext, t: number) => void> = {
  // Two-tone, high and urgent: hard to sleep through.
  crit: (ctx, t) => {
    for (let i = 0; i < 3; i++) {
      tone(ctx, t + i * 0.4, 988, 0.18, 0.35);
      tone(ctx, t + i * 0.4 + 0.2, 740, 0.18, 0.35);
    }
  },
  // Rising two-note chime: "have a look".
  warn: (ctx, t) => {
    tone(ctx, t, 660, 0.15, 0.25);
    tone(ctx, t + 0.22, 880, 0.25, 0.25);
    tone(ctx, t + 0.6, 660, 0.15, 0.25);
    tone(ctx, t + 0.82, 880, 0.25, 0.25);
  },
  // Falling three notes, softer: something dropped out (the PC or the baby camera).
  lost: (ctx, t) => {
    tone(ctx, t, 784, 0.2, 0.25, 'triangle');
    tone(ctx, t + 0.25, 622, 0.2, 0.25, 'triangle');
    tone(ctx, t + 0.5, 523, 0.35, 0.25, 'triangle');
  },
};

/** Plays `sound`. A critical alarm keeps ringing until `stopAlarm`; nothing else interrupts it. */
export function startAlarm(sound: AlarmSound): void {
  const ctx = running();
  if (!ctx) return;
  if (sound === 'crit') {
    testing = false; // a real alarm: it rings until stopped, even if a test started it
    if (ringing) return;
    ringing = true;
    SOUNDS.crit(ctx, ctx.currentTime + 0.02);
    repeat = setInterval(() => SOUNDS.crit(ctx, ctx.currentTime + 0.02), CRIT_REPEAT_MS);
    return;
  }
  if (!ringing) SOUNDS[sound](ctx, ctx.currentTime + 0.02);
}

/** Stops a critical alarm. `keepTest`: leave the Test button's alarm to finish its three seconds. */
export function stopAlarm({ keepTest = false } = {}): void {
  if (keepTest && testing) return;
  clearInterval(repeat);
  repeat = undefined;
  ringing = false;
  testing = false;
}

/** About three seconds of the critical alarm, for the Test button. */
export function testAlarm(): void {
  if (ringing) return; // a real alarm is already sounding: never cut it short
  startAlarm('crit');
  testing = true;
  setTimeout(() => {
    if (testing) stopAlarm();
  }, 3000);
}
