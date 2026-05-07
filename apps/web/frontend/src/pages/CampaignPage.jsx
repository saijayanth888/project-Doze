import { useCallback, useEffect, useState } from 'react';
import { Play, ChevronDown, ChevronRight, FlaskConical } from 'lucide-react';
import { C, F } from '../config/colors';
import { apiFetch } from '../config/api';
import { CONCEPT_INFO } from '../data/benchmarkInfo';
import InfoTooltip from '../components/shared/InfoTooltip';
import LoadingSkeleton from '../components/shared/LoadingSkeleton';
import { useToast } from '../context/ToastContext';

function humanizeCampaignId(id) {
  return String(id)
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function ExperimentRow({ exp }) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(0,2fr) 120px 120px',
        gap: 10,
        padding: '6px 12px',
        borderBottom: `1px solid ${C.border}`,
        fontFamily: F.mono,
        fontSize: 11,
        color: C.txtS,
      }}
    >
      <span
        style={{
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          color: C.txtP,
        }}
      >
        {exp.model_id || exp.base_model || '—'}
      </span>
      <span style={{ color: C.txtM }}>{exp.method || '—'}</span>
      <span style={{ color: C.txtM, textAlign: 'right' }}>
        {exp.max_generations != null ? `${exp.max_generations} gen` : '—'}
      </span>
    </div>
  );
}

function CampaignCard({ campaign }) {
  const [open, setOpen] = useState(false);
  const toast = useToast();

  const experiments = campaign.experiments || [];
  const name = campaign.name || humanizeCampaignId(campaign.id || campaign.campaign_id || '');
  const description = campaign.description || '';
  const expCount = experiments.length;

  return (
    <div
      style={{
        background: 'var(--bg-card, #111827)',
        border: `1px solid ${C.border}`,
        borderRadius: 10,
        overflow: 'hidden',
      }}
    >
      {/* Card header */}
      <div style={{ padding: '16px 18px 14px' }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'space-between',
            gap: 12,
            flexWrap: 'wrap',
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <div
              style={{
                fontFamily: F.display || F.ui,
                fontSize: 16,
                fontWeight: 700,
                color: 'var(--text-primary, #f1f5f9)',
                marginBottom: 4,
              }}
            >
              {name}
            </div>
            {description ? (
              <div
                style={{
                  fontFamily: F.ui,
                  fontSize: 12,
                  color: 'var(--text-secondary, #94a3b8)',
                  lineHeight: 1.55,
                  marginBottom: 6,
                }}
              >
                {description}
              </div>
            ) : null}
            <div
              style={{
                fontFamily: F.mono,
                fontSize: 11,
                color: C.txtM,
              }}
            >
              {expCount} experiment{expCount !== 1 ? 's' : ''}
            </div>
          </div>

          <button
            type="button"
            onClick={() =>
              toast.show(
                'Campaign autopilot endpoint not yet wired — backend Phase 5.2 task.',
                'info',
              )
            }
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              padding: '8px 14px',
              background: C.acc || '#76b900',
              color: '#000',
              border: 'none',
              borderRadius: 6,
              cursor: 'pointer',
              fontFamily: F.ui,
              fontSize: 12,
              fontWeight: 700,
              whiteSpace: 'nowrap',
              flexShrink: 0,
            }}
          >
            <Play size={12} fill="currentColor" />
            Start Campaign
          </button>
        </div>
      </div>

      {/* Collapsible experiments */}
      {expCount > 0 ? (
        <>
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              width: '100%',
              padding: '8px 18px',
              background: 'rgba(255,255,255,0.025)',
              border: 'none',
              borderTop: `1px solid ${C.border}`,
              cursor: 'pointer',
              color: C.txtM,
              fontFamily: F.mono,
              fontSize: 11,
              letterSpacing: '0.05em',
              textTransform: 'uppercase',
              textAlign: 'left',
            }}
          >
            {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
            {open ? 'Hide' : 'Show'} experiments
          </button>

          {open ? (
            <div>
              {/* Column headers */}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'minmax(0,2fr) 120px 120px',
                  gap: 10,
                  padding: '6px 12px',
                  borderBottom: `1px solid ${C.border}`,
                  background: 'rgba(255,255,255,0.02)',
                  fontFamily: F.mono,
                  fontSize: 9,
                  letterSpacing: '0.08em',
                  textTransform: 'uppercase',
                  color: C.txtM,
                }}
              >
                <span>Model</span>
                <span>Method</span>
                <span style={{ textAlign: 'right' }}>Max Gen</span>
              </div>
              {experiments.map((exp, i) => (
                <ExperimentRow key={exp.experiment_id || exp.id || i} exp={exp} />
              ))}
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

export default function CampaignPage() {
  const [campaigns, setCampaigns] = useState(null);
  const [loading, setLoading] = useState(true);
  const toast = useToast();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch('/api/campaigns');
      setCampaigns(Array.isArray(data) ? data : data?.campaigns || []);
    } catch (e) {
      toast.show(
        `Failed to load campaigns: ${e?.message || 'network error'}`,
        'danger',
      );
      setCampaigns([]);
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Page heading */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
        <FlaskConical size={24} color={C.acc || '#76b900'} style={{ marginTop: 3, flexShrink: 0 }} />
        <div>
          <h1
            style={{
              fontFamily: F.display || F.ui,
              fontSize: 26,
              fontWeight: 700,
              color: 'var(--text-primary, #f1f5f9)',
              margin: 0,
              display: 'flex',
              alignItems: 'center',
              gap: 6,
            }}
          >
            Research Campaigns
            <InfoTooltip info={CONCEPT_INFO.ept} />
          </h1>
          <p
            style={{
              fontFamily: F.ui,
              fontSize: 13,
              color: 'var(--text-secondary, #94a3b8)',
              margin: '6px 0 0',
              lineHeight: 1.6,
              maxWidth: 680,
            }}
          >
            A <strong style={{ color: 'var(--text-primary, #f1f5f9)' }}>Research Campaign</strong> is a
            pre-configured sequence of evolution experiments designed to systematically improve a model
            across multiple tasks. Each campaign bundles a set of (model, method, generations) tuples
            that run in order, producing a lineage you can inspect and promote.
          </p>
        </div>
      </div>

      {/* Content */}
      {loading ? (
        <LoadingSkeleton rows={4} height={80} />
      ) : campaigns && campaigns.length > 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {campaigns.map((c, i) => (
            <CampaignCard
              key={c.id || c.campaign_id || i}
              campaign={c}
            />
          ))}
        </div>
      ) : (
        <div
          style={{
            padding: '40px 24px',
            background: 'var(--bg-card, #111827)',
            border: `1px solid ${C.border}`,
            borderRadius: 10,
            textAlign: 'center',
          }}
        >
          <p
            style={{
              fontFamily: F.ui,
              fontSize: 13,
              color: 'var(--text-secondary, #94a3b8)',
              margin: 0,
              lineHeight: 1.6,
            }}
          >
            No campaigns configured. See{' '}
            <code
              style={{
                fontFamily: F.mono,
                fontSize: 12,
                color: 'var(--text-primary, #f1f5f9)',
                background: 'rgba(255,255,255,0.06)',
                padding: '1px 5px',
                borderRadius: 4,
              }}
            >
              apps/api/src/services/campaign_configs.py
            </code>
          </p>
        </div>
      )}
    </div>
  );
}
