'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { RequireRole } from '@/components/RequireRole';
import { apiFetch } from '@/lib/apiClient';
import { useIdentity } from '@/lib/useIdentity';
import { HelpTip } from '@/components/onboarding/HelpTip';
import { RefreshCcw, Save, AlertTriangle, ExternalLink } from 'lucide-react';

type RawMeResponse = {
  lineage?: Array<{ org_id?: string; node_id: string; name?: string; node_type?: string; parent_id?: string | null }>;
  configs?: Record<string, unknown>;
};

export default function TeamConfigurationPage() {
  const { identity } = useIdentity();

  const [effective, setEffective] = useState<unknown | null>(null);
  const [raw, setRaw] = useState<RawMeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [overridesText, setOverridesText] = useState('{\n  \n}');
  const [saving, setSaving] = useState(false);

  const effectivePretty = useMemo(() => {
    if (!effective) return '';
    try {
      return JSON.stringify(effective, null, 2);
    } catch {
      return String(effective);
    }
  }, [effective]);

  const rawPretty = useMemo(() => {
    if (!raw) return '';
    try {
      return JSON.stringify(raw, null, 2);
    } catch {
      return String(raw);
    }
  }, [raw]);

  const lineageLabel = useMemo(() => {
    const lineage = raw?.lineage || [];
    if (!lineage.length) return '—';
    return lineage.map((n) => n.name || n.node_id).join(' → ');
  }, [raw?.lineage]);

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const [effRes, rawRes] = await Promise.all([
        apiFetch('/api/config/me/effective', { cache: 'no-store' }),
        apiFetch('/api/config/me/raw', { cache: 'no-store' }),
      ]);

      if (!effRes.ok) throw new Error(`effective: ${effRes.status} ${effRes.statusText}: ${await effRes.text()}`);
      if (!rawRes.ok) throw new Error(`raw: ${rawRes.status} ${rawRes.statusText}: ${await rawRes.text()}`);

      setEffective(await effRes.json());
      setRaw((await rawRes.json()) as RawMeResponse);
    } catch (e: any) {
      setEffective(null);
      setRaw(null);
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  };

  const saveOverrides = async () => {
    setSaving(true);
    setError(null);
    try {
      const parsed = JSON.parse(overridesText);
      const res = await apiFetch('/api/config/me', {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(parsed),
      });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${await res.text()}`);
      await refresh();
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setSaving(false);
    }
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

    return (
    <RequireRole role="team" fallbackHref="/">
      <div className="p-8 max-w-6xl mx-auto space-y-6">
        <div className="flex items-start justify-between gap-4">
                <div>
            <h1 className="text-2xl font-semibold text-gray-900 dark:text-white flex items-center gap-2">
              Team Configuration
              <HelpTip id="team-config" position="right">
                <strong>Configuration</strong> controls how IncidentFox connects to your integrations (Grafana, K8s, Slack) and how AI agents behave. Settings inherit from organization defaults and can be overridden per team.
              </HelpTip>
            </h1>
            <p className="text-sm text-gray-500 mt-1">
              Backed by config service: <span className="font-mono">/api/v1/config/me/*</span>
            </p>
            <div className="mt-2 text-xs text-gray-500 flex items-center gap-1">
              Lineage: <span className="font-mono">{lineageLabel}</span>
              <HelpTip id="config-lineage" position="right">
                <strong>Lineage</strong> shows the configuration hierarchy. Settings cascade from Organization to Team level, with more specific levels overriding general ones.
              </HelpTip>
            </div>
                </div>
                
          <div className="flex items-center gap-2">
            <Link
              href="/settings"
              className="px-3 py-2 text-sm font-medium bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
            >
              Token / Settings
            </Link>
                        <button 
              onClick={refresh}
              disabled={loading}
              className="flex items-center gap-2 px-3 py-2 text-sm font-medium bg-gray-100 dark:bg-gray-800 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 disabled:opacity-70"
            >
              <RefreshCcw className="w-4 h-4" /> {loading ? 'Refreshing…' : 'Refresh'}
                                        </button>
                </div>
            </div>

        {identity?.can_write === false && (
          <div className="text-sm text-yellow-800 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-100 dark:border-yellow-900/40 rounded-lg p-3 flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 mt-0.5" />
            <div>
              Writes are disabled for this identity (<span className="font-mono">can_write=false</span>). You can still view config.
                                </div>
                            </div>
        )}

        {error && (
          <div className="text-sm text-red-600 bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/40 rounded-lg p-3">
            {error}
                                        </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-5 shadow-sm space-y-2">
            <div className="flex items-center justify-between">
              <div className="text-sm font-semibold text-gray-900 dark:text-white flex items-center gap-1">
                Effective config
                <HelpTip id="effective-config" position="right">
                  The <strong>effective config</strong> is the final merged result of all settings from org defaults + team overrides. This is what IncidentFox actually uses.
                </HelpTip>
              </div>
              <a
                href="#"
                className="text-xs text-gray-400 flex items-center gap-1 pointer-events-none"
                aria-disabled="true"
                title="Linking to docs will be wired once we expose docs URLs in config schema."
              >
                Docs <ExternalLink className="w-3 h-3" />
                                                            </a>
                                                        </div>
            <pre className="h-[60vh] overflow-auto bg-gray-50 dark:bg-gray-950/50 border border-gray-200 dark:border-gray-800 rounded-lg p-3 text-xs font-mono text-gray-700 dark:text-gray-200">
              {effectivePretty || '(not loaded)'}
            </pre>
                                                </div>
                                                
          <div className="space-y-6">
            <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-5 shadow-sm space-y-2">
              <div className="text-sm font-semibold text-gray-900 dark:text-white">Raw lineage + per-node configs</div>
              <pre className="h-[28vh] overflow-auto bg-gray-50 dark:bg-gray-950/50 border border-gray-200 dark:border-gray-800 rounded-lg p-3 text-xs font-mono text-gray-700 dark:text-gray-200">
                {rawPretty || '(not loaded)'}
              </pre>
                                </div>

            <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-5 shadow-sm space-y-3">
              <div>
                <div className="text-sm font-semibold text-gray-900 dark:text-white flex items-center gap-1">
                  Team overrides
                  <HelpTip id="team-overrides" position="right">
                    <strong>Overrides</strong> let you customize settings for your team without changing org-wide defaults. Enter JSON to override specific values (e.g., Grafana URLs, alert thresholds).
                  </HelpTip>
                </div>
                <p className="text-xs text-gray-500 mt-1">
                  This payload is deep-merged (PATCH semantics) into existing team overrides via{' '}
                  <span className="font-mono">PUT /api/v1/config/me</span>.
                                                    </p>
                                                </div>

              <textarea
                value={overridesText}
                onChange={(e) => setOverridesText(e.target.value)}
                rows={10}
                className="w-full p-3 font-mono text-xs rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-950 focus:outline-none focus:ring-2 focus:ring-orange-500"
              />

              <div className="flex justify-end">
                                                         <button 
                  onClick={saveOverrides}
                  disabled={saving || identity?.can_write === false}
                  className="flex items-center gap-2 px-4 py-2 text-sm font-medium bg-orange-600 text-white rounded-lg hover:bg-orange-700 disabled:opacity-70"
                >
                  <Save className="w-4 h-4" /> {saving ? 'Saving…' : 'Save overrides'}
                                                            </button>
                                                        </div>
                                                    </div>
                                                                </div>
                                                            </div>
                                                        </div>
    </RequireRole>
  );
}


