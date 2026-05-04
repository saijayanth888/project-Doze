export default function TrainingWave({ color = '#76b900', width = 200, height = 32 }) {
  const points = Array.from({ length: 41 }, (_, i) => {
    const x = (i / 40) * width * 2;
    const y = height / 2 + Math.sin((i / 40) * Math.PI * 4) * (height / 3);
    return `${x},${y}`;
  }).join(' ');

  return (
    <svg width={width} height={height} style={{ overflow: 'hidden' }}>
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        className="animate-wave"
        style={{ opacity: 0.7 }}
      />
    </svg>
  );
}
