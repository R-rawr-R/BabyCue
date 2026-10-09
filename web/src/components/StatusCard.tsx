import { Check, CircleQuestionMark, TriangleAlert } from 'lucide-react';
import { useEffect, useRef } from 'react';
import type { Tone } from '../net/relayStatus';

const icons = { ok: Check, warn: TriangleAlert, unk: CircleQuestionMark } as const;

/** The big "how is baby" card. Colour, icon and words always say the same thing; it pops when it changes. */
export function StatusCard({ tone, title, sub }: { tone: Tone; title: string; sub: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    ref.current?.animate?.([{ transform: 'scale(.94)' }, { transform: 'scale(1.03)' }, { transform: 'scale(1)' }], {
      duration: 450,
      easing: 'ease-out',
    });
  }, [tone, title]);
  const Icon = icons[tone];
  return (
    <div ref={ref} className={`status ${tone}`} role="status" aria-live="polite">
      <span className="badge">
        <Icon size={32} strokeWidth={2.75} aria-hidden />
      </span>
      <div style={{ minWidth: 0 }}>
        <div className="title">{title}</div>
        <div className="sub">{sub}</div>
      </div>
    </div>
  );
}
