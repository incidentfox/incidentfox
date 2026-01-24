'use client';

import Link from 'next/link';
import { RequireRole } from '@/components/RequireRole';
import { useIdentity } from '@/lib/useIdentity';
import { useOnboarding } from '@/lib/useOnboarding';
import { QuickStartWizard } from '@/components/onboarding/QuickStartWizard';
import {
  ShieldCheck,
  Network,
  Bot,
  Users,
  Activity,
  TrendingUp,
  Clock,
  AlertCircle,
  CheckCircle,
  XCircle,
  Settings,
  FileText,
  Key,
  BarChart3,
  Zap,
  Cloud,
  MessageSquare,
  Github,
  Code,
  RefreshCw,
} from 'lucide-react';
import { useState, useEffect } from 'react';

interface DurationPercentiles {
  p50: number;
  p95: number;
  p99: number;
}

interface TeamStats {
  team_node_id: string;
  team_name: string;
  total_runs: number;
  successful_runs: number;
  failed_runs: number;
  success_rate: number;
  last_run_at: string | null;
  avg_duration_seconds: number | null;
  duration_percentiles: DurationPercentiles | null;
  most_used_agent: string | null;
  trend: 'up' | 'down' | 'stable';
  runs_this_week: number;
  runs_prev_week: number;
}

interface OrgStats {
  totalTeams: number;
  activeTeams: number;
  totalRuns: number;
  successRate: number;
  avgDurationSeconds: number | null;
  durationPercentiles: DurationPercentiles | null;
  teams: TeamStats[];
}

interface ActivityItem {
  id: string;
  type: 'run' | 'config' | 'token' | 'template';
  description: string;
  timestamp: string;
  status: 'success' | 'failed' | 'pending' | 'info';
  teamName?: string;
}

interface PendingItems {
  remediations: number;
  configChanges: number;
  expiringTokens: number;
}

interface ServiceHealth {
  name: string;
  status: 'healthy' | 'degraded' | 'down';
  lastCheck: string;
}

interface IntegrationHealth {
  name: string;
  status: 'connected' | 'error' | 'not_configured';
  icon: any;
}

