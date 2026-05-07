import { useId } from 'react';

/**
 * Pulsing gray bars used as a loading state on every page that fetches
 * over the network. Pass `rows` for line count and `height` per bar.
 *
 * Default styling matches the dark-theme card surface so the skeleton
 * sits in place of real content without re-flowing on data arrival.
 */
export default function LoadingSkeleton({
  rows = 3,
  height = 16,
  width = '100%',
  gap = 8,
  style,
}) {
  const id = useId().replace(/:/g, '');
  const keyframes = `mf-skel-${id}`;
  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap,
        width,
        ...style,
      }}
    >
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          style={{
            height,
            background:
              'linear-gradient(90deg, var(--bg-card-2, #111827) 0%, var(--bg-card-3, #1f2937) 50%, var(--bg-card-2, #111827) 100%)',
            backgroundSize: '200% 100%',
            animation: `${keyframes} 1.4s ease-in-out infinite`,
            borderRadius: 4,
          }}
        />
      ))}
      <style>{`
        @keyframes ${keyframes} {
          0%   { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
      `}</style>
    </div>
  );
}
