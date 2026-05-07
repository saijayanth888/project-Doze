// Static reference data for in-app automation tooltips.
// Keys are the seeded workflow `name` strings — they MUST match exactly
// (case + spaces) the names defined in
// apps/api/src/services/automation_engine/seeds.py:
//   "Nightly Evolution", "Drift Detection", "Health Monitor",
//   "Daily Report", "Weekly Summary", "Auto Cleanup",
//   "Champion-Promoted Slack Ping"
// User-created workflows have arbitrary names and will not have entries here;
// callers should treat a missing entry as "no explainer available".
export const AUTOMATION_INFO = {
  'Nightly Evolution': {
    name: 'Nightly Evolution',
    description:
      'Kicks off a small Llama 3.2 3B evolution run aimed at the weakest benchmark each night.',
    when_it_fires: 'Daily at 02:00 UTC by default (currently disabled).',
    what_it_does:
      'Starts a small Llama 3.2 3B evolution run aimed at the weakest benchmark. Sends a Slack ping when the run kicks off.',
    side_effects:
      'Holds the GPU for ~2-5 hours and competes with manual runs. Enable only if the box is dedicated overnight.',
    destructive: true,
  },
  'Drift Detection': {
    name: 'Drift Detection',
    description:
      'Watches for benchmark regressions across consecutive generations and alerts on Slack.',
    when_it_fires: 'Every 6 hours.',
    what_it_does:
      'Compares the latest two generations across every benchmark. If any benchmark drops more than 5%, posts a Slack alert with the delta.',
    side_effects: null,
    destructive: false,
  },
  'Health Monitor': {
    name: 'Health Monitor',
    description:
      'Liveness check across Postgres, Redis, and Ollama with Slack alerts on failure.',
    when_it_fires: 'Every 15 minutes.',
    what_it_does:
      'Pings Postgres, Redis, and Ollama for liveness. Posts a Slack alert if any service fails.',
    side_effects: null,
    destructive: false,
  },
  'Daily Report': {
    name: 'Daily Report',
    description:
      'Posts a one-line Slack summary linking to /dashboard with the current champion.',
    when_it_fires: 'Daily at 08:00 UTC (currently disabled).',
    what_it_does:
      'Posts a one-line Slack summary linking to /dashboard with the current champion.',
    side_effects: null,
    destructive: false,
  },
  'Weekly Summary': {
    name: 'Weekly Summary',
    description:
      'Posts a Slack summary linking to /history with the past 7 days of evolution runs.',
    when_it_fires: 'Sunday at 09:00 UTC (currently disabled).',
    what_it_does:
      'Posts a Slack summary linking to /history with the past 7 days of evolution runs.',
    side_effects: null,
    destructive: false,
  },
  'Auto Cleanup': {
    name: 'Auto Cleanup',
    description:
      'Deletes adapter directories on disk older than the configured keep-days threshold.',
    when_it_fires: 'Sunday at 03:00 UTC.',
    what_it_does:
      'Deletes adapter directories on disk older than the configured keep-days threshold (default 7 days).',
    side_effects:
      'Permanently removes adapter weights from disk. Adapters that have been promoted to champion are never deleted by this job, but anything else older than the threshold is gone.',
    destructive: true,
  },
  'Champion-Promoted Slack Ping': {
    name: 'Champion-Promoted Slack Ping',
    description:
      "Announces a new champion's generation number and average score on Slack.",
    when_it_fires: 'Whenever a new champion is promoted (event-driven, not cron).',
    what_it_does:
      "Posts a Slack message announcing the new champion's generation number and average score.",
    side_effects: null,
    destructive: false,
  },
};
