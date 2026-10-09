import { BellRing, Volume2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { describeFailure } from '../streaming/FramePusher';
import { testAlarm } from '../alarm';
import { enablePush, pushState, sendTestPush, type PushState } from '../net/push';
import { Button } from './Button';

const EXPLAIN: Record<Exclude<PushState, 'on' | 'off'>, string> = {
  'needs-install': 'On iPhone, alarms with the app closed need BabyCue on the Home Screen: tap Share, then Add to Home Screen, and open it from there.',
  unsupported:
    "This browser can't get alarms while BabyCue is closed. Install the home PC's certificate (see the setup screen), then reopen BabyCue in Chrome.",
  blocked: 'Notifications are blocked for BabyCue. Allow them in the browser settings (lock icon next to the address), then come back.',
};

/** Offers background alarms until they are on, then shrinks to a line with a Test button. */
export function BackgroundAlarms() {
  const [state, setState] = useState<PushState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [note, setNote] = useState('');

  useEffect(() => {
    let alive = true;
    void pushState().then(async (current) => {
      if (!alive) return;
      setState(current);
      // Already on: sign up again quietly, in case the PC's database was reset since.
      if (current === 'on') await enablePush().catch(() => undefined);
    });
    return () => {
      alive = false;
    };
  }, []);

  if (state === null) return null;

  const test = async () => {
    testAlarm();
    setError('');
    setNote('');
    if (state !== 'on') return;
    try {
      await sendTestPush();
      setNote('Test sent. Lock the phone or switch apps within a few seconds to see how it arrives.');
    } catch (failure) {
      setError(describeFailure(failure));
    }
  };
  const testButton = (
    <Button className="small quiet" haptic="tap" onClick={() => void test()}>
      <Volume2 size={18} strokeWidth={2.75} aria-hidden style={{ verticalAlign: '-3px', marginRight: 6 }} />
      Test alarm
    </Button>
  );

  if (state === 'on') {
    return (
      <div className="bg-alarms">
        <div className="top">
          <span className="ic">
            <BellRing size={22} strokeWidth={2.75} aria-hidden />
          </span>
          <div>
            <div className="t">Alarms are on</div>
            <div className="s">This phone sounds an alarm in the app, and notifies you when BabyCue is closed.</div>
          </div>
        </div>
        {testButton}
        {note ? <p className="s">{note}</p> : null}
        {error ? (
          <p className="problem" role="alert">
            {error}
          </p>
        ) : null}
      </div>
    );
  }

  const turnOn = async () => {
    setBusy(true);
    setError('');
    try {
      setState(await enablePush());
    } catch (failure) {
      setError(describeFailure(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="bg-alarms">
      <div className="top">
        <span className="ic">
          <BellRing size={22} strokeWidth={2.75} aria-hidden />
        </span>
        <div>
          <div className="t">Alarms when BabyCue is closed</div>
          <div className="s">{state === 'off' ? 'Get a loud alert on this phone even when the app is in the background.' : EXPLAIN[state]}</div>
        </div>
      </div>
      {state === 'off' ? (
        <Button className="small" haptic="confirm" disabled={busy} onClick={() => void turnOn()}>
          {busy ? 'Turning on…' : 'Turn on background alarms'}
        </Button>
      ) : null}
      {testButton}
      {error ? (
        <p className="problem" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
