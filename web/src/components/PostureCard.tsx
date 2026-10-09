import { BedSingle, CircleQuestionMark, OctagonAlert, TriangleAlert } from 'lucide-react';
import type { Posture } from '../net/relayStatus';
import { postureView } from '../safeSleep';

const icons = { ok: BedSingle, warn: TriangleAlert, crit: OctagonAlert, unk: CircleQuestionMark } as const;

/** Sleep position from the server's pose models. Back is safest; side warns; tummy is critical. */
export function PostureCard({ posture }: { posture: Posture | null }) {
  const view = postureView(posture);
  const Icon = icons[view.tone];
  return (
    <section className={`card ${view.tone}`} aria-label="Sleep position" aria-live="polite">
      <span className="badge">
        <Icon size={24} strokeWidth={2.75} aria-hidden />
      </span>
      <div className="body">
        <div className="kicker">Sleep position</div>
        <div className="title">{view.title}</div>
        <div className="sub">{view.sub}</div>
      </div>
    </section>
  );
}
