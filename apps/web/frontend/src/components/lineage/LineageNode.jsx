export default function LineageNode({ node, onClick, isSelected }) {
  const promoted = node.promoted;
  const isChampion = node.isChampion ?? node.is_champion;
  const isSynthetic = !!node.synthetic;
  // Synthetic Gen-0 base nodes get a neutral grey so they read as "origin"
  // instead of competing with the real promoted/discarded color language.
  const color = isSynthetic
    ? '#64748b'
    : isChampion
      ? '#d4a574'
      : promoted
        ? '#76b900'
        : '#ef4444';
  const scoreMap = node.scores || node.childScores || {};
  const scoreVals = Object.values(scoreMap).filter((v) => typeof v === 'number');
  const avgScore = scoreVals.length ? scoreVals.reduce((a, b) => a + b, 0) / scoreVals.length : (node.avg_score ?? 0);

  // Compact short label for the base model (e.g. "Llama-3.2-3B-Instruct").
  const baseShort = (() => {
    const lbl = String(node.label || '');
    const tail = lbl.split('/').pop() || lbl;
    return tail.length > 22 ? tail.slice(0, 22) + '…' : tail;
  })();

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
        fill={
          isSynthetic
            ? 'rgba(100,116,139,0.10)'
            : isChampion
              ? 'rgba(212,165,116,0.15)'
              : promoted
                ? 'rgba(118,185,0,0.12)'
                : 'rgba(239,68,68,0.08)'
        }
        stroke={color}
        strokeWidth={promoted || isChampion ? 2 : 1}
        strokeDasharray={isSynthetic ? '3 3' : null}
        opacity={isSynthetic ? 0.75 : promoted ? 1 : 0.5}
      />

      {/* Crown for champion */}
      {isChampion && (
        <text x={0} y={-20} textAnchor="middle" fontSize={13} fill="#d4a574" style={{ animation: 'crown-float 3s ease-in-out infinite' }}>
          ★
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
        {isSynthetic ? 'BASE' : `G${node.generation}`}
      </text>

      {/* Sub-label below: short model name for synthetic, score % for real gens */}
      <text
        x={0} y={30}
        textAnchor="middle"
        fontSize={9}
        fontFamily="JetBrains Mono"
        fill="#64748b"
      >
        {isSynthetic
          ? baseShort
          : avgScore <= 1
            ? `${(avgScore * 100).toFixed(0)}%`
            : `${Number(avgScore).toFixed(0)}%`}
      </text>
    </g>
  );
}
