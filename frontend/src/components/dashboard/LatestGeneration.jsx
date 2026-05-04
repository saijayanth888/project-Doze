import { C, F } from '../../config/colors';
import { GENS } from '../../config/mockData';
import Badge from '../shared/Badge';

export default function LatestGeneration() {
  const gen = GENS[GENS.length - 1];
  if (!gen) return null;

  const parentScores = gen.parent_scores;
  const childScores = gen.child_scores;
  const parentAvg = Object.values(parentScores).reduce((a, b) => a + b, 0) / Object.values(parentScores).length;
  const childAvg  = Object.values(childScores).reduce((a, b) => a + b, 0) / Object.values(childScores).length;
  const delta = childAvg - parentAvg;

  return (
    <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 18, height: '100%', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
        <span style={{ fontFamily: F.ui, fontSize: 13, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: C.txtM }}>Latest Generation</span>
        <Badge type={gen.promoted ? 'promoted' : 'discarded'}>{gen.promoted ? 'Promoted' : 'Discarded'}</Badge>
      </div>

      {/* Parent vs child avg */}
      <div style={{ display: 'flex', gap: 20, marginBottom: 14, alignItems: 'flex-end' }}>
        <div>
          <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: C.txtM, marginBottom: 3 }}>Parent</div>
          <div style={{ fontFamily: F.mono, fontSize: '1.6rem', fontWeight: 500, color: C.txtS, lineHeight: 1 }}>{parentAvg.toFixed(3)}</div>
        </div>
        <div style={{ color: delta > 0 ? C.success : C.danger, fontSize: 20, paddingBottom: 2 }}>
          {delta > 0 ? '↑' : '↓'}
        </div>
        <div>
          <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: C.txtM, marginBottom: 3 }}>Child</div>
          <div style={{ fontFamily: F.mono, fontSize: '1.6rem', fontWeight: 500, color: gen.promoted ? C.acc : C.danger, lineHeight: 1 }}>{childAvg.toFixed(3)}</div>
        </div>
        <div style={{ marginLeft: 'auto', textAlign: 'right' }}>
          <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: C.txtM, marginBottom: 3 }}>Delta</div>
          <div style={{ fontFamily: F.mono, fontSize: '1.6rem', fontWeight: 600, color: delta > 0 ? C.success : C.danger, lineHeight: 1 }}>
            {delta > 0 ? '+' : ''}{delta.toFixed(3)}
          </div>
        </div>
      </div>

      {/* Benchmark breakdown */}
      <div style={{ marginBottom: 12 }}>
        {Object.keys(parentScores).map(bench => {
          const pd = parentScores[bench];
          const cd = childScores[bench];
          const d = cd - pd;
          return (
            <div key={bench} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
              <span style={{ fontFamily: F.mono, fontSize: 11, color: C.txtM, width: 110, flexShrink: 0 }}>{bench}</span>
              <span style={{ fontFamily: F.mono, fontSize: 11, color: C.txtS, width: 48 }}>{pd.toFixed(3)}</span>
              <span style={{ fontFamily: F.mono, fontSize: 11, color: d > 0 ? C.success : d < 0 ? C.danger : C.txtM, width: 56, fontWeight: 600 }}>
                {d > 0 ? '+' : ''}{d.toFixed(3)}
              </span>
            </div>
          );
        })}
      </div>

      <div style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM }}>
        {gen.training_data_size?.toLocaleString()} samples · {gen.decision_reason}
      </div>
    </div>
  );
}
