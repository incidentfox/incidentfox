'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useIdentity } from '@/lib/useIdentity';
import { apiFetch } from '@/lib/apiClient';
import { HelpTip } from '@/components/onboarding/HelpTip';
import {
  Settings,
  Moon,
  Sun,
  RefreshCcw,
  Bot,
  ChevronRight,
  AlertTriangle,
  Shield,
  KeyRound,
  Activity,
  ExternalLink,
  Radio,
  Bell,
  Plus,
  X,
  Check,
  Zap,
  Clock,
  ToggleLeft,
  ToggleRight,
  Network,
  Loader2,
  Link2,
  Route,
  MessageSquare,
  Github,
  Webhook,
  Tag,
  Server,
  Info
} from 'lucide-react';

// Tab type
type SettingsTab = 'general' | 'routing' | 'notifications' | 'telemetry' | 'features' | 'advanced';

// Feature configs
interface IngestorSourceConfig {
  slack: {
    enabled: boolean;
    channels: string[];  // Channel names like "#incidents", "#oncall"
  };
  confluence: {
    enabled: boolean;
    base_url: string;    // e.g., "https://company.atlassian.net"
    space_keys: string[]; // Space keys to include
  };
  gdocs: {
    enabled: boolean;
    folder_ids: string[]; // Optional folder IDs to filter
  };
  agent_traces: {
    enabled: boolean;
  };
}

interface PipelineConfig {
  enabled: boolean;
  schedule: string;
  ingestors: IngestorSourceConfig;
}

interface DependencyDiscoveryConfig {
  enabled: boolean;
  schedule: string;
  sources: {
    new_relic: boolean;
    cloudwatch: boolean;
    prometheus: boolean;
    datadog: boolean;
  };
}

interface CorrelationConfig {
  enabled: boolean;
  temporal_window_seconds: number;
  semantic_threshold: number;
}

// Routing configuration - determines which webhooks route to this team
interface RoutingConfig {
  slack_channel_ids: string[];
  github_repos: string[];
  pagerduty_service_ids: string[];
  incidentio_team_ids: string[];
  incidentio_alert_source_ids: string[];
  coralogix_team_names: string[];
  services: string[];
}

// Admin sub-pages (shown as links in sidebar for admins)
interface AdminLink {
  name: string;
  href: string;
  icon: any;
  description: string;
}

const adminLinks: AdminLink[] = [
  { name: 'Security Policies', href: '/admin/security-policies', icon: Shield, description: 'Token policies and guardrails' },
  { name: 'SSO', href: '/admin/sso', icon: KeyRound, description: 'Single sign-on configuration' },
  { name: 'Audit Log', href: '/admin/audit', icon: Activity, description: 'View all activity logs' },
];

