export default function DNALoader({ size = 40 }) {
  const strands = 8;
  return (
    <svg width={size} height={size * 2} viewBox={`0 0 ${size} ${size * 2}`}>
      {Array.from({ length: strands }, (_, i) => {
        const t = i / strands;
        const x1 = size * 0.2 + Math.sin(t * Math.PI * 2) * size * 0.3;
        const x2 = size * 0.8 - Math.sin(t * Math.PI * 2) * size * 0.3;
        const y = (size * 2 * i) / strands;
        return (
          <g key={i}>
            <line
              x1={x1} y1={y} x2={x2} y2={y}
              stroke="#1e293b" strokeWidth={1}
            />
            <circle cx={x1} cy={y} r={3} fill="#818cf8"
              style={{ animation: `bob ${1 + i * 0.1}s ease-in-out infinite`, animationDelay: `${i * 0.1}s` }}
            />
            <circle cx={x2} cy={y} r={3} fill="#76b900"
              style={{ animation: `bob ${1 + i * 0.1}s ease-in-out infinite`, animationDelay: `${i * 0.15}s` }}
            />
          </g>
        );
      })}
    </svg>
  );
}
