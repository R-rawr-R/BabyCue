import { ShieldCheck, ToyBrick } from 'lucide-react';
import type { Detection } from '../net/relayStatus';
import { hazardName, hazardsView, hazardWhere } from '../safeSleep';

/** Toys the crib-hazard model found. Safe sleep means a bare crib, so any toy is worth a look. */
export function HazardCard({ detection }: { detection: Detection }) {
  const view = hazardsView(detection);
  const Icon = view.tone === 'ok' ? ShieldCheck : ToyBrick;
  return (
    <section className={`card ${view.tone}`} aria-label="Crib check" aria-live="polite">
      <span className="badge">
        <Icon size={24} strokeWidth={2.75} aria-hidden />
      </span>
      <div className="body">
        <div className="kicker">Crib check</div>
        <div className="title">{view.title}</div>
        <div className="sub">{view.sub}</div>
        {detection.hazards.length > 0 ? (
          <ul className="hazards">
            {detection.hazards.map((h) => (
              <li key={h.label}>
                <span className="name">{hazardName(h.label)}</span>
                <span className={`tag${h.nearBaby ? ' near' : ''}`}>{hazardWhere(h)}</span>
                <span className="score">{Math.round(h.score * 100)}%</span>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </section>
  );
}
