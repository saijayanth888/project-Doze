import { useState } from 'react';
import { C, F } from '../../config/colors';
import { ChevronUp, ChevronDown } from 'lucide-react';
import { BENCHMARK_INFO } from '../../data/benchmarkInfo';
import InfoTooltip from '../shared/InfoTooltip';

const KEYS = ['mmlu', 'arc_challenge', 'hellaswag', 'gsm8k', 'humaneval'];
const BENCHMARK_LABELS = {
  mmlu: 'MMLU',
  arc_challenge: 'ARC-C',
  hellaswag: 'HellaSwag',
  gsm8k: 'GSM8K',
  humaneval: 'HumanEval',
};

function getHeatColor(v) {
  if (v < 0.40) return '#1c2420';
  if (v < 0.50) return '#1f2e1f';
  if (v < 0.55) return '#24381e';
  if (v < 0.60) return '#2a431e';
  if (v < 0.65) return '#314e1e';
  if (v < 0.70) return '#3a5c1d';
  if (v < 0.75) return '#456b1c';
  if (v < 0.80) return '#527c1b';
  return '#608e1a';
}

function getTextColor(v) {
  return v >= 0.65 ? '#a3e635' : v >= 0.55 ? '#86a12e' : '#4a5c35';
}

/**
 * @param {{ generation: number, childScores: Record<string, number>, promoted: boolean }[]} rows
 *   Rows from /api/eval/generations (scores mapped to childScores by parent).
 */
export default function HeatmapTable({ rows = [] }) {
  const [sortKey, setSortKey] = useState('generation');
  const [sortDir, setSortDir] = useState('desc');
  const [hover, setHover] = useState(null);

  function toggleSort(key) {
    if (sortKey === key) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else {
      setSortKey(key);
      setSortDir('desc');
    }
  }

  if (!rows || rows.length === 0) {
    return (
      <div
        style={{
          textAlign: 'center',
          padding: '40px 0',
          fontFamily: F.ui,
          fontSize: 13,
        }}
      >
        <p style={{ margin: 0, color: C.txtM }}>
          Benchmark comparison will appear after evolution runs complete.
        </p>
      </div>
    );
  }

  const sorted = [...rows].sort((a, b) => {
    const av =
      sortKey === 'generation' ? a.generation : a.childScores?.[sortKey] ?? 0;
    const bv =
      sortKey === 'generation' ? b.generation : b.childScores?.[sortKey] ?? 0;
    return sortDir === 'asc' ? av - bv : bv - av;
  });

  return (
    <div style={{ overflowX: 'auto' }}>
      {hover && (
        <div
          style={{
            position: 'fixed',
            top: hover.y - 36,
            left: hover.x,
            background: '#1a2235',
            border: '1px solid #1e293b',
            borderRadius: 6,
            padding: '4px 10px',
            fontSize: 11,
            fontFamily: 'JetBrains Mono',
            color: '#f1f5f9',
            pointerEvents: 'none',
            zIndex: 100,
            transform: 'translateX(-50%)',
          }}
        >
          {hover.label}: {(hover.value * 100).toFixed(2)}%
        </div>
      )}
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid #1e293b' }}>
            <th
              onClick={() => toggleSort('generation')}
              style={{
                padding: '10px 12px',
                textAlign: 'left',
                fontFamily: 'JetBrains Mono',
                fontSize: 11,
                color: '#64748b',
                letterSpacing: 1,
                cursor: 'pointer',
                whiteSpace: 'nowrap',
              }}
            >
              <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                GEN
                {sortKey === 'generation' &&
                  (sortDir === 'asc' ? <ChevronUp size={10} /> : <ChevronDown size={10} />)}
              </span>
            </th>
            {KEYS.map((k) => (
              <th
                key={k}
                onClick={() => toggleSort(k)}
                style={{
                  padding: '10px 12px',
                  textAlign: 'center',
                  fontFamily: 'JetBrains Mono',
                  fontSize: 11,
                  color: sortKey === k ? '#76b900' : '#64748b',
                  letterSpacing: 1,
                  cursor: 'pointer',
                  whiteSpace: 'nowrap',
                }}
              >
                <span
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: 4,
                  }}
                >
                  {BENCHMARK_LABELS[k]}
                  <InfoTooltip info={BENCHMARK_INFO[k]} size={11} />
                  {sortKey === k &&
                    (sortDir === 'asc' ? <ChevronUp size={10} /> : <ChevronDown size={10} />)}
                </span>
              </th>
            ))}
            <th
              style={{
                padding: '10px 12px',
                textAlign: 'center',
                fontFamily: 'JetBrains Mono',
                fontSize: 11,
                color: '#64748b',
              }}
            >
              STATUS
            </th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((g, i) => (
            <tr
              key={g.generation}
              style={{
                borderBottom: '1px solid rgba(30,41,59,0.5)',
                background: i % 2 === 0 ? 'transparent' : 'rgba(12,16,24,0.4)',
                transition: 'background 150ms',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = 'rgba(30,41,59,0.3)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background =
                  i % 2 === 0 ? 'transparent' : 'rgba(12,16,24,0.4)';
              }}
            >
              <td
                style={{
                  padding: '8px 12px',
                  fontFamily: 'JetBrains Mono',
                  fontSize: 12,
                  color: '#94a3b8',
                }}
              >
                G{g.generation}
              </td>
              {KEYS.map((k) => {
                const val = g.childScores?.[k] ?? 0;
                return (
                  <td
                    key={k}
                    style={{ padding: '6px 6px', textAlign: 'center' }}
                    onMouseEnter={(e) =>
                      setHover({
                        x: e.clientX,
                        y: e.clientY,
                        label: BENCHMARK_LABELS[k],
                        value: val,
                      })
                    }
                    onMouseLeave={() => setHover(null)}
                  >
                    <div
                      style={{
                        background: getHeatColor(val),
                        borderRadius: 4,
                        padding: '4px 8px',
                        fontFamily: 'JetBrains Mono',
                        fontSize: 11,
                        color: getTextColor(val),
                        fontWeight: 500,
                        transition: 'transform 150ms',
                        cursor: 'default',
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.transform = 'scale(1.05)';
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.transform = 'scale(1)';
                      }}
                    >
                      {(val * 100).toFixed(1)}
                    </div>
                  </td>
                );
              })}
              <td style={{ padding: '8px 12px', textAlign: 'center' }}>
                <span
                  style={{
                    fontSize: 10,
                    fontFamily: 'JetBrains Mono',
                    color: g.promoted ? '#76b900' : '#ef4444',
                    background: g.promoted ? 'rgba(118,185,0,0.1)' : 'rgba(239,68,68,0.1)',
                    padding: '2px 8px',
                    borderRadius: 4,
                    letterSpacing: 0.5,
                  }}
                >
                  {g.promoted ? 'KEPT' : 'DROP'}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
