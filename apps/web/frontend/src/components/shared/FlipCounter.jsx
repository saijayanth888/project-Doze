import { useState, useEffect, useRef } from 'react';

function Digit({ value }) {
  const [displayed, setDisplayed] = useState(value);
  const [animating, setAnimating] = useState(false);
  const prevRef = useRef(value);

  useEffect(() => {
    if (prevRef.current !== value) {
      setAnimating(true);
      const t = setTimeout(() => {
        setDisplayed(value);
        setAnimating(false);
        prevRef.current = value;
      }, 150);
      return () => clearTimeout(t);
    }
  }, [value]);

  return (
    <span
      className="inline-block w-[0.6em] overflow-hidden relative font-mono"
      style={{ height: '1.2em', lineHeight: '1.2em' }}
    >
      <span
        style={{
          display: 'block',
          transform: animating ? 'translateY(-100%)' : 'translateY(0)',
          opacity: animating ? 0 : 1,
          transition: 'transform 150ms ease, opacity 150ms ease',
        }}
      >
        {displayed}
      </span>
    </span>
  );
}

export default function FlipCounter({ value, className = '' }) {
  const str = String(value).padStart(2, '0');
  return (
    <span className={`font-mono inline-flex ${className}`}>
      {str.split('').map((d, i) => <Digit key={i} value={d} />)}
    </span>
  );
}
