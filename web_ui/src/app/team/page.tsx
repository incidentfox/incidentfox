'use client';

import Link from 'next/link';
import { RequireRole } from '@/components/RequireRole';
import { useIdentity } from '@/lib/useIdentity';
import { useOnboarding } from '@/lib/useOnboarding';
import { QuickStartWizard } from '@/components/onboarding/QuickStartWizard';
import {
  Bot,
  Activity,
  TrendingUp,
  Clock,
  CheckCircle,
  XCircle,
  Settings,
  BookOpen,
  RefreshCw,
  Upload,
  Wrench,
  LayoutTemplate,
  GitPullRequest,
} from 'lucide-react';
import { useState, useEffect } from 'react';

interface TeamStats {
  totalRuns: number;
  successRate: number;
  avgMttdSeconds: number | null;
  runsThisWeek: number;
  runsPrevWeek: number;
  trend: 'up' | 'down' | 'stable';
}

interface ActivityItem {
  id: string;
  type: 'run' | 'config' | 'knowledge' | 'template';
  description: string;
  timestamp: string;
  status: 'success' | 'failed' | 'pending' | 'info';
}

interface PendingItems {
  configChanges: number;
  knowledgeChanges: number;
}

export default function TeamDashboardPage() {
  const { identity } = useIdentity();
  const [stats, setStats] = useState<TeamStats | null>(null);
  const [activities, setActivities] = useState<ActivityItem[]>([]);
  const [pending, setPending] = useState<PendingItems>({ configChanges: 0, knowledgeChanges: 0 });

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
    // Fetch team stats
    fetch('/api/team/stats')
      .then(res => res.ok ? res.json() : null)
      .then(data => {
        console.log('Stats API response:', data);
        data && setStats(data);
      })
      .catch(err => console.error('Failed to load stats:', err));

    // Fetch recent activity
    fetch('/api/team/activity?limit=10')
      .then(res => res.ok ? res.json() : null)
      .then(data => data && setActivities(data.activities || []))
      .catch(err => console.error('Failed to load activity:', err));

    // Fetch pending items
    fetch('/api/team/pending')
      .then(res => res.ok ? res.json() : null)
      .then(data => data && setPending(data))
      .catch(err => console.error('Failed to load pending items:', err));
  }, []);

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

  const getActivityIcon = (type: ActivityItem['type']) => {
    switch (type) {
      case 'run':
        return <Bot className="w-4 h-4" />;
      case 'config':
        return <Settings className="w-4 h-4" />;
      case 'knowledge':
        return <BookOpen className="w-4 h-4" />;
      case 'template':
        return <LayoutTemplate className="w-4 h-4" />;
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

  const totalPending = pending.configChanges + pending.knowledgeChanges;

  const handleWelcomeRunAgent = () => {
    markWelcomeSeen();
    markFirstAgentRunCompleted();
    setShowWelcomeModal(false);
    // Navigate to agent-runs page where they can run agents
    window.location.href = '/team/agent-runs';
  };

  const handleWelcomeSkip = () => {
    markWelcomeSeen();
    setShowWelcomeModal(false);
  };

  return (
    <RequireRole role="team" fallbackHref="/">
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
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-orange-500 to-amber-500 flex items-center justify-center"><Bot className="w-5 h-5 text-white" /></div>
            <div>
              <h1 className="text-2xl font-semibold text-gray-900 dark:text-white">Team Dashboard</h1>
              <p className="text-sm text-gray-500">Monitor your AI agents and team activity</p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <div className="text-xs text-gray-500 text-right">
              <div>
                Team: <span className="font-mono">{identity?.team_node_id || identity?.org_id || 'unknown'}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Team Overview Stats */}
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Team Overview</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-5 shadow-sm">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-gray-500">Total Agent Runs</div>
                  <div className="text-3xl font-bold text-gray-900 dark:text-white mt-1">
                    {stats?.totalRuns || 0}
                  </div>
                  {stats && stats.trend !== 'stable' && (
                    <div className="flex items-center gap-1 mt-1">
                      {stats.trend === 'up' ? (
                        <TrendingUp className="w-3 h-3 text-green-500" />
                      ) : (
                        <Activity className="w-3 h-3 text-red-500 rotate-180" />
                      )}
                      <span className={`text-xs ${stats.trend === 'up' ? 'text-green-600' : 'text-red-600'}`}>
                        {stats.runsThisWeek} this week
                      </span>
                    </div>
                  )}
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
                <TrendingUp className="w-10 h-10 text-green-500 opacity-80" />
              </div>
            </div>

            <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-5 shadow-sm">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-gray-500">Avg MTTD</div>
                  <div className="text-3xl font-bold text-gray-900 dark:text-white mt-1">
                    {stats?.avgMttdSeconds != null
                      ? stats.avgMttdSeconds < 60
                        ? `${Math.round(stats.avgMttdSeconds)}s`
                        : stats.avgMttdSeconds < 3600
                        ? `${Math.round(stats.avgMttdSeconds / 60)}m`
                        : `${(stats.avgMttdSeconds / 3600).toFixed(1)}h`
                      : 'N/A'}
                  </div>
                  <div className="text-xs text-gray-400 mt-1">Last 30 days</div>
                </div>
                <Clock className="w-10 h-10 text-gray-400 opacity-80" />
              </div>
            </div>
          </div>
        </div>

        {/* Main Content Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Activity Feed - Takes 2 columns, height matches right column */}
          <div className="lg:col-span-2">
            <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl shadow-sm flex flex-col max-h-[526px]">
              <div className="p-5 border-b border-gray-200 dark:border-gray-800 flex-shrink-0">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Recent Activity</h2>
                  <button className="text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 flex items-center gap-1">
                    <RefreshCw className="w-3 h-3" />
                    Refresh
                  </button>
                </div>
              </div>
              <div className="divide-y divide-gray-200 dark:divide-gray-800 overflow-y-auto flex-1">
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
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Right Column - Pending Items + Quick Actions */}
          <div className="flex flex-col gap-4">
            {/* Pending Items */}
            <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl shadow-sm">
              <div className="p-4 border-b border-gray-200 dark:border-gray-800">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Pending Items</h2>
                  {totalPending > 0 && (
                    <span className="px-2 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-400">
                      {totalPending}
                    </span>
                  )}
                </div>
              </div>
              <div className="p-4 space-y-2">
                <Link
                  href="/team/pending-changes"
                  className="block p-2.5 rounded-lg border border-gray-200 dark:border-gray-800 hover:border-gray-400 dark:hover:border-gray-600 transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <GitPullRequest className="w-4 h-4 text-gray-500" />
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
                  href="/team/knowledge"
                  className="block p-2.5 rounded-lg border border-gray-200 dark:border-gray-800 hover:border-gray-400 dark:hover:border-gray-600 transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <BookOpen className="w-4 h-4 text-gray-500" />
                      <span className="text-sm font-medium text-gray-900 dark:text-white">Knowledge Changes</span>
                    </div>
                    {pending.knowledgeChanges > 0 && (
                      <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400">
                        {pending.knowledgeChanges}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-500 mt-1">Proposed changes</p>
                </Link>
              </div>
            </div>

            {/* Quick Actions */}
            <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl shadow-sm">
              <div className="p-4 border-b border-gray-200 dark:border-gray-800">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Quick Actions</h2>
              </div>
              <div className="p-4 space-y-2">
                <Link
                  href="/team/knowledge"
                  className="block p-2.5 rounded-lg border border-gray-200 dark:border-gray-800 hover:border-gray-400 dark:hover:border-gray-600 transition-colors group"
                >
                  <div className="flex items-center gap-3">
                    <div className="p-1.5 rounded-lg bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 group-hover:bg-gray-200 dark:group-hover:bg-gray-700 transition-colors">
                      <Upload className="w-4 h-4" />
                    </div>
                    <div>
                      <div className="text-sm font-medium text-gray-900 dark:text-white">Upload Knowledge</div>
                      <div className="text-xs text-gray-500">Add documentation</div>
                    </div>
                  </div>
                </Link>

                <Link
                  href="/team/agents"
                  className="block p-2.5 rounded-lg border border-gray-200 dark:border-gray-800 hover:border-gray-400 dark:hover:border-gray-600 transition-colors group"
                >
                  <div className="flex items-center gap-3">
                    <div className="p-1.5 rounded-lg bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 group-hover:bg-gray-200 dark:group-hover:bg-gray-700 transition-colors">
                      <Wrench className="w-4 h-4" />
                    </div>
                    <div>
                      <div className="text-sm font-medium text-gray-900 dark:text-white">Configure Agents</div>
                      <div className="text-xs text-gray-500">Edit agent topology</div>
                    </div>
                  </div>
                </Link>

                <Link
                  href="/team/templates"
                  className="block p-2.5 rounded-lg border border-gray-200 dark:border-gray-800 hover:border-gray-400 dark:hover:border-gray-600 transition-colors group"
                >
                  <div className="flex items-center gap-3">
                    <div className="p-1.5 rounded-lg bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 group-hover:bg-gray-200 dark:group-hover:bg-gray-700 transition-colors">
                      <LayoutTemplate className="w-4 h-4" />
                    </div>
                    <div>
                      <div className="text-sm font-medium text-gray-900 dark:text-white">View Templates</div>
                      <div className="text-xs text-gray-500">Browse presets</div>
                    </div>
                  </div>
                </Link>
              </div>
            </div>
          </div>
        </div>
      </div>
    </RequireRole>
  );
}