export default function SettingsPage() {
  const router = useRouter();
  const { identity, loading: identityLoading } = useIdentity();
  const [activeTab, setActiveTab] = useState<SettingsTab>('general');
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');

  // Telemetry opt-in/out
  const [telemetryEnabled, setTelemetryEnabled] = useState(true);
  const [telemetryLoading, setTelemetryLoading] = useState(false);

  // Output configuration (Delivery & Notifications)
  const [outputConfig, setOutputConfig] = useState<{
    default_destinations: Array<{
      type: string;
      channel_id?: string;
      channel_name?: string;
      repo?: string;
      config?: any;
    }>;
    trigger_overrides: { [key: string]: string };
  }>({ default_destinations: [], trigger_overrides: {} });
  const [outputConfigLoading, setOutputConfigLoading] = useState(false);
  const [showAddDestination, setShowAddDestination] = useState(false);
  const [newDestinationType, setNewDestinationType] = useState('slack');
  const [newDestinationConfig, setNewDestinationConfig] = useState({ channel_name: '', channel_id: '' });

  // Agent run state (advanced)
  const [agentPrompt, setAgentPrompt] = useState('');
  const [agentRunning, setAgentRunning] = useState(false);
  const [agentResult, setAgentResult] = useState<any>(null);

  // Feature configs (AI Pipeline & Dependency Discovery)
  const [pipelineConfig, setPipelineConfig] = useState<PipelineConfig>({
    enabled: false,
    schedule: '0 2 * * *',
    ingestors: {
      slack: { enabled: true, channels: [] },
      confluence: { enabled: false, base_url: '', space_keys: [] },
      gdocs: { enabled: false, folder_ids: [] },
      agent_traces: { enabled: false },
    },
  });
  const [dependencyConfig, setDependencyConfig] = useState<DependencyDiscoveryConfig>({
    enabled: false,
    schedule: '0 */2 * * *',
    sources: {
      new_relic: true,
      cloudwatch: false,
      prometheus: false,
      datadog: false,
    },
  });
  const [correlationConfig, setCorrelationConfig] = useState<CorrelationConfig>({
    enabled: false,
    temporal_window_seconds: 300,
    semantic_threshold: 0.75,
  });
  const [featuresLoading, setFeaturesLoading] = useState(false);
  const [featuresSaving, setFeaturesSaving] = useState(false);
  const [syncingCronJobs, setSyncingCronJobs] = useState(false);

  // Routing configuration state
  const [routingConfig, setRoutingConfig] = useState<RoutingConfig>({
    slack_channel_ids: [],
    github_repos: [],
    pagerduty_service_ids: [],
    incidentio_team_ids: [],
    incidentio_alert_source_ids: [],
    coralogix_team_names: [],
    services: [],
  });
  const [routingLoading, setRoutingLoading] = useState(false);
  const [routingSaving, setRoutingSaving] = useState(false);
  // Track which routing field is being edited (for add input)
  const [editingRoutingField, setEditingRoutingField] = useState<keyof RoutingConfig | null>(null);
  const [newRoutingValue, setNewRoutingValue] = useState('');

  const isAdmin = identity?.role === 'admin';

  // Theme toggle
  useEffect(() => {
    const stored = localStorage.getItem('theme') || 'dark';
    setTheme(stored as 'dark' | 'light');
    if (stored === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, []);

  const toggleTheme = () => {
    const newTheme = theme === 'dark' ? 'light' : 'dark';
    setTheme(newTheme);
    localStorage.setItem('theme', newTheme);
    if (newTheme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  };

  // Load telemetry settings on mount
  useEffect(() => {
    const loadTelemetry = async () => {
      try {
        const res = await apiFetch('/api/config/me/org-settings');
        const data = await res.json();
        setTelemetryEnabled(data.telemetry_enabled);
      } catch (e) {
        console.error('Failed to load telemetry settings', e);
      }
    };
    loadTelemetry();
  }, []);

  // Toggle telemetry
  const toggleTelemetry = async () => {
    setTelemetryLoading(true);
    try {
      const newValue = !telemetryEnabled;
      const res = await apiFetch('/api/config/me/org-settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ telemetry_enabled: newValue }),
      });
      if (!res.ok) throw new Error('Failed to update');
      setTelemetryEnabled(newValue);
    } catch (e: any) {
      console.error('Failed to update telemetry', e);
      alert('Failed to update telemetry preference');
    } finally {
      setTelemetryLoading(false);
    }
  };

  // Load output config on mount
  useEffect(() => {
    const loadOutputConfig = async () => {
      try {
        const res = await apiFetch('/api/v1/team/output-config');
        const data = await res.json();
        setOutputConfig(data);
      } catch (e) {
        console.error('Failed to load output config', e);
      }
    };
    loadOutputConfig();
  }, []);

  // Save output config
  const saveOutputConfig = async () => {
    setOutputConfigLoading(true);
    try {
      const res = await apiFetch('/api/v1/team/output-config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(outputConfig),
      });
      if (!res.ok) throw new Error('Failed to update');
      const data = await res.json();
      setOutputConfig(data);
      alert('Output configuration saved successfully!');
    } catch (e: any) {
      console.error('Failed to save output config', e);
      alert('Failed to save output configuration');
    } finally {
      setOutputConfigLoading(false);
    }
  };

  // Add destination
  const addDestination = () => {
    const newDest: any = { type: newDestinationType };
    if (newDestinationType === 'slack') {
      newDest.channel_id = newDestinationConfig.channel_id;
      newDest.channel_name = newDestinationConfig.channel_name;
    }
    setOutputConfig({
      ...outputConfig,
      default_destinations: [...outputConfig.default_destinations, newDest],
    });
    setShowAddDestination(false);
    setNewDestinationConfig({ channel_name: '', channel_id: '' });
  };

  // Remove destination
  const removeDestination = (index: number) => {
    setOutputConfig({
      ...outputConfig,
      default_destinations: outputConfig.default_destinations.filter((_, i) => i !== index),
    });
  };

  // Run agent (advanced)
  const runAgent = async () => {
    if (!agentPrompt.trim()) return;
    setAgentRunning(true);
    setAgentResult(null);
    try {
      const res = await apiFetch('/api/orchestrator/agents/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: agentPrompt,
          agent_name: 'planner',
          max_turns: 50,
          timeout: 180,
        }),
      });
      const data = await res.json();
      setAgentResult(data);
    } catch (e: any) {
      setAgentResult({ error: e?.message || 'Failed to run agent' });
    } finally {
      setAgentRunning(false);
    }
  };

  // Sign out handler
  const signOut = async () => {
    try {
      // Call the logout API to clear the httpOnly session cookie
      await fetch('/api/session/logout', { method: 'POST' });
    } catch (e) {
      console.error('Logout API failed', e);
    }
    // Also clear any localStorage tokens
    localStorage.removeItem('incidentfox_token');
    // Force reload to clear React state and redirect to login
    window.location.href = '/';
  };

  // Load feature configs on mount
  useEffect(() => {
    const loadFeatureConfigs = async () => {
      setFeaturesLoading(true);
      try {
        const res = await apiFetch('/api/config/me');
        if (res.ok) {
          const data = await res.json();
          const config = data.effective_config || data;

          // Extract ai_pipeline config
          if (config.ai_pipeline) {
            const ingestors = config.ai_pipeline.ingestors || {};
            // Handle both old boolean format and new object format
            const parseIngestor = (key: string, defaultEnabled: boolean) => {
              const val = ingestors[key];
              if (typeof val === 'boolean') {
                // Legacy format - convert to new structure
                return { enabled: val, channels: [], base_url: '', space_keys: [], folder_ids: [] };
              }
              return val || { enabled: defaultEnabled };
            };

            setPipelineConfig({
              enabled: config.ai_pipeline.enabled ?? false,
              schedule: config.ai_pipeline.schedule ?? '0 2 * * *',
              ingestors: {
                slack: {
                  enabled: parseIngestor('slack', true).enabled ?? true,
                  channels: ingestors.slack?.channels || [],
                },
                confluence: {
                  enabled: parseIngestor('confluence', false).enabled ?? false,
                  base_url: ingestors.confluence?.base_url || '',
                  space_keys: ingestors.confluence?.space_keys || [],
                },
                gdocs: {
                  enabled: parseIngestor('gdocs', false).enabled ?? false,
                  folder_ids: ingestors.gdocs?.folder_ids || [],
                },
                agent_traces: {
                  enabled: parseIngestor('agent_traces', false).enabled ?? false,
                },
              },
            });
          }

          // Extract dependency_discovery config
          if (config.dependency_discovery) {
            setDependencyConfig({
              enabled: config.dependency_discovery.enabled ?? false,
              schedule: config.dependency_discovery.schedule ?? '0 */2 * * *',
              sources: {
                new_relic: config.dependency_discovery.sources?.new_relic ?? true,
                cloudwatch: config.dependency_discovery.sources?.cloudwatch ?? false,
                prometheus: config.dependency_discovery.sources?.prometheus ?? false,
                datadog: config.dependency_discovery.sources?.datadog ?? false,
              },
            });
          }

          // Extract correlation config
          if (config.correlation) {
            setCorrelationConfig({
              enabled: config.correlation.enabled ?? false,
              temporal_window_seconds: config.correlation.temporal_window_seconds ?? 300,
              semantic_threshold: config.correlation.semantic_threshold ?? 0.75,
            });
          }

          // Extract routing config
          if (config.routing) {
            setRoutingConfig({
              slack_channel_ids: config.routing.slack_channel_ids || [],
              github_repos: config.routing.github_repos || [],
              pagerduty_service_ids: config.routing.pagerduty_service_ids || [],
              incidentio_team_ids: config.routing.incidentio_team_ids || [],
              incidentio_alert_source_ids: config.routing.incidentio_alert_source_ids || [],
              coralogix_team_names: config.routing.coralogix_team_names || [],
              services: config.routing.services || [],
            });
          }
        }
      } catch (e) {
        console.error('Failed to load feature configs', e);
      } finally {
        setFeaturesLoading(false);
        setRoutingLoading(false);
      }
    };
    setRoutingLoading(true);
    loadFeatureConfigs();
  }, []);

  // Save feature configs
  const saveFeatureConfigs = async () => {
    setFeaturesSaving(true);
    try {
      const patch = {
        ai_pipeline: {
          enabled: pipelineConfig.enabled,
          schedule: pipelineConfig.schedule,
          ingestors: pipelineConfig.ingestors,
        },
        dependency_discovery: {
          enabled: dependencyConfig.enabled,
          schedule: dependencyConfig.schedule,
          sources: dependencyConfig.sources,
        },
        correlation: {
          enabled: correlationConfig.enabled,
          temporal_window_seconds: correlationConfig.temporal_window_seconds,
          semantic_threshold: correlationConfig.semantic_threshold,
        },
      };

      const res = await apiFetch('/api/config/me', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      });

      if (!res.ok) throw new Error('Failed to save');
      alert('Feature configuration saved! Click "Apply Changes" to update scheduled jobs.');
    } catch (e: any) {
      console.error('Failed to save feature configs', e);
      alert('Failed to save feature configuration');
    } finally {
      setFeaturesSaving(false);
    }
  };

  // Save routing config
  const saveRoutingConfig = async () => {
    setRoutingSaving(true);
    try {
      const patch = {
        routing: routingConfig,
      };

      const res = await apiFetch('/api/config/me', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      });

      if (!res.ok) throw new Error('Failed to save');
      alert('Routing configuration saved successfully!');
    } catch (e: any) {
      console.error('Failed to save routing config', e);
      alert('Failed to save routing configuration');
    } finally {
      setRoutingSaving(false);
    }
  };

  // Add a routing identifier value
  const addRoutingValue = (field: keyof RoutingConfig) => {
    const trimmed = newRoutingValue.trim();
    if (!trimmed) return;
    if (routingConfig[field].includes(trimmed)) {
      alert('This value already exists');
      return;
    }
    setRoutingConfig({
      ...routingConfig,
      [field]: [...routingConfig[field], trimmed],
    });
    setNewRoutingValue('');
    setEditingRoutingField(null);
  };

  // Remove a routing identifier value
  const removeRoutingValue = (field: keyof RoutingConfig, value: string) => {
    setRoutingConfig({
      ...routingConfig,
      [field]: routingConfig[field].filter((v) => v !== value),
    });
  };

  // Sync CronJobs with current config
  const syncCronJobs = async () => {
    setSyncingCronJobs(true);
    try {
      // Team endpoint uses token auth - no body needed
      const res = await apiFetch('/api/orchestrator/sync-cronjobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });

      const data = await res.json();
      if (data.ok) {
        alert('Scheduled jobs synced successfully!');
      } else {
        alert(`Sync failed: ${data.message || 'Unknown error'}`);
      }
    } catch (e: any) {
      console.error('Failed to sync cronjobs', e);
      alert('Failed to sync scheduled jobs');
    } finally {
      setSyncingCronJobs(false);
    }
  };

  const tabs: { id: SettingsTab; name: string; icon: any; adminOnly?: boolean }[] = [
    { id: 'general', name: 'General', icon: Settings },
    { id: 'routing', name: 'Webhook Routing', icon: Route },
    { id: 'notifications', name: 'Delivery & Notifications', icon: Bell },
    { id: 'telemetry', name: 'Telemetry', icon: Radio },
    { id: 'features', name: 'Advanced Features', icon: Zap },
    { id: 'advanced', name: 'Debug Tools', icon: Bot, adminOnly: true },
  ];

  const filteredTabs = tabs.filter(t => !t.adminOnly || isAdmin);

  return (
    <div className="p-8 max-w-6xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-gray-900 dark:text-white">Settings</h1>
        <p className="text-sm text-gray-500 mt-1">
          {isAdmin ? 'Manage preferences and run ad-hoc agents.' : 'Manage your preferences.'}
        </p>
      </div>

      <div className="flex gap-8">
        {/* Sidebar */}
        <div className="w-56 flex-shrink-0">
          <nav className="space-y-1">
            {filteredTabs.map((tab) => (
            <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`w-full flex items-center gap-3 px-3 py-2.5 text-sm font-medium rounded-lg transition-colors ${
                  activeTab === tab.id
                    ? 'bg-orange-50 text-orange-600 dark:bg-orange-900/20 dark:text-orange-400'
                    : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
              >
                <tab.icon className="w-4 h-4" />
                {tab.name}
                <ChevronRight className={`w-4 h-4 ml-auto transition-transform ${activeTab === tab.id ? 'rotate-90' : ''}`} />
            </button>
          ))}
          
          {/* Admin Links Section */}
          {isAdmin && (
            <>
              <div className="pt-4 mt-4 border-t border-gray-200 dark:border-gray-800">
                <p className="px-3 text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">Admin</p>
              </div>
              {adminLinks.map((link) => (
                <button
                  key={link.href}
                  onClick={() => router.push(link.href)}
                  className="w-full flex items-center gap-3 px-3 py-2.5 text-sm font-medium rounded-lg transition-colors text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
                >
                  <link.icon className="w-4 h-4" />
                  {link.name}
                  <ExternalLink className="w-3 h-3 ml-auto text-gray-400" />
                </button>
              ))}
            </>
          )}
          </nav>
        </div>

        {/* Content */}
        <div className="flex-1">
          {/* General Tab */}
          {activeTab === 'general' && (
            <div className="space-y-6">
              <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-6 shadow-sm">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Preferences</h2>

                <div className="space-y-4">
                  <div className="flex items-center justify-between py-3">
                    <div>
                      <div className="font-medium text-gray-900 dark:text-white">Theme</div>
                      <div className="text-sm text-gray-500">Toggle dark/light mode</div>
                    </div>
                    <button
                      onClick={toggleTheme}
                      className="flex items-center gap-2 px-4 py-2 bg-gray-100 dark:bg-gray-800 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700"
                    >
                      {theme === 'dark' ? <Moon className="w-4 h-4" /> : <Sun className="w-4 h-4" />}
                      {theme === 'dark' ? 'Dark' : 'Light'}
                    </button>
                  </div>
                </div>
              </div>

              <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-6 shadow-sm">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Session</h2>
                
                <div className="space-y-3 text-sm">
                  <div className="flex justify-between py-2">
                    <span className="text-gray-500">Signed in as</span>
                    <span className="font-mono text-gray-900 dark:text-white">{identity?.auth_kind || 'unknown'}</span>
                  </div>
                  <div className="flex justify-between py-2">
                    <span className="text-gray-500">Role</span>
                    <span className="font-medium text-gray-900 dark:text-white">{identity?.role || 'unknown'}</span>
                  </div>
                  {identity?.org_id && (
                    <div className="flex justify-between py-2">
                      <span className="text-gray-500">Organization</span>
                      <span className="font-mono text-gray-900 dark:text-white">{identity.org_id}</span>
                    </div>
                  )}
                </div>

              <button
                  onClick={signOut}
                  className="mt-4 w-full px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700"
              >
                  Sign Out
              </button>
            </div>
          </div>
          )}

          {/* Webhook Routing Tab */}
          {activeTab === 'routing' && (
            <div className="space-y-6">
              <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-6 shadow-sm">
                <div className="flex items-center justify-between mb-6">
                  <div>
                    <h2 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-1">
                      Webhook Routing
                      <HelpTip id="webhook-routing" position="right">
                        <strong>Webhook Routing</strong> determines which incoming webhooks are directed to your team. Configure identifiers from your integrations (Slack channels, GitHub repos, PagerDuty services, etc.) so that alerts and events from those sources are routed to your team's agent.
                      </HelpTip>
                    </h2>
                    <p className="text-sm text-gray-500 mt-1">
                      Configure which webhooks should route to your team
                    </p>
                  </div>
                </div>

                {/* Info Banner */}
                <div className="bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-700 rounded-lg p-4 mb-6">
                  <div className="flex items-start gap-3">
                    <Info className="w-5 h-5 text-gray-500 dark:text-gray-400 flex-shrink-0 mt-0.5" />
                    <div className="text-sm text-gray-600 dark:text-gray-300">
                      <p className="font-medium mb-1">How routing works:</p>
                      <p>When a webhook arrives from Slack, GitHub, PagerDuty, or other integrations, the system checks these identifiers to determine which team should handle the event. Add all the IDs and names that belong to your team.</p>
                    </div>
                  </div>
                </div>

                {routingLoading ? (
                  <div className="flex items-center justify-center py-12">
                    <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
                    <span className="ml-2 text-gray-500">Loading routing configuration...</span>
                  </div>
                ) : (
                  <div className="space-y-4">
                    {/* Add Routing Form */}
                    {editingRoutingField ? (
                      <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 bg-gray-50 dark:bg-gray-800/50">
                        <div className="flex flex-col sm:flex-row gap-3">
                          <select
                            value={editingRoutingField}
                            onChange={(e) => setEditingRoutingField(e.target.value as keyof RoutingConfig)}
                            className="px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                          >
                            <option value="slack_channel_ids">Slack Channel ID</option>
                            <option value="github_repos">GitHub Repository</option>
                            <option value="pagerduty_service_ids">PagerDuty Service ID</option>
                            <option value="incidentio_team_ids">Incident.io Team ID</option>
                            <option value="incidentio_alert_source_ids">Incident.io Alert Source ID</option>
                            <option value="coralogix_team_names">Coralogix Team Name</option>
                            <option value="services">Service Name</option>
                          </select>
                          <input
                            type="text"
                            value={newRoutingValue}
                            onChange={(e) => setNewRoutingValue(e.target.value)}
                            placeholder={
                              editingRoutingField === 'slack_channel_ids' ? 'C0A4967KRBM' :
                              editingRoutingField === 'github_repos' ? 'owner/repo' :
                              editingRoutingField === 'pagerduty_service_ids' ? 'PXXXXXX' :
                              editingRoutingField === 'incidentio_team_ids' ? '01KCSZ7FHG...' :
                              editingRoutingField === 'incidentio_alert_source_ids' ? '01KEGMSPP...' :
                              editingRoutingField === 'coralogix_team_names' ? 'team-name' :
                              'service-name'
                            }
                            className="flex-1 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                            onKeyDown={(e) => e.key === 'Enter' && addRoutingValue(editingRoutingField)}
                            autoFocus
                          />
                          <div className="flex gap-2">
                            <button
                              onClick={() => addRoutingValue(editingRoutingField)}
                              className="px-4 py-2 bg-gray-600 text-white text-sm rounded-lg hover:bg-gray-700"
                            >
                              Add
                            </button>
                            <button
                              onClick={() => { setEditingRoutingField(null); setNewRoutingValue(''); }}
                              className="px-4 py-2 text-gray-600 dark:text-gray-400 text-sm hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <button
                        onClick={() => setEditingRoutingField('slack_channel_ids')}
                        className="flex items-center gap-2 px-4 py-2 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-200 border border-dashed border-gray-300 dark:border-gray-700 rounded-lg hover:border-gray-400 dark:hover:border-gray-600 transition-colors"
                      >
                        <Plus className="w-4 h-4" />
                        Add Routing Rule
                      </button>
                    )}

                    {/* Configured Routes List */}
                    {(() => {
                      const allRoutes: { type: keyof RoutingConfig; label: string; value: string }[] = [];
                      routingConfig.slack_channel_ids.forEach(v => allRoutes.push({ type: 'slack_channel_ids', label: 'Slack', value: v }));
                      routingConfig.github_repos.forEach(v => allRoutes.push({ type: 'github_repos', label: 'GitHub', value: v }));
                      routingConfig.pagerduty_service_ids.forEach(v => allRoutes.push({ type: 'pagerduty_service_ids', label: 'PagerDuty', value: v }));
                      routingConfig.incidentio_team_ids.forEach(v => allRoutes.push({ type: 'incidentio_team_ids', label: 'Incident.io Team', value: v }));
                      routingConfig.incidentio_alert_source_ids.forEach(v => allRoutes.push({ type: 'incidentio_alert_source_ids', label: 'Incident.io Source', value: v }));
                      routingConfig.coralogix_team_names.forEach(v => allRoutes.push({ type: 'coralogix_team_names', label: 'Coralogix', value: v }));
                      routingConfig.services.forEach(v => allRoutes.push({ type: 'services', label: 'Service', value: v }));

                      if (allRoutes.length === 0) {
                        return (
                          <div className="text-sm text-gray-500 py-8 text-center border border-dashed border-gray-200 dark:border-gray-800 rounded-lg">
                            No routing rules configured. Webhooks won&apos;t be routed to this team.
                          </div>
                        );
                      }

                      return (
                        <div className="border border-gray-200 dark:border-gray-800 rounded-lg divide-y divide-gray-200 dark:divide-gray-800">
                          {allRoutes.map((route, idx) => (
                            <div
                              key={`${route.type}-${route.value}-${idx}`}
                              className="flex items-center justify-between p-3 hover:bg-gray-50 dark:hover:bg-gray-800/50"
                            >
                              <div className="flex items-center gap-3">
                                <span className="px-2 py-0.5 text-xs font-medium bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 rounded">
                                  {route.label}
                                </span>
                                <code className="text-sm text-gray-900 dark:text-gray-100">{route.value}</code>
                              </div>
                              <button
                                onClick={() => removeRoutingValue(route.type, route.value)}
                                className="p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
                              >
                                <X className="w-4 h-4" />
                              </button>
                            </div>
                          ))}
                        </div>
                      );
                    })()}

                    {/* Save Button */}
                    <div className="pt-4 border-t border-gray-200 dark:border-gray-800">
                      <button
                        onClick={saveRoutingConfig}
                        disabled={routingSaving}
                        className="flex items-center gap-2 px-4 py-2 bg-gray-600 text-white rounded-lg hover:bg-gray-700 disabled:opacity-50"
                      >
                        {routingSaving ? (
                          <>
                            <Loader2 className="w-4 h-4 animate-spin" />
                            Saving...
                          </>
                        ) : (
                          <>
                            <Check className="w-4 h-4" />
                            Save Routing Configuration
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Delivery & Notifications Tab */}
          {activeTab === 'notifications' && (
            <div className="space-y-6">
              <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-6 shadow-sm">
                <div className="flex items-center justify-between mb-6">
                  <div>
                    <h2 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-1">
                      Output Destinations
                      <HelpTip id="output-destinations" position="right">
                        <strong>Output Destinations</strong> control where agent investigation results are posted. You can set default destinations (like a Slack channel) and override behavior based on how the agent was triggered.
                      </HelpTip>
                    </h2>
                    <p className="text-sm text-gray-500 mt-1">
                      Configure where agent results are delivered
                    </p>
                  </div>
                </div>

                {/* Default Destinations */}
                <div className="space-y-4">
                  <div>
                    <h3 className="text-sm font-medium text-gray-900 dark:text-white mb-3">
                      Default Destinations
                    </h3>
                    <p className="text-xs text-gray-500 mb-4">
                      Agent results will be posted to these destinations by default
                    </p>

                    {outputConfig.default_destinations.length === 0 ? (
                      <div className="text-sm text-gray-500 py-8 text-center border-2 border-dashed border-gray-200 dark:border-gray-800 rounded-lg">
                        No default destinations configured. Results will only be posted to trigger-specific locations.
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {outputConfig.default_destinations.map((dest, idx) => (
                          <div
                            key={idx}
                            className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-800 rounded-lg"
                          >
                            <div className="flex items-center gap-3">
                              <div className="px-2 py-1 bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-300 text-xs font-medium rounded">
                                {dest.type}
                              </div>
                              {dest.type === 'slack' && (
                                <span className="text-sm text-gray-700 dark:text-gray-300">
                                  {dest.channel_name || dest.channel_id || 'Unknown channel'}
                                </span>
                              )}
                              {dest.type === 'github' && (
                                <span className="text-sm text-gray-700 dark:text-gray-300">
                                  {dest.repo || 'Unknown repo'}
                                </span>
                              )}
                            </div>
                            <button
                              onClick={() => removeDestination(idx)}
                              className="text-red-600 hover:text-red-700 dark:text-red-400"
                            >
                              <X className="w-4 h-4" />
                            </button>
                          </div>
                        ))}
                      </div>
                    )}

                    {!showAddDestination ? (
                      <button
                        onClick={() => setShowAddDestination(true)}
                        className="mt-3 flex items-center gap-2 px-3 py-2 text-sm text-orange-600 dark:text-orange-400 hover:bg-orange-50 dark:hover:bg-orange-900/20 rounded-lg"
                      >
                        <Plus className="w-4 h-4" />
                        Add Destination
                      </button>
                    ) : (
                      <div className="mt-3 p-4 bg-gray-50 dark:bg-gray-800 rounded-lg space-y-3">
                        <div>
                          <label className="block text-xs text-gray-600 dark:text-gray-400 mb-1">
                            Destination Type
                          </label>
                          <select
                            value={newDestinationType}
                            onChange={(e) => setNewDestinationType(e.target.value)}
                            className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900"
                          >
                            <option value="slack">Slack</option>
                            <option value="github">GitHub</option>
                            <option value="pagerduty">PagerDuty</option>
                          </select>
                        </div>

                        {newDestinationType === 'slack' && (
                          <>
                            <div>
                              <label className="block text-xs text-gray-600 dark:text-gray-400 mb-1">
                                Channel Name
                              </label>
                              <input
                                type="text"
                                placeholder="#incidents"
                                value={newDestinationConfig.channel_name}
                                onChange={(e) =>
                                  setNewDestinationConfig({ ...newDestinationConfig, channel_name: e.target.value })
                                }
                                className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900"
                              />
                            </div>
                            <div>
                              <label className="block text-xs text-gray-600 dark:text-gray-400 mb-1">
                                Channel ID
                              </label>
                              <input
                                type="text"
                                placeholder="C1234567890"
                                value={newDestinationConfig.channel_id}
                                onChange={(e) =>
                                  setNewDestinationConfig({ ...newDestinationConfig, channel_id: e.target.value })
                                }
                                className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900"
                              />
                            </div>
                          </>
                        )}

                        <div className="flex gap-2">
                          <button
                            onClick={addDestination}
                            disabled={
                              newDestinationType === 'slack' &&
                              (!newDestinationConfig.channel_id || !newDestinationConfig.channel_name)
                            }
                            className="flex items-center gap-2 px-3 py-2 text-sm bg-orange-600 text-white rounded-lg hover:bg-orange-700 disabled:opacity-50"
                          >
                            <Check className="w-4 h-4" />
                            Add
                          </button>
                          <button
                            onClick={() => {
                              setShowAddDestination(false);
                              setNewDestinationConfig({ channel_name: '', channel_id: '' });
                            }}
                            className="px-3 py-2 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Trigger Overrides */}
                  <div className="border-t border-gray-200 dark:border-gray-800 pt-4 mt-6">
                    <h3 className="text-sm font-medium text-gray-900 dark:text-white mb-3">
                      Trigger-Specific Rules
                    </h3>
                    <p className="text-xs text-gray-500 mb-4">
                      Override behavior for specific trigger sources
                    </p>

                    <div className="space-y-3">
                      <div className="flex items-center justify-between py-2">
                        <div>
                          <div className="text-sm font-medium text-gray-900 dark:text-white">
                            When triggered from Slack
                          </div>
                          <div className="text-xs text-gray-500">Choose where to post results</div>
                        </div>
                        <select
                          value={outputConfig.trigger_overrides.slack || 'reply_in_thread'}
                          onChange={(e) =>
                            setOutputConfig({
                              ...outputConfig,
                              trigger_overrides: { ...outputConfig.trigger_overrides, slack: e.target.value },
                            })
                          }
                          className="px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900"
                        >
                          <option value="reply_in_thread">Reply in thread</option>
                          <option value="use_default">Use default destinations</option>
                        </select>
                      </div>

                      <div className="flex items-center justify-between py-2">
                        <div>
                          <div className="text-sm font-medium text-gray-900 dark:text-white">
                            When triggered from GitHub
                          </div>
                          <div className="text-xs text-gray-500">Choose where to post results</div>
                        </div>
                        <select
                          value={outputConfig.trigger_overrides.github || 'comment_on_pr'}
                          onChange={(e) =>
                            setOutputConfig({
                              ...outputConfig,
                              trigger_overrides: { ...outputConfig.trigger_overrides, github: e.target.value },
                            })
                          }
                          className="px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900"
                        >
                          <option value="comment_on_pr">Comment on PR/issue</option>
                          <option value="use_default">Use default destinations</option>
                        </select>
                      </div>

                      <div className="flex items-center justify-between py-2">
                        <div>
                          <div className="text-sm font-medium text-gray-900 dark:text-white">
                            When triggered from API
                          </div>
                          <div className="text-xs text-gray-500">Choose where to post results</div>
                        </div>
                        <select
                          value={outputConfig.trigger_overrides.api || 'use_default'}
                          onChange={(e) =>
                            setOutputConfig({
                              ...outputConfig,
                              trigger_overrides: { ...outputConfig.trigger_overrides, api: e.target.value },
                            })
                          }
                          className="px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900"
                        >
                          <option value="use_default">Use default destinations</option>
                          <option value="no_output">No output (silent)</option>
                        </select>
                      </div>
                    </div>
                  </div>

                  {/* Save Button */}
                  <div className="border-t border-gray-200 dark:border-gray-800 pt-4 mt-6">
                    <button
                      onClick={saveOutputConfig}
                      disabled={outputConfigLoading}
                      className="px-4 py-2 bg-orange-600 text-white rounded-lg hover:bg-orange-700 disabled:opacity-50"
                    >
                      {outputConfigLoading ? 'Saving...' : 'Save Configuration'}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Telemetry Tab */}
          {activeTab === 'telemetry' && (
            <div className="space-y-6">
              <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-6 shadow-sm">
                <div className="flex items-center justify-between mb-6">
                  <div>
                    <h2 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-1">
                      Telemetry Settings
                      <HelpTip id="telemetry-settings" position="right">
                        <strong>Telemetry</strong> helps us improve IncidentFox by sharing anonymous usage metrics (agent run counts, success rates, performance). No personal data, prompts, or sensitive information is ever collected.
                      </HelpTip>
                    </h2>
                    <p className="text-sm text-gray-500 mt-1">
                      Help us improve IncidentFox by sharing anonymous usage data
                    </p>
                  </div>
                  <button
                    onClick={toggleTelemetry}
                    disabled={telemetryLoading}
                    className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                      telemetryEnabled ? 'bg-orange-600' : 'bg-gray-300 dark:bg-gray-700'
                    } ${telemetryLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
                  >
                    <span
                      className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                        telemetryEnabled ? 'translate-x-6' : 'translate-x-1'
                      }`}
                    />
                  </button>
                </div>

                <div className="space-y-4">
                  <div className="border-t border-gray-200 dark:border-gray-800 pt-4">
                    <h3 className="text-sm font-medium text-gray-900 dark:text-white mb-3">
                      What data is collected?
                    </h3>
                    <div className="space-y-3 text-sm text-gray-600 dark:text-gray-400">
                      <div className="flex items-start gap-3">
                        <div className="mt-0.5 w-1.5 h-1.5 rounded-full bg-orange-500 flex-shrink-0"></div>
                        <div>
                          <span className="font-medium text-gray-900 dark:text-white">Agent run metrics:</span> Number of agent runs, success/failure rates, execution duration, and timeout counts
                        </div>
                      </div>
                      <div className="flex items-start gap-3">
                        <div className="mt-0.5 w-1.5 h-1.5 rounded-full bg-orange-500 flex-shrink-0"></div>
                        <div>
                          <span className="font-medium text-gray-900 dark:text-white">Usage patterns:</span> Tool usage frequency, agent types used, trigger sources (webhook, manual, scheduled)
                        </div>
                      </div>
                      <div className="flex items-start gap-3">
                        <div className="mt-0.5 w-1.5 h-1.5 rounded-full bg-orange-500 flex-shrink-0"></div>
                        <div>
                          <span className="font-medium text-gray-900 dark:text-white">Performance statistics:</span> Average duration, p50/p95/p99 latency percentiles, error types
                        </div>
                      </div>
                      <div className="flex items-start gap-3">
                        <div className="mt-0.5 w-1.5 h-1.5 rounded-full bg-orange-500 flex-shrink-0"></div>
                        <div>
                          <span className="font-medium text-gray-900 dark:text-white">Team activity:</span> Number of active teams and overall team count
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="border-t border-gray-200 dark:border-gray-800 pt-4">
                    <h3 className="text-sm font-medium text-gray-900 dark:text-white mb-3">
                      What is NOT collected?
                    </h3>
                    <div className="space-y-3 text-sm text-gray-600 dark:text-gray-400">
                      <div className="flex items-start gap-3">
                        <div className="mt-0.5 w-1.5 h-1.5 rounded-full bg-green-500 flex-shrink-0"></div>
                        <div>Personal information, user credentials, or authentication tokens</div>
                      </div>
                      <div className="flex items-start gap-3">
                        <div className="mt-0.5 w-1.5 h-1.5 rounded-full bg-green-500 flex-shrink-0"></div>
                        <div>Agent prompts, messages, or conversation content</div>
                      </div>
                      <div className="flex items-start gap-3">
                        <div className="mt-0.5 w-1.5 h-1.5 rounded-full bg-green-500 flex-shrink-0"></div>
                        <div>Knowledge base documents or team-specific data</div>
                      </div>
                      <div className="flex items-start gap-3">
                        <div className="mt-0.5 w-1.5 h-1.5 rounded-full bg-green-500 flex-shrink-0"></div>
                        <div>API keys, secrets, or integration credentials</div>
                      </div>
                      <div className="flex items-start gap-3">
                        <div className="mt-0.5 w-1.5 h-1.5 rounded-full bg-green-500 flex-shrink-0"></div>
                        <div>IP addresses, hostnames, or network identifiers</div>
                      </div>
                    </div>
                  </div>

                  <div className="border-t border-gray-200 dark:border-gray-800 pt-4">
                    <h3 className="text-sm font-medium text-gray-900 dark:text-white mb-3">
                      How is data used?
                    </h3>
                    <div className="space-y-2 text-sm text-gray-600 dark:text-gray-400">
                      <p>
                        Telemetry data is aggregated and anonymized to help us understand product usage patterns,
                        identify performance issues, and prioritize feature development. Data is sent securely to
                        our vendor service and is never shared with third parties.
                      </p>
                      <p className="mt-3">
                        <span className="font-medium text-gray-900 dark:text-white">Reporting frequency:</span>
                        {' '}Metrics are collected every 5 minutes (heartbeat) and aggregated daily at 2:00 AM UTC.
                      </p>
                    </div>
                  </div>

                  <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4 mt-4">
                    <p className="text-sm text-blue-800 dark:text-blue-200">
                      <span className="font-medium">Note:</span> Disabling telemetry will take effect immediately.
                      Your organization's data will be excluded from all future reports. License validation will
                      continue to work normally.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Features Tab - AI Pipeline & Dependency Discovery */}
          {activeTab === 'features' && (
            <div className="space-y-6">
              {/* AI Pipeline Section */}
              <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-6 shadow-sm">
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className="p-2 bg-gray-100 dark:bg-gray-800 rounded-lg">
                      <Zap className="w-5 h-5 text-gray-600 dark:text-gray-400" />
                    </div>
                    <div>
                      <h2 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-1">
                        AI Pipeline
                        <HelpTip id="ai-pipeline" position="right">
                          <strong>AI Pipeline</strong> automatically processes your incident data (Slack discussions, Confluence runbooks, Google Docs) on a schedule and extracts learnings to build your Knowledge Base. This enables agents to reference past incidents and solutions.
                        </HelpTip>
                      </h2>
                      <p className="text-sm text-gray-500">
                        Automatically learn from incidents and build knowledge base
                      </p>
                    </div>
                  </div>
                  <button
                    onClick={() => setPipelineConfig({ ...pipelineConfig, enabled: !pipelineConfig.enabled })}
                    disabled={featuresLoading}
                    className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                      pipelineConfig.enabled ? 'bg-gray-600' : 'bg-gray-300 dark:bg-gray-700'
                    } ${featuresLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
                  >
                    <span
                      className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                        pipelineConfig.enabled ? 'translate-x-6' : 'translate-x-1'
                      }`}
                    />
                  </button>
                </div>

                {pipelineConfig.enabled && (
                  <div className="mt-4 pt-4 border-t border-gray-200 dark:border-gray-800 space-y-4">
                    {/* Schedule */}
                    <div className="flex items-center gap-4">
                      <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
                        <Clock className="w-4 h-4" />
                        Schedule (cron):
                      </div>
                      <input
                        type="text"
                        value={pipelineConfig.schedule}
                        onChange={(e) => setPipelineConfig({ ...pipelineConfig, schedule: e.target.value })}
                        placeholder="0 2 * * *"
                        className="flex-1 max-w-xs px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 font-mono"
                      />
                      <span className="text-xs text-gray-500">
                        Default: 2:00 AM daily
                      </span>
                    </div>

                    {/* Data Sources / Ingestors */}
                    <div className="space-y-4">
                      <div className="text-sm font-medium text-gray-700 dark:text-gray-300">
                        Data Sources
                      </div>

                      {/* Slack Ingestor */}
                      <div className={`p-4 rounded-lg border ${
                        pipelineConfig.ingestors.slack.enabled
                          ? 'border-gray-400 bg-gray-50 dark:bg-gray-800/50'
                          : 'border-gray-200 dark:border-gray-700'
                      }`}>
                        <label className="flex items-center gap-3 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={pipelineConfig.ingestors.slack.enabled}
                            onChange={(e) =>
                              setPipelineConfig({
                                ...pipelineConfig,
                                ingestors: {
                                  ...pipelineConfig.ingestors,
                                  slack: { ...pipelineConfig.ingestors.slack, enabled: e.target.checked },
                                },
                              })
                            }
                            className="sr-only"
                          />
                          <div
                            className={`w-4 h-4 rounded border flex items-center justify-center ${
                              pipelineConfig.ingestors.slack.enabled
                                ? 'bg-gray-600 border-gray-600'
                                : 'border-gray-300 dark:border-gray-600'
                            }`}
                          >
                            {pipelineConfig.ingestors.slack.enabled && <Check className="w-3 h-3 text-white" />}
                          </div>
                          <div>
                            <div className="text-sm font-medium text-gray-900 dark:text-white">Slack</div>
                            <div className="text-xs text-gray-500">Incident discussions & resolutions</div>
                          </div>
                        </label>
                        {pipelineConfig.ingestors.slack.enabled && (
                          <div className="mt-3 pl-7">
                            <label className="block text-xs text-gray-600 dark:text-gray-400 mb-1">
                              Channels to monitor (comma-separated)
                            </label>
                            <input
                              type="text"
                              value={pipelineConfig.ingestors.slack.channels.join(', ')}
                              onChange={(e) =>
                                setPipelineConfig({
                                  ...pipelineConfig,
                                  ingestors: {
                                    ...pipelineConfig.ingestors,
                                    slack: {
                                      ...pipelineConfig.ingestors.slack,
                                      channels: e.target.value.split(',').map(s => s.trim()).filter(Boolean),
                                    },
                                  },
                                })
                              }
                              placeholder="#incidents, #oncall, #postmortems"
                              className="w-full px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
                            />
                            <p className="text-xs text-gray-400 mt-1">Leave empty to monitor all bot-accessible channels</p>
                          </div>
                        )}
                      </div>

                      {/* Confluence Ingestor */}
                      <div className={`p-4 rounded-lg border ${
                        pipelineConfig.ingestors.confluence.enabled
                          ? 'border-gray-400 bg-gray-50 dark:bg-gray-800/50'
                          : 'border-gray-200 dark:border-gray-700'
                      }`}>
                        <label className="flex items-center gap-3 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={pipelineConfig.ingestors.confluence.enabled}
                            onChange={(e) =>
                              setPipelineConfig({
                                ...pipelineConfig,
                                ingestors: {
                                  ...pipelineConfig.ingestors,
                                  confluence: { ...pipelineConfig.ingestors.confluence, enabled: e.target.checked },
                                },
                              })
                            }
                            className="sr-only"
                          />
                          <div
                            className={`w-4 h-4 rounded border flex items-center justify-center ${
                              pipelineConfig.ingestors.confluence.enabled
                                ? 'bg-gray-600 border-gray-600'
                                : 'border-gray-300 dark:border-gray-600'
                            }`}
                          >
                            {pipelineConfig.ingestors.confluence.enabled && <Check className="w-3 h-3 text-white" />}
                          </div>
                          <div>
                            <div className="text-sm font-medium text-gray-900 dark:text-white">Confluence</div>
                            <div className="text-xs text-gray-500">Runbooks & documentation</div>
                          </div>
                        </label>
                        {pipelineConfig.ingestors.confluence.enabled && (
                          <div className="mt-3 pl-7 space-y-3">
                            <div>
                              <label className="block text-xs text-gray-600 dark:text-gray-400 mb-1">
                                Confluence Base URL
                              </label>
                              <input
                                type="text"
                                value={pipelineConfig.ingestors.confluence.base_url}
                                onChange={(e) =>
                                  setPipelineConfig({
                                    ...pipelineConfig,
                                    ingestors: {
                                      ...pipelineConfig.ingestors,
                                      confluence: { ...pipelineConfig.ingestors.confluence, base_url: e.target.value },
                                    },
                                  })
                                }
                                placeholder="https://company.atlassian.net"
                                className="w-full px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
                              />
                            </div>
                            <div>
                              <label className="block text-xs text-gray-600 dark:text-gray-400 mb-1">
                                Space Keys (comma-separated)
                              </label>
                              <input
                                type="text"
                                value={pipelineConfig.ingestors.confluence.space_keys.join(', ')}
                                onChange={(e) =>
                                  setPipelineConfig({
                                    ...pipelineConfig,
                                    ingestors: {
                                      ...pipelineConfig.ingestors,
                                      confluence: {
                                        ...pipelineConfig.ingestors.confluence,
                                        space_keys: e.target.value.split(',').map(s => s.trim()).filter(Boolean),
                                      },
                                    },
                                  })
                                }
                                placeholder="ENG, OPS, RUNBOOKS"
                                className="w-full px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
                              />
                              <p className="text-xs text-gray-400 mt-1">Leave empty to include all accessible spaces</p>
                            </div>
                          </div>
                        )}
                      </div>

                      {/* Google Docs Ingestor */}
                      <div className={`p-4 rounded-lg border ${
                        pipelineConfig.ingestors.gdocs.enabled
                          ? 'border-gray-400 bg-gray-50 dark:bg-gray-800/50'
                          : 'border-gray-200 dark:border-gray-700'
                      }`}>
                        <label className="flex items-center gap-3 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={pipelineConfig.ingestors.gdocs.enabled}
                            onChange={(e) =>
                              setPipelineConfig({
                                ...pipelineConfig,
                                ingestors: {
                                  ...pipelineConfig.ingestors,
                                  gdocs: { ...pipelineConfig.ingestors.gdocs, enabled: e.target.checked },
                                },
                              })
                            }
                            className="sr-only"
                          />
                          <div
                            className={`w-4 h-4 rounded border flex items-center justify-center ${
                              pipelineConfig.ingestors.gdocs.enabled
                                ? 'bg-gray-600 border-gray-600'
                                : 'border-gray-300 dark:border-gray-600'
                            }`}
                          >
                            {pipelineConfig.ingestors.gdocs.enabled && <Check className="w-3 h-3 text-white" />}
                          </div>
                          <div>
                            <div className="text-sm font-medium text-gray-900 dark:text-white">Google Docs</div>
                            <div className="text-xs text-gray-500">Postmortems & procedures</div>
                          </div>
                        </label>
                        {pipelineConfig.ingestors.gdocs.enabled && (
                          <div className="mt-3 pl-7">
                            <label className="block text-xs text-gray-600 dark:text-gray-400 mb-1">
                              Folder IDs (comma-separated, optional)
                            </label>
                            <input
                              type="text"
                              value={pipelineConfig.ingestors.gdocs.folder_ids.join(', ')}
                              onChange={(e) =>
                                setPipelineConfig({
                                  ...pipelineConfig,
                                  ingestors: {
                                    ...pipelineConfig.ingestors,
                                    gdocs: {
                                      ...pipelineConfig.ingestors.gdocs,
                                      folder_ids: e.target.value.split(',').map(s => s.trim()).filter(Boolean),
                                    },
                                  },
                                })
                              }
                              placeholder="1abc123..., 2def456..."
                              className="w-full px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
                            />
                            <p className="text-xs text-gray-400 mt-1">Leave empty to include all shared drive docs</p>
                          </div>
                        )}
                      </div>

                      {/* Agent Traces Ingestor */}
                      <div className={`p-4 rounded-lg border ${
                        pipelineConfig.ingestors.agent_traces.enabled
                          ? 'border-gray-400 bg-gray-50 dark:bg-gray-800/50'
                          : 'border-gray-200 dark:border-gray-700'
                      }`}>
                        <label className="flex items-center gap-3 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={pipelineConfig.ingestors.agent_traces.enabled}
                            onChange={(e) =>
                              setPipelineConfig({
                                ...pipelineConfig,
                                ingestors: {
                                  ...pipelineConfig.ingestors,
                                  agent_traces: { enabled: e.target.checked },
                                },
                              })
                            }
                            className="sr-only"
                          />
                          <div
                            className={`w-4 h-4 rounded border flex items-center justify-center ${
                              pipelineConfig.ingestors.agent_traces.enabled
                                ? 'bg-gray-600 border-gray-600'
                                : 'border-gray-300 dark:border-gray-600'
                            }`}
                          >
                            {pipelineConfig.ingestors.agent_traces.enabled && <Check className="w-3 h-3 text-white" />}
                          </div>
                          <div>
                            <div className="text-sm font-medium text-gray-900 dark:text-white">Agent Traces</div>
                            <div className="text-xs text-gray-500">Tool calls, errors & decisions (auto-configured)</div>
                          </div>
                        </label>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* Dependency Discovery Section */}
              <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-6 shadow-sm">
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className="p-2 bg-gray-100 dark:bg-gray-800 rounded-lg">
                      <Network className="w-5 h-5 text-gray-600 dark:text-gray-400" />
                    </div>
                    <div>
                      <h2 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-1">
                        Service Dependency Discovery
                        <HelpTip id="dependency-discovery" position="right">
                          <strong>Dependency Discovery</strong> analyzes your observability data (traces, metrics) to automatically map service relationships. This helps agents understand how services connect and identify cascading failures during incidents.
                        </HelpTip>
                      </h2>
                      <p className="text-sm text-gray-500">
                        Automatically discover service dependencies from observability data
                      </p>
                    </div>
                  </div>
                  <button
                    onClick={() => setDependencyConfig({ ...dependencyConfig, enabled: !dependencyConfig.enabled })}
                    disabled={featuresLoading}
                    className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                      dependencyConfig.enabled ? 'bg-gray-600' : 'bg-gray-300 dark:bg-gray-700'
                    } ${featuresLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
                  >
                    <span
                      className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                        dependencyConfig.enabled ? 'translate-x-6' : 'translate-x-1'
                      }`}
                    />
                  </button>
                </div>

                {dependencyConfig.enabled && (
                  <div className="mt-4 pt-4 border-t border-gray-200 dark:border-gray-800 space-y-4">
                    {/* Schedule */}
                    <div className="flex items-center gap-4">
                      <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
                        <Clock className="w-4 h-4" />
                        Schedule (cron):
                      </div>
                      <input
                        type="text"
                        value={dependencyConfig.schedule}
                        onChange={(e) => setDependencyConfig({ ...dependencyConfig, schedule: e.target.value })}
                        placeholder="0 */2 * * *"
                        className="flex-1 max-w-xs px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 font-mono"
                      />
                      <span className="text-xs text-gray-500">
                        Default: Every 2 hours
                      </span>
                    </div>

                    {/* Data Sources */}
                    <div>
                      <div className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">
                        Discovery Sources
                      </div>
                      <div className="grid grid-cols-2 gap-3">
                        {[
                          { key: 'new_relic', name: 'New Relic', desc: 'Distributed tracing' },
                          { key: 'datadog', name: 'Datadog', desc: 'APM traces' },
                          { key: 'cloudwatch', name: 'AWS CloudWatch', desc: 'X-Ray traces' },
                          { key: 'prometheus', name: 'Prometheus', desc: 'Service mesh metrics' },
                        ].map((source) => (
                          <label
                            key={source.key}
                            className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                              dependencyConfig.sources[source.key as keyof typeof dependencyConfig.sources]
                                ? 'border-gray-400 bg-gray-50 dark:bg-gray-800/50'
                                : 'border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800'
                            }`}
                          >
                            <input
                              type="checkbox"
                              checked={dependencyConfig.sources[source.key as keyof typeof dependencyConfig.sources]}
                              onChange={(e) =>
                                setDependencyConfig({
                                  ...dependencyConfig,
                                  sources: {
                                    ...dependencyConfig.sources,
                                    [source.key]: e.target.checked,
                                  },
                                })
                              }
                              className="sr-only"
                            />
                            <div
                              className={`w-4 h-4 rounded border flex items-center justify-center ${
                                dependencyConfig.sources[source.key as keyof typeof dependencyConfig.sources]
                                  ? 'bg-gray-600 border-gray-600'
                                  : 'border-gray-300 dark:border-gray-600'
                              }`}
                            >
                              {dependencyConfig.sources[source.key as keyof typeof dependencyConfig.sources] && (
                                <Check className="w-3 h-3 text-white" />
                              )}
                            </div>
                            <div>
                              <div className="text-sm font-medium text-gray-900 dark:text-white">
                                {source.name}
                              </div>
                              <div className="text-xs text-gray-500">{source.desc}</div>
                            </div>
                          </label>
                        ))}
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* Alert Correlation Section */}
              <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-6 shadow-sm">
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className="p-2 bg-gray-100 dark:bg-gray-800 rounded-lg">
                      <Link2 className="w-5 h-5 text-gray-600 dark:text-gray-400" />
                    </div>
                    <div>
                      <h2 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-1">
                        Alert Correlation
                        <HelpTip id="alert-correlation" position="right">
                          <strong>Alert Correlation</strong> groups related alerts together to reduce noise. It uses three methods: <em>temporal</em> (alerts within a time window), <em>topology</em> (alerts from related services), and <em>semantic</em> (alerts with similar descriptions).
                        </HelpTip>
                      </h2>
                      <p className="text-sm text-gray-500">
                        Automatically correlate related alerts using temporal, topology, and semantic analysis
                      </p>
                    </div>
                  </div>
                  <button
                    onClick={() => setCorrelationConfig({ ...correlationConfig, enabled: !correlationConfig.enabled })}
                    disabled={featuresLoading}
                    className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                      correlationConfig.enabled ? 'bg-gray-600' : 'bg-gray-300 dark:bg-gray-700'
                    } ${featuresLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
                  >
                    <span
                      className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                        correlationConfig.enabled ? 'translate-x-6' : 'translate-x-1'
                      }`}
                    />
                  </button>
                </div>

                {correlationConfig.enabled && (
                  <div className="mt-4 pt-4 border-t border-gray-200 dark:border-gray-800 space-y-4">
                    {/* Temporal Window */}
                    <div className="flex items-center gap-4">
                      <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
                        <Clock className="w-4 h-4" />
                        Temporal Window:
                      </div>
                      <input
                        type="number"
                        value={correlationConfig.temporal_window_seconds}
                        onChange={(e) => setCorrelationConfig({ ...correlationConfig, temporal_window_seconds: parseInt(e.target.value) || 300 })}
                        min={60}
                        max={3600}
                        className="w-24 px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 font-mono"
                      />
                      <span className="text-xs text-gray-500">
                        seconds (default: 300 = 5 min)
                      </span>
                    </div>

                    {/* Semantic Threshold */}
                    <div className="flex items-center gap-4">
                      <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
                        <Activity className="w-4 h-4" />
                        Semantic Threshold:
                      </div>
                      <input
                        type="number"
                        value={correlationConfig.semantic_threshold}
                        onChange={(e) => setCorrelationConfig({ ...correlationConfig, semantic_threshold: parseFloat(e.target.value) || 0.75 })}
                        min={0}
                        max={1}
                        step={0.05}
                        className="w-24 px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 font-mono"
                      />
                      <span className="text-xs text-gray-500">
                        0.0 - 1.0 (default: 0.75)
                      </span>
                    </div>

                    <div className="mt-3 text-xs text-gray-500">
                      When enabled, incoming alerts are correlated with recent alerts based on:
                      <ul className="list-disc list-inside mt-2 space-y-1">
                        <li><strong>Temporal:</strong> Alerts within the time window</li>
                        <li><strong>Topology:</strong> Related services from dependency graph</li>
                        <li><strong>Semantic:</strong> Similar alert descriptions (above threshold)</li>
                      </ul>
                    </div>
                  </div>
                )}
              </div>

              {/* Save & Sync Actions */}
              <div className="flex items-center gap-3">
                <button
                  onClick={saveFeatureConfigs}
                  disabled={featuresSaving}
                  className="flex items-center gap-2 px-4 py-2 bg-gray-600 text-white rounded-lg hover:bg-gray-700 disabled:opacity-50"
                >
                  {featuresSaving ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Saving...
                    </>
                  ) : (
                    <>
                      <Check className="w-4 h-4" />
                      Save Configuration
                    </>
                  )}
                </button>
                <button
                  onClick={syncCronJobs}
                  disabled={syncingCronJobs}
                  className="flex items-center gap-2 px-4 py-2 bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 disabled:opacity-50"
                >
                  {syncingCronJobs ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Syncing...
                    </>
                  ) : (
                    <>
                      <RefreshCcw className="w-4 h-4" />
                      Apply Changes
                    </>
                  )}
                </button>
                <span className="text-xs text-gray-500">
                  Save config first, then apply to activate scheduled jobs
                </span>
              </div>

              {/* Info Box */}
              <div className="bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-700 rounded-lg p-4">
                <p className="text-sm text-gray-700 dark:text-gray-300">
                  <span className="font-medium">How it works:</span> When enabled, these features run as scheduled Kubernetes CronJobs.
                  The AI Pipeline processes incident data to build your knowledge base. Dependency Discovery analyzes
                  observability data to map service relationships, helping agents understand your architecture during incidents.
                </p>
              </div>
            </div>
          )}

          {/* Advanced Tab */}
          {activeTab === 'advanced' && isAdmin && (
            <div className="space-y-6">
              <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-xl p-4">
                <div className="flex items-center gap-2 text-yellow-800 dark:text-yellow-200">
                  <AlertTriangle className="w-5 h-5" />
                  <span className="font-medium">Advanced Tools</span>
                </div>
                <p className="text-sm text-yellow-700 dark:text-yellow-300 mt-1">
                  These tools are for debugging and testing. Use with caution.
                </p>
              </div>

              <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-6 shadow-sm">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
                  <Bot className="w-5 h-5" /> Ad-Hoc Agent Run
                </h2>
                
                <div className="space-y-4">
                    <div>
                    <label className="block text-sm text-gray-600 dark:text-gray-400 mb-1">
                      Prompt
                    </label>
                    <textarea
                      value={agentPrompt}
                      onChange={(e) => setAgentPrompt(e.target.value)}
                      rows={3}
                      placeholder="e.g., Investigate the cart service in otel-demo namespace"
                      className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
                    />
                    </div>
                  <button
                    onClick={runAgent}
                    disabled={agentRunning || !agentPrompt.trim()}
                    className="flex items-center gap-2 px-4 py-2 bg-orange-600 text-white rounded-lg hover:bg-orange-700 disabled:opacity-50"
                  >
                    {agentRunning ? (
                      <>
                        <RefreshCcw className="w-4 h-4 animate-spin" />
                        Running...
                      </>
                    ) : (
                      <>
                        <Bot className="w-4 h-4" />
                        Run Agent
                      </>
                    )}
                  </button>

                  {agentResult && (
                    <div className="mt-4">
                      <label className="block text-sm text-gray-600 dark:text-gray-400 mb-1">
                        Result
                        </label>
                      <pre className="p-4 bg-gray-50 dark:bg-gray-800 rounded-lg overflow-auto max-h-80 text-xs font-mono">
                        {JSON.stringify(agentResult, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
            </div>
          </div>
          )}
        </div>
      </div>
    </div>
  );
}
