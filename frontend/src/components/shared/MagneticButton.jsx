import { useRef, useState } from 'react';

export default function MagneticButton({ children, onClick, className = '', style = {} }) {
  const ref = useRef(null);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [ripples, setRipples] = useState([]);

  function handleMouseMove(e) {
    const rect = ref.current.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    setOffset({
      x: (e.clientX - cx) * 0.2,
      y: (e.clientY - cy) * 0.2,
    });
  }

  function handleMouseLeave() {
    setOffset({ x: 0, y: 0 });
  }

  function handleClick(e) {
    const rect = ref.current.getBoundingClientRect();
    const id = Date.now();
    setRipples(r => [...r, { id, x: e.clientX - rect.left, y: e.clientY - rect.top }]);
    setTimeout(() => setRipples(r => r.filter(rp => rp.id !== id)), 600);
    onClick?.(e);
  }

  return (
    <button
      ref={ref}
      onClick={handleClick}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      className={`relative overflow-hidden ${className}`}
      style={{
        transform: `translate(${offset.x}px, ${offset.y}px)`,
        transition: 'transform 200ms cubic-bezier(0.16, 1, 0.3, 1)',
        ...style,
      }}
    >
      {ripples.map(rp => (
        <span
          key={rp.id}
          className="animate-ripple"
          style={{
            position: 'absolute',
            left: rp.x,
            top: rp.y,
            width: 8,
            height: 8,
            marginLeft: -4,
            marginTop: -4,
            borderRadius: '50%',
            background: 'rgba(255,255,255,0.3)',
            pointerEvents: 'none',
          }}
        />
      ))}
      {children}
    </button>
  );
}
