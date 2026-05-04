export default function LineageNode({ node, onClick, isSelected }) {
  const promoted = node.promoted;
  const isChampion = node.isChampion;
  const color = isChampion ? '#d4a574' : promoted ? '#76b900' : '#ef4444';
  const avgScore = Object.values(node.childScores).reduce((a, b) => a + b, 0) / 5;

  return (
    <g
      onClick={() => onClick(node)}
      className="animate-node-birth"
      style={{ animationDelay: `${node.generation * 30}ms`, cursor: 'pointer' }}
    >
      {/* Glow ring */}
      {isSelected && (
        <circle cx={0} cy={0} r={22} fill="none" stroke={color} strokeWidth={2} strokeDasharray="4 2" opacity={0.6}>
          <animateTransform attributeName="transform" type="rotate" from="0 0 0" to="360 0 0" dur="4s" repeatCount="indefinite" />
        </circle>
      )}

      {/* Node circle */}
      <circle
        cx={0} cy={0} r={16}
        fill={isChampion ? 'rgba(212,165,116,0.15)' : promoted ? 'rgba(118,185,0,0.12)' : 'rgba(239,68,68,0.08)'}
        stroke={color}
        strokeWidth={promoted ? 2 : 1}
        opacity={promoted ? 1 : 0.5}
      />

      {/* Crown for champion */}
      {isChampion && (
        <text x={0} y={-20} textAnchor="middle" fontSize={14} style={{ animation: 'crown-float 3s ease-in-out infinite' }}>
          👑
        </text>
      )}

      {/* Generation number */}
      <text
        x={0} y={4}
        textAnchor="middle"
        fontSize={10}
        fontFamily="JetBrains Mono"
        fontWeight={600}
        fill={color}
      >
        G{node.generation}
      </text>

      {/* Score below */}
      <text
        x={0} y={30}
        textAnchor="middle"
        fontSize={9}
        fontFamily="JetBrains Mono"
        fill="#64748b"
      >
        {(avgScore * 100).toFixed(0)}%
      </text>
    </g>
  );
}
