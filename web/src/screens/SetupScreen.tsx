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
  const install = useInstallPrompt();
  const press = useRef<ReturnType<typeof setTimeout>>(undefined);

  const choose = (next: Role) => {
    haptic('select');
    setRole(next);
    setProblem(next === 'baby' && !cameraAvailable() ? 'insecure' : null);
  };

  const connect = async () => {
    if (role === 'baby') {
      if (!cameraAvailable()) {
        haptic('error');
        setProblem('insecure');
        return;
      }
      setBusy(true);
      try {
        // Ask for the camera now, so the permission prompt comes before the baby screen.
        (await openCamera()).getTracks().forEach((t) => t.stop());
      } catch (error) {
        haptic('error');
        setProblem(describeCameraError(error));
        setBusy(false);
        return;
      }
      setBusy(false);
    }
    haptic('success');
    // Only the parent phone names the baby; the baby phone leaves the saved name alone.
    onConnect({ role, name: role === 'parent' ? name : initial.name });
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
        {role === 'parent' ? (
          <div className="field">
            <label htmlFor="name">Baby's name (optional)</label>
            <input id="name" className="input" value={name} onChange={(e) => setName(e.target.value)} autoComplete="off" />
            <span className="hint">Only shown on this phone.</span>
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
      {problem ? (
        <p className="problem" role="alert">
          {cameraProblemText[problem]}
        </p>
      ) : null}
      <Button className="up" haptic="tap" style={{ animationDelay: '.4s' }} disabled={busy} onClick={() => void connect()}>
        {busy ? 'Opening the camera…' : 'Connect'}
      </Button>
      </div>
    </main>
  );
}
