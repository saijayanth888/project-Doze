import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  Brain,
  Calculator,
  Compass,
  Cpu,
  GitCompare,
  Globe2,
  Loader2,
  RefreshCw,
  Send,
  Sparkles,
  Target,
  Trash2,
  Wand2,
  Zap,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { C, F } from '../config/colors';
import { apiFetch } from '../config/api';

// ── Track presentation ────────────────────────────────────────────────────

const TRACK_ICON = {
  reasoning: Brain,
  code: Cpu,
  math: Calculator,
  general: Globe2,
};

const TRACK_TINT = {
  reasoning: { fg: C.ind,    dim: C.indDim,   border: C.borderI },
  code:      { fg: C.acc,    dim: C.accDim,   border: C.borderA },
  math:      { fg: C.warning,dim: C.warningDim, border: `${C.warning}55` },
  general:   { fg: C.info,   dim: 'rgba(56,189,248,0.15)', border: `${C.info}55` },
};

const TRACK_FALLBACK = { fg: C.txtS, dim: 'rgba(148,163,184,0.12)', border: C.border };

function tone(trackId) { return TRACK_TINT[trackId] || TRACK_FALLBACK; }

const METHOD_LABEL = {
  keyword: 'Keyword score',
  llm: 'LLM tiebreak',
  fallback: 'Fallback (no signal)',
  pinned: 'User pinned',
  compare: 'Compare-mode A/B',
};

// ── Helpers ───────────────────────────────────────────────────────────────

function fmtMs(ms) {
  if (!ms && ms !== 0) return '—';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

function avgScore(scores) {
  const v = Object.values(scores || {});
  if (!v.length) return null;
  return v.reduce((a, b) => a + b, 0) / v.length;
}

function input(extras = {}) {
  return {
    width: '100%', background: C.bgI, border: `1px solid ${C.border}`,
    borderRadius: 6, color: C.txtP, padding: '8px 10px',
    fontFamily: F.mono, fontSize: 12, outline: 'none', ...extras,
  };
}

function btn(kind = 'default', disabled = false) {
  const base = {
    display: 'inline-flex', alignItems: 'center', gap: 6,
    padding: '7px 12px', fontFamily: F.ui, fontSize: 12, fontWeight: 600,
    border: `1px solid ${C.border}`, borderRadius: 6,
    background: 'transparent', color: C.txtS,
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.55 : 1,
  };
  if (kind === 'primary') return { ...base, background: C.acc, color: '#0a0e16', border: 'none' };
  if (kind === 'danger') return { ...base, color: C.danger, borderColor: `${C.danger}55` };
  if (kind === 'ghost') return { ...base, padding: '4px 8px', fontSize: 11 };
  return base;
}

// ── Track card ────────────────────────────────────────────────────────────

function TrackCard({ track, isPinned, onPin, onUnpin }) {
  const Icon = TRACK_ICON[track.track_id] || Compass;
  const t = tone(track.track_id);
  const has = track.has_adapter;
  const avg = has ? avgScore(track.champion_scores) : null;
  return (
    <div style={{
      background: C.bgC, border: `1px solid ${isPinned ? t.fg : C.border}`,
      borderRadius: 8, padding: 12, display: 'flex', flexDirection: 'column', gap: 8,
      position: 'relative',
      boxShadow: isPinned ? `0 0 0 2px ${t.dim}` : 'none',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <div style={{
          width: 28, height: 28, borderRadius: 7,
          background: t.dim, border: `1px solid ${t.border}`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <Icon size={15} color={t.fg} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontFamily: F.ui, fontSize: 12.5, fontWeight: 700, color: C.txtP }}>
            {track.name}
          </div>
          <div style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM }}>
            {track.track_id}
          </div>
        </div>
        {has ? (
          <span style={{
            padding: '2px 7px', borderRadius: 999,
            background: t.dim, color: t.fg, border: `1px solid ${t.border}`,
            fontFamily: F.mono, fontSize: 9, letterSpacing: '0.05em', textTransform: 'uppercase',
          }}>adapter</span>
        ) : (
          <span style={{
            padding: '2px 7px', borderRadius: 999,
            background: 'rgba(148,163,184,0.12)', color: C.txtM, border: `1px solid ${C.border}`,
            fontFamily: F.mono, fontSize: 9, letterSpacing: '0.05em', textTransform: 'uppercase',
          }}>base</span>
        )}
      </div>
      {track.description ? (
        <div style={{ fontFamily: F.ui, fontSize: 11.5, color: C.txtS, lineHeight: 1.45 }}>
          {track.description}
        </div>
      ) : null}
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
        {(track.target_benchmarks || []).map((b) => (
          <span key={b} style={{
            padding: '2px 6px', fontFamily: F.mono, fontSize: 9.5,
            background: C.bgI, border: `1px solid ${C.border}`, color: C.txtS, borderRadius: 4,
          }}>{b}</span>
        ))}
      </div>
      {has ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontFamily: F.mono, fontSize: 10.5, color: C.txtM }}>
          <span>gen {track.champion_generation}</span>
          <span>·</span>
          <span>avg {avg != null ? avg.toFixed(3) : '—'}</span>
        </div>
      ) : null}
      <div style={{ display: 'flex', gap: 6, marginTop: 'auto' }}>
        {isPinned ? (
          <button type="button" onClick={onUnpin} style={btn('ghost')}>Unpin</button>
        ) : (
          <button type="button" onClick={onPin} style={btn('ghost')}>Pin</button>
        )}
      </div>
    </div>
  );
}

