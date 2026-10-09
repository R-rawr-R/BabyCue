import { House } from 'lucide-react';
import { useRef, useState } from 'react';
import { Button } from '../components/Button';
import {
  cameraAvailable,
  cameraProblemText,
  describeCameraError,
  isIos,
  isStandalone,
  openCamera,
  useInstallPrompt,
  type CameraProblem,
} from '../device';
import { haptic } from '../haptics';
import { describeFailure } from '../streaming/FramePusher';
import { fetchBaby, saveBabyName } from '../net/database';
import { CA_PATH } from '../net/wireProtocol';
import type { Prefs, Role } from '../storage';

const ROLES: { value: Role; label: string }[] = [
  { value: 'parent', label: 'Watch' },
  { value: 'baby', label: 'Baby phone' },
];

const LONG_PRESS_MS = 700;

/** First screen: which phone is this? The home PC is the server that served this page. */
export function SetupScreen({
  initial,
  onConnect,
  onPreview,
}: {
  initial: Prefs;
  onConnect: (prefs: Prefs) => void;
  onPreview: () => void;
}) {
  const [role, setRole] = useState<Role>(initial.role);
  const [name, setName] = useState(initial.name);
  const [problem, setProblem] = useState<CameraProblem | null>(role === 'baby' && !cameraAvailable() ? 'insecure' : null);
  const [busy, setBusy] = useState(false);
  /** The server has no baby yet: ask for the name before going on. */
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState('');
  const install = useInstallPrompt();
  const press = useRef<ReturnType<typeof setTimeout>>(undefined);

  const choose = (next: Role) => {
    haptic('select');
    setRole(next);
    setProblem(next === 'baby' && !cameraAvailable() ? 'insecure' : null);
  };

  const connect = async () => {
    if (role === 'baby' && !asking) {
      if (!cameraAvailable()) {
        haptic('error');
        setProblem('insecure');
        return;
      }
      setBusy(true);
      try {
        // Ask for the camera now, so the permission prompt comes before the baby screen.
        (await openCamera()).getTracks().forEach((t) => t.stop());
      } catch (cameraError) {
        haptic('error');
        setProblem(describeCameraError(cameraError));
        setBusy(false);
        return;
      }
    }
    setBusy(true);
    setError('');
    try {
      // The PC keeps the baby's name, so every phone shows the same one.
      const baby = asking ? await saveBabyName(name) : await fetchBaby();
      if (baby === null) {
        haptic('select');
        setAsking(true);
        return;
      }
      haptic('success');
      onConnect({ role, name: baby.name });
    } catch (failure) {
      haptic('error');
      setError(describeFailure(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="setup">
      <div className="intro">
      <div className="logo" role="img" aria-label="BabyCue">
        <House size={34} strokeWidth={2.75} aria-hidden />
      </div>
      <h1
        className="up"
        style={{ animationDelay: '.1s' }}
        onPointerDown={() => {
          press.current = setTimeout(onPreview, LONG_PRESS_MS);
        }}
        onPointerUp={() => clearTimeout(press.current)}
        onPointerLeave={() => clearTimeout(press.current)}
        onPointerCancel={() => clearTimeout(press.current)}
        onContextMenu={(e) => e.preventDefault()}
      >
        Let's connect to your home PC
      </h1>
      <p className="lead up" style={{ animationDelay: '.2s' }}>
        Open BabyCue on the PC. This page is already connected to it.
      </p>
      </div>

      <div className="body">

      <div className="up" style={{ animationDelay: '.3s', display: 'grid', gap: 18, marginTop: 8 }}>
        <div className="field">
          <span className="label" id="role-label">
            This phone will
          </span>
          <div className="seg" role="radiogroup" aria-labelledby="role-label">
            {ROLES.map((r) => (
              <button
                key={r.value}
                type="button"
                role="radio"
                aria-checked={role === r.value}
                onClick={() => choose(r.value)}
              >
                {r.label}
              </button>
            ))}
          </div>
          <span className="hint">
            {role === 'parent' ? 'Watch the live video and get alerts.' : 'Point at the crib and send video to the PC.'}
          </span>
        </div>
        <div className="field">
          <span className="label">Home PC</span>
          <div className="pc">{location.host}</div>
        </div>
        {asking ? (
          <div className="field">
            <label htmlFor="name">What's your baby's name?</label>
            <input
              id="name"
              className="input"
              value={name}
              maxLength={40}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && name.trim()) void connect();
              }}
              autoComplete="off"
              autoFocus
            />
            <span className="hint">Saved on the home PC, so every phone uses it.</span>
          </div>
        ) : null}
      </div>

      {!isStandalone() ? (
        <details className="help">
          <summary>Install as an app</summary>
          {install ? (
            <Button className="small" haptic="confirm" style={{ marginTop: 10, width: '100%' }} onClick={install}>
              Install BabyCue
            </Button>
          ) : (
            <ol>
              {isIos() ? (
                <li>
                  In Safari tap <b>Share</b>, then <b>Add to Home Screen</b>.
                </li>
              ) : (
                <li>
                  In Chrome open the menu (⋮), then <b>Install app</b> or <b>Add to Home screen</b>.
                </li>
              )}
              <li>
                If Chrome only offers a shortcut, first <a href={CA_PATH}>download the certificate</a> and install it
                (Settings, Security, Install a certificate, CA certificate), then reopen this page.
              </li>
            </ol>
          )}
        </details>
      ) : null}

      </div>

      <div className="actions">
      {problem || error ? (
        <p className="problem" role="alert">
          {problem ? cameraProblemText[problem] : error}
        </p>
      ) : null}
      <Button
        className="up"
        haptic="tap"
        style={{ animationDelay: '.4s' }}
        disabled={busy || (asking && !name.trim())}
        onClick={() => void connect()}
      >
        {busy ? 'Connecting…' : asking ? 'Save and connect' : 'Connect'}
      </Button>
      </div>
    </main>
  );
}
