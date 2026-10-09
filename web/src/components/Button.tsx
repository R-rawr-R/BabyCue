import type { ButtonHTMLAttributes, PointerEvent } from 'react';
import { haptic, type Haptic } from '../haptics';

/**
 * Pill button that ripples from the touch point, springs down when pressed, and gives the haptic that fits what it
 * does (`haptic`, a light tap by default; `null` for none, when the screen plays its own after the outcome).
 */
export function Button({
  className = '',
  haptic: kind = 'tap',
  onPointerDown,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { haptic?: Haptic | null }) {
  const down = (e: PointerEvent<HTMLButtonElement>) => {
    if (kind) haptic(kind);
    const button = e.currentTarget;
    const box = button.getBoundingClientRect();
    const dot = document.createElement('span');
    dot.className = 'ripple';
    dot.style.left = `${((e.clientX - box.left) / box.width) * 100}%`;
    dot.style.top = `${((e.clientY - box.top) / box.height) * 100}%`;
    button.appendChild(dot);
    dot.addEventListener('animationend', () => dot.remove());
    onPointerDown?.(e);
  };
  return <button type="button" className={`btn ${className}`} onPointerDown={down} {...rest} />;
}