// ── Routing decision panel ────────────────────────────────────────────────

function RoutingPanel({ route }) {
  if (!route) return null;
  const t = tone(route.track_id);
  const Icon = TRACK_ICON[route.track_id] || Compass;
  return (
    <div style={{
      background: t.dim, border: `1px solid ${t.border}`, borderRadius: 8,
      padding: 12, display: 'flex', flexDirection: 'column', gap: 8,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Icon size={14} color={t.fg} />
        <span style={{ fontFamily: F.ui, fontSize: 13, fontWeight: 700, color: t.fg }}>
          Routed to {route.track_name}
        </span>
        <span style={{
          marginLeft: 'auto', padding: '2px 8px', borderRadius: 999,
          background: 'rgba(0,0,0,0.25)', color: t.fg, border: `1px solid ${t.border}`,
          fontFamily: F.mono, fontSize: 10, letterSpacing: '0.06em', textTransform: 'uppercase',
        }}>
          {METHOD_LABEL[route.method] || route.method} · {(route.confidence * 100).toFixed(0)}%
        </span>
      </div>
      <div style={{ fontFamily: F.ui, fontSize: 11.5, color: C.txtS }}>
        {route.reason}
      </div>
      {(route.all_scores || []).filter((s) => s.score > 0).length > 0 ? (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {(route.all_scores || []).map((s) => {
            const sc = tone(s.track_id);
            const isWin = s.track_id === route.track_id;
            return (
              <span key={s.track_id} style={{
                padding: '2px 7px', fontFamily: F.mono, fontSize: 10,
                background: isWin ? sc.dim : 'transparent',
                color: s.score > 0 ? sc.fg : C.txtM,
                border: `1px solid ${isWin ? sc.border : C.border}`,
                borderRadius: 999,
              }}>
                {s.track_id} {s.score}
                {s.matches?.length > 0 ? ` · ${s.matches.slice(0, 2).join(', ')}` : ''}
              </span>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

// ── Markdown response component ───────────────────────────────────────────

function MarkdownView({ text }) {
  return (
    <div style={{ fontFamily: F.ui, fontSize: 13, color: C.txtP, lineHeight: 1.55 }}>
      <ReactMarkdown
        components={{
          code({ inline, children, ...props }) {
            return inline ? (
              <code style={{ fontFamily: F.mono, fontSize: 12, background: C.bgI, padding: '1px 5px', borderRadius: 3, color: C.acc }} {...props}>{children}</code>
            ) : (
              <pre style={{ fontFamily: F.mono, fontSize: 11.5, background: C.bgI, border: `1px solid ${C.border}`, padding: 10, borderRadius: 6, overflowX: 'auto' }}>
                <code {...props}>{children}</code>
              </pre>
            );
          },
          a({ children, ...props }) {
            return <a {...props} style={{ color: C.acc }}>{children}</a>;
          },
          li({ children, ...props }) {
            return <li style={{ margin: '2px 0' }} {...props}>{children}</li>;
          },
        }}
      >
        {text || ''}
      </ReactMarkdown>
    </div>
  );
}

// ── Conversation ──────────────────────────────────────────────────────────

function Turn({ turn }) {
  const Icon = TRACK_ICON[turn.route?.track_id] || Compass;
  const t = tone(turn.route?.track_id);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: '12px 0', borderTop: `1px solid ${C.border}` }}>
      <div style={{ fontFamily: F.mono, fontSize: 10.5, color: C.txtM, letterSpacing: '0.06em', textTransform: 'uppercase' }}>You</div>
      <div style={{ fontFamily: F.ui, fontSize: 13.5, color: C.txtP, whiteSpace: 'pre-wrap' }}>
        {turn.prompt}
      </div>
      <RoutingPanel route={turn.route} />
      <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
          <Icon size={14} color={t.fg} />
          <span style={{ fontFamily: F.ui, fontSize: 12, color: t.fg, fontWeight: 600 }}>
            {turn.route?.track_name || 'Answer'}
          </span>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, fontFamily: F.mono, fontSize: 10, color: C.txtM }}>
            <span>{turn.backend}</span>
            <span>·</span>
            <span>{turn.tokens || 0} tok</span>
            <span>·</span>
            <span>{fmtMs(turn.latency_ms)}</span>
            {turn.adapter_id ? <><span>·</span><span style={{ color: C.acc }}>{turn.adapter_id}</span></> : null}
          </div>
        </div>
        <MarkdownView text={turn.response} />
      </div>
      {turn.compare ? (
        <CompareGrid compare={turn.compare} />
      ) : null}
    </div>
  );
}

function CompareGrid({ compare }) {
  return (
    <div>
      <div style={{ fontFamily: F.mono, fontSize: 10.5, color: C.txtM, letterSpacing: '0.06em', textTransform: 'uppercase', margin: '4px 0 6px' }}>
        Compare across all tracks
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 8 }}>
        {(compare.answers || []).map((ans) => {
          const r = ans.route || {};
          const Icon = TRACK_ICON[r.track_id] || Compass;
          const t = tone(r.track_id);
          const isChosen = r.track_id === compare.chosen?.track_id;
          return (
            <div key={r.track_id} style={{
              background: C.bgC, border: `1px solid ${isChosen ? t.fg : C.border}`,
              borderRadius: 8, padding: 10,
              boxShadow: isChosen ? `0 0 0 2px ${t.dim}` : 'none',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                <Icon size={13} color={t.fg} />
                <span style={{ fontFamily: F.ui, fontSize: 12, fontWeight: 600, color: t.fg }}>
                  {r.track_name}
                </span>
                {isChosen ? <span style={{ marginLeft: 'auto', fontFamily: F.mono, fontSize: 9, color: t.fg, padding: '1px 6px', background: t.dim, border: `1px solid ${t.border}`, borderRadius: 999, textTransform: 'uppercase', letterSpacing: '0.06em' }}>chosen</span> : null}
              </div>
              {ans.error ? (
                <div style={{ fontFamily: F.mono, fontSize: 11, color: C.danger, whiteSpace: 'pre-wrap' }}>
                  {ans.error}
                </div>
              ) : (
                <div style={{ fontFamily: F.ui, fontSize: 12, color: C.txtP, lineHeight: 1.45, maxHeight: 200, overflowY: 'auto', whiteSpace: 'pre-wrap' }}>
                  {(ans.response || '').slice(0, 800)}
                  {(ans.response || '').length > 800 ? '…' : ''}
                </div>
              )}
              <div style={{ marginTop: 6, display: 'flex', gap: 8, fontFamily: F.mono, fontSize: 9.5, color: C.txtM }}>
                <span>{ans.backend}</span>
                <span>·</span>
                <span>{ans.tokens || 0} tok</span>
                <span>·</span>
                <span>{fmtMs(ans.latency_ms)}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────

const STORAGE_KEY = 'forge-history-v1';

export default function ForgeAgentPage() {
  const [tracks, setTracks] = useState([]);
  const [history, setHistory] = useState(() => {
    try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'); }
    catch { return []; }
  });
  const [prompt, setPrompt] = useState('');
  const [pinnedTrack, setPinnedTrack] = useState(null);
  const [forceBase, setForceBase] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [maxTokens, setMaxTokens] = useState(256);
  const [temperature, setTemperature] = useState(0.7);
  const conversationRef = useRef(null);

  const loadTracks = useCallback(async () => {
    try {
      const r = await apiFetch('/api/forge/tracks');
      setTracks(r?.tracks || []);
    } catch { setTracks([]); }
  }, []);

  useEffect(() => { loadTracks(); }, [loadTracks]);

  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(history.slice(-30))); }
    catch { /* ignore */ }
  }, [history]);

  useEffect(() => {
    if (conversationRef.current) {
      conversationRef.current.scrollTop = conversationRef.current.scrollHeight;
    }
  }, [history.length]);

  async function syncTracks() {
    setBusy(true);
    setErr(null);
    try {
      const r = await apiFetch('/api/forge/sync_tracks', { method: 'POST', body: '{}' });
      const n = (r?.updated || []).length;
      if (n > 0) {
        const summary = (r.updated || []).map((u) =>
          `${u.track_id}: ${u.run_id}::gen${u.generation} (avg ${u.avg})`
        ).join(' · ');
        setErr(null);
        // Reuse the "err" pill area for a positive flash via console only;
        // the track grid will refresh and reflect the change.
        console.log('[forge] sync_tracks promoted:', summary);
      }
      await loadTracks();
      if (n === 0) setErr('Sync ran — no track had a better champion to promote');
    } catch (e) {
      setErr(`Sync failed: ${e?.message || 'unknown'}`);
    } finally {
      setBusy(false);
    }
  }

  async function send({ compareMode = false } = {}) {
    const p = prompt.trim();
    if (!p || busy) return;
    setBusy(true);
    setErr(null);
    try {
      let body, endpoint;
      if (compareMode) {
        endpoint = '/api/forge/compare';
        body = { prompt: p, max_tokens: maxTokens, temperature };
      } else {
        endpoint = '/api/forge/query';
        body = { prompt: p, max_tokens: maxTokens, temperature, force_base: forceBase };
        if (pinnedTrack) body.track_id = pinnedTrack;
      }
      const r = await apiFetch(endpoint, { method: 'POST', body: JSON.stringify(body) });
      let turn;
      if (compareMode) {
        const chosen = (r.answers || []).find((a) => a.route?.track_id === r.chosen?.track_id) || (r.answers || [])[0];
        turn = {
          id: Date.now(), prompt: p,
          route: chosen?.route || r.chosen,
          response: chosen?.response || '',
          backend: chosen?.backend, tokens: chosen?.tokens, latency_ms: chosen?.latency_ms,
          adapter_id: chosen?.adapter_id, model: chosen?.model,
          compare: r,
        };
      } else {
        turn = { id: Date.now(), prompt: p, ...r };
      }
      setHistory((h) => [...h, turn]);
      setPrompt('');
    } catch (e) {
      setErr(e?.message || 'Query failed');
    } finally {
      setBusy(false);
    }
  }

  const totalTracksWithAdapters = useMemo(
    () => tracks.filter((t) => t.has_adapter).length,
    [tracks],
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, padding: '8px 0 40px', maxWidth: 1700, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <Compass size={22} color={C.acc} />
        <div style={{ flex: 1 }}>
          <h1 style={{ fontFamily: F.display, fontSize: 26, color: C.txtP, margin: 0 }}>ForgeAgent</h1>
          <p style={{ fontFamily: F.ui, fontSize: 13, color: C.txtM, margin: '4px 0 0' }}>
            Classifier-routed inference. Picks the best specialist track for each prompt — keyword scoring first, LLM tiebreak when ambiguous, falls back to base via Ollama when no champion adapter is registered yet.
          </p>
        </div>
      </div>

      {/* Tracks grid */}
      <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 14 }}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 10 }}>
          <span style={{ fontFamily: F.ui, fontSize: 12, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: C.txtM, display: 'inline-flex', alignItems: 'center', gap: 8 }}>
            <Target size={13} /> Specialist tracks
          </span>
          <span style={{ marginLeft: 12, fontFamily: F.mono, fontSize: 11, color: C.txtM }}>
            {totalTracksWithAdapters}/{tracks.length} with champion adapters
          </span>
          <button type="button" onClick={syncTracks} disabled={busy} style={{ ...btn('default', busy), marginLeft: 'auto' }}>
            <Zap size={11} /> Sync from existing champions
          </button>
          <button type="button" onClick={loadTracks} style={btn('ghost')}>
            <RefreshCw size={11} /> Refresh
          </button>
        </div>
        {tracks.length === 0 ? (
          <div style={{ padding: 18, textAlign: 'center', color: C.txtM, fontFamily: F.ui, fontSize: 12 }}>
            No tracks yet — restart the API to seed the 4 defaults.
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 10 }}>
            {tracks.map((t) => (
              <TrackCard
                key={t.track_id}
                track={t}
                isPinned={pinnedTrack === t.track_id}
                onPin={() => setPinnedTrack(t.track_id)}
                onUnpin={() => setPinnedTrack(null)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Composer */}
      <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 14 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
          <span style={{ fontFamily: F.ui, fontSize: 12, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: C.txtM, display: 'inline-flex', alignItems: 'center', gap: 8 }}>
            <Wand2 size={13} /> Ask the forge
          </span>
          {pinnedTrack ? (
            <span style={{
              padding: '2px 8px', borderRadius: 999,
              background: tone(pinnedTrack).dim, color: tone(pinnedTrack).fg, border: `1px solid ${tone(pinnedTrack).border}`,
              fontFamily: F.mono, fontSize: 10, letterSpacing: '0.05em', textTransform: 'uppercase',
            }}>pinned: {pinnedTrack}</span>
          ) : null}
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontFamily: F.mono, fontSize: 10.5, color: C.txtM }}>
              max
              <input type="number" min={32} max={1024} step={32} value={maxTokens} onChange={(e) => setMaxTokens(Number(e.target.value || 256))} style={{ ...input({ width: 70, padding: '4px 6px', fontSize: 11 }) }} />
            </label>
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontFamily: F.mono, fontSize: 10.5, color: C.txtM }}>
              temp
              <input type="number" min={0} max={1.5} step={0.1} value={temperature} onChange={(e) => setTemperature(Number(e.target.value || 0.7))} style={{ ...input({ width: 60, padding: '4px 6px', fontSize: 11 }) }} />
            </label>
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontFamily: F.ui, fontSize: 11, color: C.txtS, cursor: 'pointer' }}>
              <input type="checkbox" checked={forceBase} onChange={(e) => setForceBase(e.target.checked)} style={{ accentColor: C.acc }} />
              force base
            </label>
          </div>
        </div>
        <textarea
          rows={3}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); send(); }
          }}
          placeholder="Ask anything — the classifier picks the specialist. ⌘/Ctrl+Enter to send."
          style={input({ minHeight: 64, resize: 'vertical' })}
        />
        <div style={{ marginTop: 10, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <button type="button" onClick={() => send()} disabled={!prompt.trim() || busy} style={btn('primary', !prompt.trim() || busy)}>
            {busy ? <Loader2 size={13} className="spin" /> : <Send size={13} />}
            Send
          </button>
          <button type="button" onClick={() => send({ compareMode: true })} disabled={!prompt.trim() || busy} style={btn('default', !prompt.trim() || busy)}>
            <GitCompare size={13} /> Compare across all tracks
          </button>
          {history.length > 0 ? (
            <button type="button" onClick={() => setHistory([])} style={btn('ghost')}>
              <Trash2 size={11} /> Clear conversation
            </button>
          ) : null}
          {err ? <span style={{ fontFamily: F.mono, fontSize: 11, color: C.danger }}>{err}</span> : null}
        </div>
      </div>

      {/* Conversation */}
      <div ref={conversationRef} style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 14, maxHeight: 'calc(100vh - 480px)', overflowY: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
          <span style={{ fontFamily: F.ui, fontSize: 12, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: C.txtM, display: 'inline-flex', alignItems: 'center', gap: 8 }}>
            <Activity size={13} /> Conversation
          </span>
          {history.length > 0 ? (
            <span style={{ fontFamily: F.mono, fontSize: 10.5, color: C.txtM }}>
              {history.length} turn{history.length === 1 ? '' : 's'}
            </span>
          ) : null}
        </div>
        {history.length === 0 ? (
          <div style={{ padding: 24, textAlign: 'center', color: C.txtM, fontFamily: F.ui, fontSize: 13 }}>
            <Sparkles size={20} color={C.txtM} style={{ marginBottom: 6 }} />
            <div>Try: <em>"Calculate 17 × 23"</em> · <em>"Write a Python function for fibonacci"</em> · <em>"Why is the sky blue?"</em></div>
            <div style={{ marginTop: 4 }}>The classifier will route each to a different specialist.</div>
          </div>
        ) : (
          history.map((turn) => <Turn key={turn.id} turn={turn} />)
        )}
      </div>

      <style>{`
        .spin { animation: spin 1s linear infinite; }
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}
