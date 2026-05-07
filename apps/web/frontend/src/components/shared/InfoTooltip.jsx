import { useState } from 'react';
import { Info } from 'lucide-react';

/**
 * Hover/click tooltip used next to benchmark names and config field labels.
 * Pass an `info` object from BENCHMARK_INFO or CONCEPT_INFO.
 */
export default function InfoTooltip({ info, size = 14 }) {
  const [show, setShow] = useState(false);
  if (!info) return null;

  return (
    <span
      style={{ position: 'relative', display: 'inline-block', marginLeft: 4, lineHeight: 0 }}
      onMouseLeave={() => setShow(false)}
    >
      <Info
        size={size}
        style={{ cursor: 'pointer', opacity: 0.55, verticalAlign: 'middle' }}
        onMouseEnter={() => setShow(true)}
        onClick={() => setShow((s) => !s)}
        aria-label={`info about ${info.name || info.fullName || ''}`}
      />
      {show && (
        <div
          role="tooltip"
          style={{
            position: 'absolute',
            bottom: '125%',
            left: '50%',
            transform: 'translateX(-50%)',
            background: 'var(--bg-card, #0f172a)',
            border: '1px solid var(--border, #1f2937)',
            borderRadius: 8,
            padding: '12px 14px',
            width: 300,
            zIndex: 1000,
            fontSize: 12,
            lineHeight: 1.5,
            color: 'var(--text-primary, #e2e8f0)',
            boxShadow: '0 10px 30px rgba(0,0,0,0.55)',
            textAlign: 'left',
            whiteSpace: 'normal',
          }}
        >
          <div style={{ fontWeight: 700, marginBottom: 4, color: 'var(--text-primary, #e2e8f0)' }}>
            {info.fullName || info.name}
          </div>
          {info.description && (
            <div style={{ color: 'var(--text-secondary, #94a3b8)' }}>{info.description}</div>
          )}
          {info.whatItMeasures && (
            <div style={{ marginTop: 6, color: 'var(--text-secondary, #cbd5e1)' }}>
              <strong>Measures:</strong> {info.whatItMeasures}
            </div>
          )}
          {info.goodScore && (
            <div style={{ marginTop: 4, color: 'var(--color-success, #4ade80)' }}>
              <strong>Good score:</strong> {info.goodScore}
            </div>
          )}
          {info.paperRef && (
            <div style={{ marginTop: 6, color: 'var(--text-muted, #64748b)', fontSize: 11 }}>
              {info.paperRef}
            </div>
          )}
          {info.range && (
            <div style={{ marginTop: 6, color: 'var(--text-secondary, #cbd5e1)' }}>
              <strong>Range:</strong> {info.range}
            </div>
          )}
          {info.default !== undefined && (
            <div style={{ marginTop: 4, color: 'var(--text-secondary, #cbd5e1)' }}>
              <strong>Default:</strong> {String(info.default)}
            </div>
          )}
          {info.analogy && (
            <div style={{ marginTop: 6, color: 'var(--text-muted, #64748b)', fontStyle: 'italic' }}>
              {info.analogy}
            </div>
          )}
          {info.strategies && (
            <ul style={{ margin: '6px 0 0', paddingLeft: 16, color: 'var(--text-secondary, #cbd5e1)' }}>
              {Object.entries(info.strategies).map(([k, v]) => (
                <li key={k}>
                  <strong>{k}:</strong> {v}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </span>
  );
}
