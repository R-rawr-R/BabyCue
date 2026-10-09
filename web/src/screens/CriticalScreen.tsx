import { OctagonAlert } from 'lucide-react';
import { useRef } from 'react';
import { Button } from '../components/Button';
import { useShake } from '../device';

/** Full-screen red alert. Words, icon and colour all say "go and look". */
export function CriticalScreen({
  title,
  detail,
  onChecking,
  onSnooze,
}: {
  title: string;
  detail: string;
  onChecking: () => void;
  onSnooze: () => void;
}) {
  const root = useRef<HTMLDivElement>(null);
  useShake(root, title, 10, true);
  return (
    <div className="app" style={{ background: 'var(--crit)' }}>
      <div ref={root} className="screen crit-screen" role="alertdialog" aria-label={`Critical alert: ${title}`}>
        <div className="iconwrap">
          <span className="ring" />
          <span className="disc">
            <OctagonAlert size={52} strokeWidth={2.75} aria-hidden />
          </span>
        </div>
        <div>
          <div className="kicker">Please check on the baby</div>
          <h1>{title}</h1>
          {detail ? <p>{detail}</p> : null}
        </div>
        <div className="actions">
          <Button className="light" haptic="confirm" onClick={onChecking}>
            I'm checking now
          </Button>
          <Button className="outline" haptic="soft" onClick={onSnooze}>
            Snooze 2 minutes
          </Button>
        </div>
      </div>
    </div>
  );
}
