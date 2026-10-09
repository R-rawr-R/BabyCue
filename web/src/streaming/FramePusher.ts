export type LinkState =
  | { kind: 'connecting' }
  | { kind: 'connected' }
  /** The link is fine but the camera has stopped handing out pictures, so nothing is being sent. */
  | { kind: 'no-picture' }
  | { kind: 'retrying'; reason: string; delayMs: number };

export interface PusherDeps {
  /** Take one picture as a JPEG; null if the camera is not ready yet. */
  capture(): Promise<Blob | null>;
  /** POST it to the server; resolves to the HTTP status. Rejects if the server cannot be reached. */
  upload(jpeg: Blob): Promise<number>;
  sleep(ms: number): Promise<void>;
}

const INITIAL_BACKOFF_MS = 500;
const MAX_BACKOFF_MS = 5000;
const NOT_READY_MS = 150;
/** About 2 s without a picture: stop claiming to stream (the parent sees the camera as gone after 5 s). */
const NOT_READY_LIMIT = 13;

export function describeFailure(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  // Keep the browser's own words: they tell a refused certificate apart from a timeout or a dropped link.
  if (/failed to fetch|network|load failed|timed out|abort/i.test(message)) return `Cannot reach the home PC (${message})`;
  return message || 'Unknown error';
}

/**
 * Takes a picture, posts it, repeats. Pictures are never queued, so a slow upload just means the next one is
 * newer. After a failure it backs off (0.5 s doubling to 5 s) and tries again. `start` and `stop` are
 * idempotent; after `stop` no further state is reported.
 */
export class FramePusher {
  private run: { cancelled: boolean } | null = null;
  private sent = 0;
  private readonly deps: PusherDeps;
  private readonly onState: (state: LinkState) => void;

  constructor(deps: PusherDeps, onState: (state: LinkState) => void) {
    this.deps = deps;
    this.onState = onState;
  }

  get framesSent(): number {
    return this.sent;
  }

  start(): void {
    if (this.run) return;
    const run = { cancelled: false };
    this.run = run;
    void this.loop(run);
  }

  stop(): void {
    if (this.run) this.run.cancelled = true;
    this.run = null;
  }

  private async loop(run: { cancelled: boolean }): Promise<void> {
    const { deps } = this;
    let backoff = INITIAL_BACKOFF_MS;
    let connected = false;
    let missing = 0;
    const report = (state: LinkState) => {
      if (!run.cancelled) this.onState(state);
    };
    report({ kind: 'connecting' });
    while (!run.cancelled) {
      let reason: string;
      try {
        const jpeg = await deps.capture();
        if (run.cancelled) break;
        if (jpeg === null) {
          missing += 1;
          if (missing === NOT_READY_LIMIT) {
            connected = false;
            report({ kind: 'no-picture' });
          }
          await deps.sleep(NOT_READY_MS);
          continue;
        }
        missing = 0;
        const status = await deps.upload(jpeg);
        if (run.cancelled) break;
        if (status >= 200 && status < 300) {
          this.sent += 1;
          backoff = INITIAL_BACKOFF_MS;
          if (!connected) report({ kind: 'connected' });
          connected = true;
          continue;
        }
        reason = status === 409 ? 'Another phone is already sending video' : `The server answered ${status}`;
      } catch (error) {
        if (run.cancelled) break;
        reason = describeFailure(error);
      }
      connected = false;
      report({ kind: 'retrying', reason, delayMs: backoff });
      await deps.sleep(backoff);
      backoff = Math.min(backoff * 2, MAX_BACKOFF_MS);
      report({ kind: 'connecting' });
    }
  }
}

export function linkText(state: LinkState | null): string {
  if (state === null) return '';
  switch (state.kind) {
    case 'connecting':
      return 'Connecting to the home PC…';
    case 'connected':
      return 'Sending video to the home PC';
    case 'no-picture':
      return 'The camera stopped giving pictures. Keep this page open with the screen on.';
    case 'retrying':
      return `${state.reason}. Trying again in ${Math.ceil(state.delayMs / 1000)} s`;
  }
}