export default function AdminHomePage() {
  const { identity, error } = useIdentity();
  const [stats, setStats] = useState<OrgStats | null>(null);
  const [activities, setActivities] = useState<ActivityItem[]>([]);
  const [pending, setPending] = useState<PendingItems>({ remediations: 0, configChanges: 0, expiringTokens: 0 });
  const [services, setServices] = useState<ServiceHealth[]>([]);
  const [integrations, setIntegrations] = useState<IntegrationHealth[]>([]);

  // Onboarding state
  const {
    shouldShowWelcome,
    markWelcomeSeen,
    markFirstAgentRunCompleted,
  } = useOnboarding();
  const [showWelcomeModal, setShowWelcomeModal] = useState(false);

  // Show welcome modal on first visit
  useEffect(() => {
    if (shouldShowWelcome) {
      setShowWelcomeModal(true);
    }
  }, [shouldShowWelcome]);

  useEffect(() => {
    if (!identity?.org_id) return;

    // Fetch org-wide stats
    fetch(`/api/admin/orgs/${identity.org_id}/stats`)
      .then(res => res.ok ? res.json() : null)
      .then(data => data && setStats(data))
      .catch(err => console.error('Failed to load stats:', err));

    // Fetch recent activity
    fetch(`/api/admin/orgs/${identity.org_id}/activity?limit=10`)
      .then(res => res.ok ? res.json() : null)
      .then(data => data && setActivities(data.activities || []))
      .catch(err => console.error('Failed to load activity:', err));

    // Fetch pending items
    fetch(`/api/admin/orgs/${identity.org_id}/pending`)
      .then(res => res.ok ? res.json() : null)
      .then(data => data && setPending(data))
      .catch(err => console.error('Failed to load pending items:', err));

    // Fetch system health (services + integrations)
    fetch(`/api/admin/orgs/${identity.org_id}/health`)
      .then(res => res.ok ? res.json() : null)
      .then(data => {
        if (data) {
          setServices(data.services || []);
          // Map integration icons
          const integrationsWithIcons = (data.integrations || []).map((int: any) => ({
            ...int,
            icon: getIntegrationIcon(int.name),
          }));
          setIntegrations(integrationsWithIcons);
        }
      })
      .catch(err => console.error('Failed to load health:', err));
  }, [identity?.org_id]);

  // Helper to map integration names to icons
  const getIntegrationIcon = (name: string) => {
    const iconMap: Record<string, any> = {
      slack: MessageSquare,
      openai: Zap,
      github: Github,
      kubernetes: Cloud,
      aws: Cloud,
      datadog: BarChart3,
      grafana: BarChart3,
      pagerduty: AlertCircle,
      coralogix: BarChart3,
    };
    return iconMap[name.toLowerCase()] || Settings;
  };

  const formatRelativeTime = (timestamp: string) => {
    const now = Date.now();
    const then = new Date(timestamp).getTime();
    const diff = now - then;
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(diff / 3600000);
    const days = Math.floor(diff / 86400000);

    if (minutes < 1) return 'just now';
    if (minutes < 60) return `${minutes}m ago`;
    if (hours < 24) return `${hours}h ago`;
    return `${days}d ago`;
  };

  const formatDuration = (seconds: number | null) => {
    if (seconds === null) return 'N/A';
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m`;
    const hours = Math.floor(minutes / 60);
    const remainingMinutes = minutes % 60;
    return `${hours}h ${remainingMinutes}m`;
  };

  const getActivityIcon = (type: ActivityItem['type']) => {
    switch (type) {
      case 'run':
        return <Bot className="w-4 h-4" />;
      case 'config':
        return <Settings className="w-4 h-4" />;
      case 'token':
        return <Key className="w-4 h-4" />;
      case 'template':
        return <FileText className="w-4 h-4" />;
    }
  };

  const getActivityStatusIcon = (status: ActivityItem['status']) => {
    switch (status) {
      case 'success':
        return <CheckCircle className="w-4 h-4 text-green-500" />;
      case 'failed':
        return <XCircle className="w-4 h-4 text-red-500" />;
      case 'pending':
        return <Clock className="w-4 h-4 text-yellow-500" />;
      case 'info':
        return <Activity className="w-4 h-4 text-gray-500" />;
    }
  };

  const getServiceStatusBadge = (status: ServiceHealth['status']) => {
    switch (status) {
      case 'healthy':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400">
            <CheckCircle className="w-3 h-3" />
            Healthy
          </span>
        );
      case 'degraded':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400">
            <AlertCircle className="w-3 h-3" />
            Degraded
          </span>
        );
      case 'down':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400">
            <XCircle className="w-3 h-3" />
            Down
          </span>
        );
    }
  };

  const getIntegrationStatusBadge = (status: IntegrationHealth['status']) => {
    switch (status) {
      case 'connected':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400">
            <CheckCircle className="w-3 h-3" />
            Connected
          </span>
        );
      case 'error':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400">
            <XCircle className="w-3 h-3" />
            Error
          </span>
        );
      case 'not_configured':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-400">
            <AlertCircle className="w-3 h-3" />
            Not Configured
          </span>
        );
    }
  };

  const totalPending = pending.remediations + pending.configChanges + pending.expiringTokens;

  const handleWelcomeRunAgent = () => {
    markWelcomeSeen();
    markFirstAgentRunCompleted();
    setShowWelcomeModal(false);
  };

  const handleWelcomeSkip = () => {
    markWelcomeSeen();
    setShowWelcomeModal(false);
  };

  return (
    <RequireRole role="admin" fallbackHref="/">
      {/* Onboarding Modals */}
      {showWelcomeModal && (
        <QuickStartWizard
          onClose={() => setShowWelcomeModal(false)}
          onRunAgent={handleWelcomeRunAgent}
          onSkip={handleWelcomeSkip}
        />
      )}

      <div className="p-8 max-w-7xl mx-auto space-y-8">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <ShieldCheck className="w-7 h-7 text-gray-500" />
            <div>
              <h1 className="text-2xl font-semibold text-gray-900 dark:text-white">Admin Dashboard</h1>
              <p className="text-sm text-gray-500">Monitor organization health and activity</p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <div className="text-xs text-gray-500 text-right">
              <div>
                Signed in as: <span className="font-mono">{identity?.auth_kind || 'unknown'}</span>
              </div>
              <div className="mt-1">
                Organization: <span className="font-mono">{identity?.org_id || '—'}</span>
              </div>
            </div>
          </div>
        </div>

        {error && (
          <div className="text-sm text-red-600 bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/40 rounded-lg p-3">
            {error}
          </div>
        )}

        {/* Organization Overview Stats */}
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Organization Overview</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
            <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-5 shadow-sm">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-gray-500">Total Teams</div>
                  <div className="text-3xl font-bold text-gray-900 dark:text-white mt-1">
                    {stats?.totalTeams || 0}
                  </div>
                </div>
                <Users className="w-10 h-10 text-gray-400 opacity-80" />
              </div>
            </div>

            <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-5 shadow-sm">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-gray-500">Active Teams (7d)</div>
                  <div className="text-3xl font-bold text-gray-900 dark:text-white mt-1">
                    {stats?.activeTeams || 0}
                  </div>
                </div>
                <Activity className="w-10 h-10 text-gray-400 opacity-80" />
              </div>
            </div>

            <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-5 shadow-sm">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-gray-500">Agent Runs (30d)</div>
                  <div className="text-3xl font-bold text-gray-900 dark:text-white mt-1">
                    {stats?.totalRuns || 0}
                  </div>
                </div>
                <Bot className="w-10 h-10 text-gray-400 opacity-80" />
              </div>
            </div>

            <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-5 shadow-sm">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-gray-500">Success Rate</div>
                  <div className="text-3xl font-bold text-gray-900 dark:text-white mt-1">
                    {stats?.successRate || 0}%
                  </div>
                </div>
                <TrendingUp className="w-10 h-10 text-gray-400 opacity-80" />
              </div>
            </div>

            <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-5 shadow-sm">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-gray-500">MTTD (Agent Run Duration)</div>
                  {stats?.durationPercentiles ? (
                    <div>
                      <div className="text-3xl font-bold text-gray-900 dark:text-white mt-1">
                        {stats.durationPercentiles.p50}s
                      </div>
                      <div className="text-xs text-gray-500 mt-1">
                        P50 | P95: {stats.durationPercentiles.p95}s | P99: {stats.durationPercentiles.p99}s
                      </div>
                    </div>
                  ) : (
                    <div className="text-3xl font-bold text-gray-400 dark:text-gray-600 mt-1">—</div>
                  )}
                </div>
                <Clock className="w-10 h-10 text-cyan-500 opacity-80" />
              </div>
            </div>
          </div>
        </div>

        {/* Main Content Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Activity Feed - Takes 2 columns */}
          <div className="lg:col-span-2">
            <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl shadow-sm">
              <div className="p-5 border-b border-gray-200 dark:border-gray-800">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Recent Activity</h2>
                  <button className="text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 flex items-center gap-1">
                    <RefreshCw className="w-3 h-3" />
                    Refresh
                  </button>
                </div>
              </div>
              <div className="divide-y divide-gray-200 dark:divide-gray-800">
                {activities.length === 0 && (
                  <div className="p-8 text-center text-sm text-gray-500">No recent activity</div>
                )}
                {activities.map((activity) => (
                  <div key={activity.id} className="p-4 hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">
                    <div className="flex items-start gap-3">
                      <div className="flex-shrink-0 mt-0.5">
                        <div className="p-2 rounded-lg bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300">
                          {getActivityIcon(activity.type)}
                        </div>
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          {getActivityStatusIcon(activity.status)}
                          <p className="text-sm text-gray-900 dark:text-white">{activity.description}</p>
                        </div>
                        <div className="flex items-center gap-2 mt-1">
                          <span className="text-xs text-gray-500">{formatRelativeTime(activity.timestamp)}</span>
                          {activity.teamName && (
                            <>
                              <span className="text-xs text-gray-400">•</span>
                              <span className="text-xs text-gray-500">{activity.teamName}</span>
                            </>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Right Column - Pending Items + Health Status */}
          <div className="space-y-6">
            {/* Pending Items */}
            <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl shadow-sm">
              <div className="p-5 border-b border-gray-200 dark:border-gray-800">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Pending Items</h2>
                  {totalPending > 0 && (
                    <span className="px-2 py-1 rounded-full text-xs font-medium bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400">
                      {totalPending}
                    </span>
                  )}
                </div>
              </div>
              <div className="p-5 space-y-3">
                <Link
                  href="/admin/agent-run"
                  className="block p-3 rounded-lg border border-gray-200 dark:border-gray-800 hover:border-orange-300 dark:hover:border-orange-700 transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <AlertCircle className="w-4 h-4 text-gray-600" />
                      <span className="text-sm font-medium text-gray-900 dark:text-white">Remediations</span>
                    </div>
                    {pending.remediations > 0 && (
                      <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400">
                        {pending.remediations}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-500 mt-1">Awaiting approval</p>
                </Link>

                <Link
                  href="/admin/org-tree"
                  className="block p-3 rounded-lg border border-gray-200 dark:border-gray-800 hover:border-orange-300 dark:hover:border-orange-700 transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Settings className="w-4 h-4 text-gray-600" />
                      <span className="text-sm font-medium text-gray-900 dark:text-white">Config Changes</span>
                    </div>
                    {pending.configChanges > 0 && (
                      <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-400">
                        {pending.configChanges}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-500 mt-1">Awaiting approval</p>
                </Link>

                <Link
                  href="/admin/token-management"
                  className="block p-3 rounded-lg border border-gray-200 dark:border-gray-800 hover:border-orange-300 dark:hover:border-orange-700 transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Clock className="w-4 h-4 text-gray-600" />
                      <span className="text-sm font-medium text-gray-900 dark:text-white">Expiring Tokens</span>
                    </div>
                    {pending.expiringTokens > 0 && (
                      <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400">
                        {pending.expiringTokens}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-500 mt-1">Expiring within 7 days</p>
                </Link>
              </div>
            </div>

            {/* System Health */}
            <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl shadow-sm">
              <div className="p-5 border-b border-gray-200 dark:border-gray-800">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">System Health</h2>
              </div>
              <div className="p-5 space-y-4">
                <div>
                  <div className="text-xs font-medium text-gray-500 uppercase mb-2">Services</div>
                  <div className="space-y-2">
                    {services.map((service) => (
                      <div key={service.name} className="flex items-center justify-between">
                        <span className="text-sm text-gray-700 dark:text-gray-300">{service.name}</span>
                        {getServiceStatusBadge(service.status)}
                      </div>
                    ))}
                  </div>
                </div>

                <div className="border-t border-gray-200 dark:border-gray-800 pt-4">
                  <div className="text-xs font-medium text-gray-500 uppercase mb-2">Integrations</div>
                  <div className="space-y-2">
                    {integrations.map((integration) => {
                      const Icon = integration.icon;
                      return (
                        <div key={integration.name} className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <Icon className="w-4 h-4 text-gray-500" />
                            <span className="text-sm text-gray-700 dark:text-gray-300">{integration.name}</span>
                          </div>
                          {getIntegrationStatusBadge(integration.status)}
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Team Performance Breakdown */}
        {stats?.teams && stats.teams.length > 0 && (
          <div>
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Team Performance (Last 30 Days)</h2>
            <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl shadow-sm overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Team
                      </th>
                      <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Total Runs
                      </th>
                      <th className="px-6 py-3 text-center text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Trend
                      </th>
                      <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Success Rate
                      </th>
                      <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        MTTD
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Most Used Agent
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Last Run
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                    {stats.teams.map((team) => (
                      <tr key={team.team_node_id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="flex items-center">
                            <div className="w-8 h-8 rounded-lg bg-gray-100 dark:bg-gray-800 flex items-center justify-center mr-3">
                              <Users className="w-4 h-4 text-gray-600 dark:text-gray-400" />
                            </div>
                            <div>
                              <div className="text-sm font-medium text-gray-900 dark:text-white">
                                {team.team_name}
                              </div>
                              <div className="text-xs text-gray-500 dark:text-gray-400">
                                {team.team_node_id}
                              </div>
                            </div>
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-right">
                          <div className="text-sm font-medium text-gray-900 dark:text-white">
                            {team.total_runs}
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-center">
                          <div className="flex items-center justify-center gap-1">
                            {team.trend === 'up' && (
                              <span className="inline-flex items-center text-green-600 dark:text-green-400" title={`${team.runs_this_week} runs this week vs ${team.runs_prev_week} last week`}>
                                <TrendingUp className="w-4 h-4" />
                              </span>
                            )}
                            {team.trend === 'down' && (
                              <span className="inline-flex items-center text-red-600 dark:text-red-400" title={`${team.runs_this_week} runs this week vs ${team.runs_prev_week} last week`}>
                                <Activity className="w-4 h-4 rotate-180" />
                              </span>
                            )}
                            {team.trend === 'stable' && (
                              <span className="inline-flex items-center text-gray-500 dark:text-gray-400" title={`${team.runs_this_week} runs this week vs ${team.runs_prev_week} last week`}>
                                <Activity className="w-4 h-4" />
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-right">
                          <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                            team.success_rate >= 90
                              ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
                              : team.success_rate >= 70
                              ? 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400'
                              : 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400'
                          }`}>
                            {team.success_rate}%
                          </span>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-right">
                          {team.duration_percentiles ? (
                            <div>
                              <div className="text-sm font-medium text-gray-900 dark:text-white">
                                P50: {team.duration_percentiles.p50}s
                              </div>
                              <div className="text-xs text-gray-500">
                                P95: {team.duration_percentiles.p95}s | P99: {team.duration_percentiles.p99}s
                              </div>
                            </div>
                          ) : (
                            <div className="text-sm text-gray-700 dark:text-gray-300">
                              {formatDuration(team.avg_duration_seconds)}
                            </div>
                          )}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-left">
                          {team.most_used_agent ? (
                            <div className="flex items-center gap-2">
                              <Bot className="w-4 h-4 text-gray-500" />
                              <span className="text-sm text-gray-700 dark:text-gray-300">
                                {team.most_used_agent}
                              </span>
                            </div>
                          ) : (
                            <span className="text-sm text-gray-400">—</span>
                          )}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-left">
                          <div className="text-sm text-gray-500 dark:text-gray-400">
                            {team.last_run_at ? formatRelativeTime(team.last_run_at) : 'Never'}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* Quick Actions */}
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Quick Actions</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            <Link
              href="/admin/org-tree"
              className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-5 shadow-sm hover:border-orange-300 dark:hover:border-orange-700 transition-colors group"
            >
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-lg bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 group-hover:bg-gray-200 dark:group-hover:bg-gray-700 transition-colors">
                  <Users className="w-5 h-5" />
                </div>
                <div>
                  <div className="font-medium text-gray-900 dark:text-white">Add New Team</div>
                  <div className="text-xs text-gray-500">Create team in org tree</div>
                </div>
              </div>
            </Link>

            <Link
              href="/admin/token-management"
              className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-5 shadow-sm hover:border-orange-300 dark:hover:border-orange-700 transition-colors group"
            >
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-lg bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 group-hover:bg-gray-200 dark:group-hover:bg-gray-700 transition-colors">
                  <Key className="w-5 h-5" />
                </div>
                <div>
                  <div className="font-medium text-gray-900 dark:text-white">Issue Token</div>
                  <div className="text-xs text-gray-500">Generate API token</div>
                </div>
              </div>
            </Link>

            <Link
              href="/admin/audit"
              className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-5 shadow-sm hover:border-orange-300 dark:hover:border-orange-700 transition-colors group"
            >
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-lg bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 group-hover:bg-gray-200 dark:group-hover:bg-gray-700 transition-colors">
                  <FileText className="w-5 h-5" />
                </div>
                <div>
                  <div className="font-medium text-gray-900 dark:text-white">View Audit Log</div>
                  <div className="text-xs text-gray-500">Review admin actions</div>
                </div>
              </div>
            </Link>
          </div>
        </div>
      </div>
    </RequireRole>
  );
}
