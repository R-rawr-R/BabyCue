import { useEffect, useRef, useState } from 'react';
import { haptic } from '../haptics';

const HOLD_MS = 2000;

/** A stop button that needs a 2 second press so little hands cannot end the stream. */
export function HoldToStop({ onStop }: { onStop: () => void }) {
  const [holding, setHolding] = useState(false);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const clear = () => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
  };
  useEffect(() => clear, []);

  const down = () => {
    setHolding(true);
    haptic('tap');
    clear();
    // A tick at each quarter so you can feel it filling, then a heavy final buzz.
    for (const part of [0.25, 0.5, 0.75]) timers.current.push(setTimeout(() => haptic('tick'), HOLD_MS * part));
    timers.current.push(
      setTimeout(() => {
        haptic('stop');
        setHolding(false);
        onStop();
      }, HOLD_MS),
    );
  };
  const up = () => {
    clear();
    setHolding(false);
  };

  return (
    <button
      type="button"
      className={`hold ${holding ? 'holding' : ''}`}
      aria-label="Press and hold to stop"
      onPointerDown={down}
      onPointerUp={up}
      onPointerLeave={up}
      onPointerCancel={up}
      onContextMenu={(e) => e.preventDefault()}
    >
      <span className="fill" />
      <span>{holding ? 'Keep holding…' : 'Hold to stop'}</span>
    </button>
  );
}
