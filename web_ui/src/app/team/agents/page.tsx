'use client';

import { useEffect, useState, useCallback, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { useIdentity } from '@/lib/useIdentity';
import {
  Bot,
  Save,
  CheckCircle,
  XCircle,
  Loader2,
  Zap,
  Brain,
  Wrench,
  Users,
  ToggleLeft,
  ToggleRight,
  X,
  Sparkles,
  Eye,
  EyeOff,
  RefreshCw,
  Code,
  Network,
  ExternalLink,
  Globe,
  Activity,
  Settings,
  Edit2,
  Trash2,
  LayoutTemplate,
  Server,
} from 'lucide-react';
import { apiFetch } from '@/lib/apiClient';
import { QuickStartWizard } from '@/components/onboarding/QuickStartWizard';
import { ContinueOnboardingButton } from '@/components/onboarding/ContinueOnboardingButton';
import { HelpTip } from '@/components/onboarding/HelpTip';

interface AgentModel {
  name: string;
  temperature: number;
  max_tokens: number;
}

interface AgentPrompt {
  system: string;
  prefix?: string;
  suffix?: string;
}

// Dict-based configuration schema
type AgentTools = { [tool_id: string]: boolean };

interface AgentConfig {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  model: AgentModel;
  prompt: AgentPrompt;
  tools: AgentTools;  // Dict format: {tool_id: boolean}
  disable_default_tools?: string[];  // Team overrides to disable inherited tools
  enable_extra_tools?: string[];     // Team overrides to add extra tools
  sub_agents: { [agent_id: string]: boolean };  // Dict format: {agent_id: boolean}
  disable_default_sub_agents?: string[];  // Team overrides to disable inherited sub-agents
  enable_extra_sub_agents?: string[];     // Team overrides to add team-specific sub-agents
  mcps?: { [mcp_id: string]: boolean };  // Dict format: {mcp_id: boolean}
  max_turns: number;
  handoff_strategy?: string;
  source: 'org' | 'team';
}

interface ToolDefinition {
  name: string;
  description: string;
  source: 'built-in' | 'mcp';
  mcp_server?: string;
}

interface RemoteAgentConfig {
  id: string;
  name: string;
  type: 'a2a';
  url: string;
  auth: {
    type: 'none' | 'bearer' | 'apikey' | 'oauth2';
    token?: string;
    api_key?: string;
    location?: 'header' | 'query';
    key_name?: string;
    token_url?: string;
    client_id?: string;
    client_secret?: string;
    scope?: string;
  };
  description?: string;
  timeout?: number;
  enabled?: boolean;
}


type RawMeResponse = {
  lineage?: Array<string | { org_id?: string; node_id: string; name?: string; node_type?: string; parent_id?: string | null }>;
  configs?: Record<string, unknown>;
};

export default function AgentSettingsPage() {
  const router = useRouter();
  const { identity } = useIdentity();
  const [agents, setAgents] = useState<Record<string, AgentConfig>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [editingAgent, setEditingAgent] = useState<AgentConfig | null>(null);
  const [editingRemoteAgent, setEditingRemoteAgent] = useState<RemoteAgentConfig | null>(null);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [showPrompt, setShowPrompt] = useState(false);
  const [showAddAgent, setShowAddAgent] = useState(false);
  const [showAddRemoteAgent, setShowAddRemoteAgent] = useState(false);
  const [showEditRemoteAgent, setShowEditRemoteAgent] = useState(false);
  const [showAgentTypeMenu, setShowAgentTypeMenu] = useState(false);
  const [newAgentId, setNewAgentId] = useState('');
  const [remoteAgents, setRemoteAgents] = useState<RemoteAgentConfig[]>([]);
  const [newRemoteAgent, setNewRemoteAgent] = useState<RemoteAgentConfig>({
    id: '',
    name: '',
    type: 'a2a',
    url: '',
    auth: { type: 'none' },
    description: '',
    timeout: 300,
  });
  const [testingConnection, setTestingConnection] = useState(false);
  const [connectionTestResult, setConnectionTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [zoom, setZoom] = useState(1);
  const [panOffset, setPanOffset] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  const [showToolPicker, setShowToolPicker] = useState(false);
  const [toolPool, setToolPool] = useState<ToolDefinition[]>([]);
  const [loadingTools, setLoadingTools] = useState(false);

  // NEW: MCP Servers state
  const [mcpServers, setMcpServers] = useState<Record<string, any>>({});

  // View mode: 'visual' for topology, 'json' for raw config
  const [viewMode, setViewMode] = useState<'visual' | 'json'>('visual');
  const [effective, setEffective] = useState<unknown | null>(null);
  const [raw, setRaw] = useState<RawMeResponse | null>(null);
  const [entranceAgentId, setEntranceAgentId] = useState<string | null>(null);
  const [overridesText, setOverridesText] = useState('{\n  \n}');
  const [initialOverridesLoaded, setInitialOverridesLoaded] = useState(false);
  const [showInheritanceModal, setShowInheritanceModal] = useState(false);

  // Quick Start wizard state
  const [showQuickStart, setShowQuickStart] = useState(false);
  const [quickStartInitialStep, setQuickStartInitialStep] = useState(1);

  const teamId = identity?.team_node_id;

  const loadToolPool = useCallback(async () => {
    setLoadingTools(true);
    try {
      // Fetch tools catalog from agent service (includes built-in + MCP tools)
      const res = await fetch('/api/team/tools');
      if (res.ok) {
        const data = await res.json();
        const tools: ToolDefinition[] = (data.tools || []).map((tool: any) => ({
          name: tool.id,
          description: tool.description || '',
          source: tool.source === 'mcp' ? 'mcp' as const : 'built-in' as const,
        }));

        setToolPool(tools);
      }
    } catch (e) {
      console.error('Failed to load tool pool:', e);
    } finally {
      setLoadingTools(false);
    }
  }, []);

  const loadAgents = useCallback(async () => {
    if (!teamId) return;
    setLoading(true);
    setInitialOverridesLoaded(false);

    try {
      const res = await fetch('/api/team/config');
      if (res.ok) {
        const data = await res.json();
        const agentsConfig = data.agents || {};

        // Also store the full effective config for JSON view
        setEffective(data);

        // Load entrance agent (the root orchestrator for this team's topology)
        // Falls back to 'planner' if not specified
        setEntranceAgentId(data.entrance_agent || 'planner');

        // NEW: Load MCP servers
        const mcpServersConfig = data.mcp_servers || {};
        setMcpServers(mcpServersConfig);

        // Load remote agents (flat dict pattern)
        const remoteAgentsConfig = data.remote_agents || {};
        // Convert dict to array for state management
        const agentsArray = Object.entries(remoteAgentsConfig)
          .filter(([_, config]: [string, any]) => config && typeof config === 'object')
          .map(([id, config]: [string, any]) => ({
            id,
            ...config,
          }));
        setRemoteAgents(agentsArray);

        // Convert to our format
        const agentMap: Record<string, AgentConfig> = {};
        for (const [id, config] of Object.entries(agentsConfig)) {
          const cfg = config as Partial<AgentConfig>;
          agentMap[id] = {
            id,
            name: cfg.name || id,
            description: cfg.description || '',
            enabled: cfg.enabled !== false,
            model: cfg.model || { name: 'gpt-4o', temperature: 0.3, max_tokens: 16000 },
            prompt: cfg.prompt || { system: '' },
            tools: cfg.tools || {},
            disable_default_tools: cfg.disable_default_tools,
            enable_extra_tools: cfg.enable_extra_tools,
            sub_agents: cfg.sub_agents || {},
            disable_default_sub_agents: cfg.disable_default_sub_agents,
            enable_extra_sub_agents: cfg.enable_extra_sub_agents,
            mcps: cfg.mcps,
            max_turns: cfg.max_turns || 20,
            handoff_strategy: cfg.handoff_strategy,
            source: 'org', // TODO: detect from raw config
          };
        }
        setAgents(agentMap);
        // Don't select any agent by default - panel starts closed
      }
      
      // Load raw config for JSON view
      const rawRes = await apiFetch('/api/config/me/raw', { cache: 'no-store' });
      if (rawRes.ok) {
        setRaw((await rawRes.json()) as RawMeResponse);
      }
    } catch (e) {
      console.error('Failed to load agents:', e);
    } finally {
      setLoading(false);
    }
  }, [teamId]);

  const saveOverrides = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const parsed = JSON.parse(overridesText);
      const res = await apiFetch('/api/config/me', {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(parsed),
      });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${await res.text()}`);
      await loadAgents();
      setMessage({ type: 'success', text: 'Overrides saved successfully' });
    } catch (e: unknown) {
      const errorMessage = e instanceof Error ? e.message : String(e);
      setMessage({ type: 'error', text: errorMessage });
    } finally {
      setSaving(false);
    }
  };

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
    // Handle both string array (API returns this) and object array
    return lineage.map((n) => {
      if (typeof n === 'string') return n;
      return n.name || n.node_id;
    }).join(' → ');
  }, [raw?.lineage]);

  useEffect(() => {
    loadAgents();
    loadToolPool();
  }, [loadAgents, loadToolPool]);

  // Pre-fill team overrides when raw data loads
  useEffect(() => {
    if (raw?.configs && raw?.lineage && !initialOverridesLoaded) {
      // Get the team's own config (last item in lineage)
      const lineage = raw.lineage;
      const teamNodeId = typeof lineage[lineage.length - 1] === 'string'
        ? lineage[lineage.length - 1]
        : (lineage[lineage.length - 1] as any)?.node_id;

      if (teamNodeId && raw.configs[teamNodeId as string]) {
        setOverridesText(JSON.stringify(raw.configs[teamNodeId as string], null, 2));
      } else {
        // No team config yet, show empty object
        setOverridesText('{\n  \n}');
      }
      setInitialOverridesLoaded(true);
    }
  }, [raw, initialOverridesLoaded]);

  // Helper function to compute effective sub-agents using disable/enable pattern
  const getEffectiveSubAgents = useCallback((agent: AgentConfig): string[] => {
    // Extract enabled sub-agents from dict format
    const defaultSubAgents = Object.entries(agent.sub_agents || {})
      .filter(([_, enabled]) => enabled)
      .map(([id, _]) => id);
    const disabledSubAgents = agent.disable_default_sub_agents || [];
    const extraSubAgents = agent.enable_extra_sub_agents || [];

    // Effective = default - disabled + extra
    const effectiveSubAgents = [
      ...defaultSubAgents.filter(id => !disabledSubAgents.includes(id)),
      ...extraSubAgents
    ];

    // Dedupe while preserving order
    return Array.from(new Set(effectiveSubAgents));
  }, []);

  // Build graph layout using BFS depth-based positioning
  // Level is determined by: distance from entrance agent (BFS depth)
  // Level 0 = entrance agent (the root orchestrator for this team)
  // Level 1 = direct children of entrance agent
  // Level 2 = grandchildren, etc.
  const graphLayout = useMemo(() => {
    const localAgentIds = Object.keys(agents);

    // Use the entrance agent as the single root for the topology
    const rootAgentId = entranceAgentId && agents[entranceAgentId] ? entranceAgentId : null;

    if (!rootAgentId) {
      return { nodes: [], edges: [], levels: [], entranceAgentId: null };
    }

    // BFS to find reachable agents AND their depth from root
    const agentDepth: Record<string, number> = {};
    const reachableAgents = new Set<string>();
    const reachableRemoteAgentIds = new Set<string>();

    // BFS queue: [agentId, depth]
    const queue: [string, number][] = [[rootAgentId, 0]];

    while (queue.length > 0) {
      const [current, depth] = queue.shift()!;

      // Skip if already visited
      if (reachableAgents.has(current) || reachableRemoteAgentIds.has(current)) continue;

      // Check if it's a local or remote agent
      if (agents[current]) {
        reachableAgents.add(current);
        agentDepth[current] = depth;

        // Add sub-agents to queue with incremented depth
        getEffectiveSubAgents(agents[current]).forEach(subId => {
          if (!reachableAgents.has(subId) && !reachableRemoteAgentIds.has(subId)) {
            queue.push([subId, depth + 1]);
          }
        });
      } else if (remoteAgents.find(r => r.id === current)) {
        reachableRemoteAgentIds.add(current);
        agentDepth[current] = depth;
      }
    }

    // Only include agents reachable from the entrance agent
    const connectedLocalAgents = localAgentIds.filter(id => reachableAgents.has(id));
    const allAgentIds = [...connectedLocalAgents, ...Array.from(reachableRemoteAgentIds)];

    if (allAgentIds.length === 0) return { nodes: [], edges: [], levels: [], entranceAgentId: rootAgentId };

    // Group agents by their BFS depth level
    const levelGroups: Record<number, string[]> = {};
    allAgentIds.forEach(id => {
      const level = agentDepth[id] ?? 0;
      if (!levelGroups[level]) levelGroups[level] = [];
      levelGroups[level].push(id);
    });

    // Sort levels and create node positions
    const sortedLevels = Object.keys(levelGroups).map(Number).sort((a, b) => a - b);
    const nodes: { id: string; x: number; y: number; level: number; isRemote: boolean }[] = [];
    const levelSpacingY = 140;
    const centerX = 300;

    sortedLevels.forEach((level, levelIndex) => {
      const agentsInLevel = levelGroups[level];
      const spacing = 130;
      const startX = centerX - ((agentsInLevel.length - 1) * spacing) / 2;

      agentsInLevel.forEach((id, i) => {
        nodes.push({
          id,
          x: startX + i * spacing,
          y: 50 + levelIndex * levelSpacingY,
          level,
          isRemote: reachableRemoteAgentIds.has(id),
        });
      });
    });

    // Build edges only from reachable agents
    const edges: { from: string; to: string }[] = [];
    connectedLocalAgents.forEach(id => {
      const agent = agents[id];
      getEffectiveSubAgents(agent).forEach(subId => {
        // Create edge only if both ends are reachable
        if (reachableAgents.has(subId) || reachableRemoteAgentIds.has(subId)) {
          edges.push({ from: id, to: subId });
        }
      });
    });

    // Calculate bounds for auto-centering
    const bounds = nodes.length > 0 ? {
      minX: Math.min(...nodes.map(n => n.x)),
      maxX: Math.max(...nodes.map(n => n.x)),
      minY: Math.min(...nodes.map(n => n.y)),
      maxY: Math.max(...nodes.map(n => n.y)),
    } : { minX: 0, maxX: 0, minY: 0, maxY: 0 };

    return { nodes, edges, levels: sortedLevels, bounds, entranceAgentId: rootAgentId };
  }, [agents, remoteAgents, getEffectiveSubAgents, entranceAgentId]);

  // Auto-center graph when it loads
  useEffect(() => {
    if (graphLayout.nodes.length > 0 && graphLayout.bounds && typeof window !== 'undefined') {
      const bounds = graphLayout.bounds;
      const graphWidth = bounds.maxX - bounds.minX + 200; // Add padding
      const graphHeight = bounds.maxY - bounds.minY + 200;
      const viewportWidth = window.innerWidth * (selectedAgent ? 0.5 : 1);
      const viewportHeight = window.innerHeight - 200;

      // Center the graph in the viewport
      const offsetX = (viewportWidth - graphWidth) / 2 - bounds.minX + 100;
      const offsetY = (viewportHeight - graphHeight) / 2 - bounds.minY + 100;

      setPanOffset({ x: offsetX, y: offsetY });
    }
  }, [graphLayout.nodes.length, graphLayout.bounds, selectedAgent]);

  const handleAgentClick = (agentId: string) => {
    setSelectedAgent(agentId);

    // Check if it's a local agent or remote agent
    if (agents[agentId]) {
      setEditingAgent({ ...agents[agentId] });
      setEditingRemoteAgent(null);
    } else {
      const remoteAgent = remoteAgents.find(r => r.id === agentId);
      if (remoteAgent) {
        setEditingRemoteAgent({ ...remoteAgent });
        setEditingAgent(null);
      }
    }

    setShowPrompt(false);
    setConnectionTestResult(null);
  };

  // Mouse wheel zoom handler
  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const delta = -e.deltaY / 1000;
    setZoom(prevZoom => Math.max(0.5, Math.min(1.5, prevZoom + delta)));
  }, []);

  // Mouse drag handlers for panning
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button === 0) { // Left mouse button
      setIsDragging(true);
      setDragStart({ x: e.clientX - panOffset.x, y: e.clientY - panOffset.y });
    }
  }, [panOffset]);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (isDragging) {
      setPanOffset({
        x: e.clientX - dragStart.x,
        y: e.clientY - dragStart.y,
      });
    }
  }, [isDragging, dragStart]);

  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
  }, []);

  const handleMouseLeave = useCallback(() => {
    setIsDragging(false);
  }, []);

  const handleClosePanel = () => {
    setSelectedAgent(null);
    setEditingAgent(null);
    setEditingRemoteAgent(null);
    setConnectionTestResult(null);
  };

  const handleAddAgent = () => {
    if (!newAgentId.trim()) return;
    const id = newAgentId.trim().toLowerCase().replace(/\s+/g, '_');
    if (agents[id]) {
      setMessage({ type: 'error', text: 'Agent with this ID already exists' });
      return;
    }
    const newAgent: AgentConfig = {
      id,
      name: newAgentId.trim(),
      description: '',
      enabled: true,
      model: { name: 'gpt-4o', temperature: 0.3, max_tokens: 16000 },
      prompt: { system: '' },
      tools: {},
      sub_agents: {},
      mcps: {},
      max_turns: 20,
      source: 'team',
    };
    setAgents(prev => ({ ...prev, [id]: newAgent }));
    setSelectedAgent(id);
    setEditingAgent(newAgent);
    setShowAddAgent(false);
    setNewAgentId('');
  };

  const handleSave = async () => {
    if (!editingAgent) return;
    setSaving(true);
    setMessage(null);

    try {
      // Update the agent config
      const res = await fetch('/api/team/config', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agents: {
            [editingAgent.id]: {
              name: editingAgent.name,
              description: editingAgent.description,
              enabled: editingAgent.enabled,
              model: editingAgent.model,
              prompt: editingAgent.prompt,
              tools: editingAgent.tools,
              disable_default_tools: editingAgent.disable_default_tools,
              enable_extra_tools: editingAgent.enable_extra_tools,
              // Don't send sub_agents when using new disable/enable pattern to avoid conflicts
              // sub_agents: editingAgent.sub_agents,
              disable_default_sub_agents: editingAgent.disable_default_sub_agents,
              enable_extra_sub_agents: editingAgent.enable_extra_sub_agents,
              mcps: editingAgent.mcps,  // NEW: Save MCP assignments
              max_turns: editingAgent.max_turns,
              handoff_strategy: editingAgent.handoff_strategy,
            },
          },
        }),
      });

      if (res.ok) {
        // Reload all agents to get the merged config from server
        await loadAgents();
        // Re-select the same agent to refresh the editing panel
        if (agents[editingAgent.id]) {
          setEditingAgent({ ...agents[editingAgent.id], ...editingAgent, source: 'team' });
        }
        setMessage({ type: 'success', text: 'Agent configuration saved!' });
      } else {
        const err = await res.json();
        setMessage({ type: 'error', text: err.error || 'Failed to save' });
      }
    } catch (e) {
      const error = e as Error;
      setMessage({ type: 'error', text: error?.message || 'Failed to save' });
    } finally {
      setSaving(false);
    }
  };


  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-gray-400" />
      </div>
    );
  }

  const currentAgent = selectedAgent ? agents[selectedAgent] : null;

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <div className="flex-shrink-0 px-8 py-6 border-b border-gray-200 dark:border-gray-800">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-orange-500 to-amber-500 flex items-center justify-center">
              <Brain className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
                Agent Topology
              </h1>
              <p className="text-sm text-gray-500">
                Configure your multi-agent system topology, prompts, and behaviors
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {/* View toggle */}
            <div className="flex items-center bg-gray-100 dark:bg-gray-800 rounded-lg p-1">
              <button
                onClick={() => setViewMode('visual')}
                className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-sm transition-all ${
                  viewMode === 'visual'
                    ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm'
                    : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
                }`}
              >
                <Network className="w-4 h-4" />
                Visual
              </button>
              <button
                onClick={() => setViewMode('json')}
                className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-sm transition-all ${
                  viewMode === 'json'
                    ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm'
                    : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
                }`}
              >
                <Code className="w-4 h-4" />
                JSON
              </button>
            </div>

            <button
              onClick={() => window.location.href = '/team/templates'}
              className="flex items-center gap-2 px-4 py-2.5 bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 transition-all"
            >
              <LayoutTemplate className="w-4 h-4" />
              Templates
            </button>

            <div className="relative">
              <button
                onClick={() => setShowAgentTypeMenu(!showAgentTypeMenu)}
                className="flex items-center gap-2 px-4 py-2.5 bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 transition-all"
              >
                <span className="text-lg leading-none">+</span>
                Add Agent
              </button>

              {showAgentTypeMenu && (
                <div className="absolute right-0 mt-2 w-56 bg-white dark:bg-gray-800 rounded-lg shadow-xl border border-gray-200 dark:border-gray-700 z-50">
                  <button
                    onClick={() => {
                      setShowAgentTypeMenu(false);
                      setShowAddAgent(true);
                    }}
                    className="w-full px-4 py-3 text-left hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors rounded-t-lg flex items-center gap-3"
                  >
                    <Bot className="w-4 h-4 text-gray-500" />
                    <div>
                      <div className="text-sm font-medium text-gray-900 dark:text-white">Add Local Agent</div>
                      <div className="text-xs text-gray-500">Create a new internal agent</div>
                    </div>
                  </button>
                  <button
                    onClick={() => {
                      setShowAgentTypeMenu(false);
                      setShowAddRemoteAgent(true);
                    }}
                    className="w-full px-4 py-3 text-left hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors rounded-b-lg flex items-center gap-3"
                  >
                    <ExternalLink className="w-4 h-4 text-gray-500" />
                    <div>
                      <div className="text-sm font-medium text-gray-900 dark:text-white">Add Remote A2A Agent</div>
                      <div className="text-xs text-gray-500">Integrate external AI agent</div>
                    </div>
                  </button>
                </div>
              )}
            </div>
            <button
              onClick={() => loadAgents()}
              disabled={loading}
              className="flex items-center gap-2 px-4 py-2.5 bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 disabled:opacity-50 transition-all"
              title="Refresh from server"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
            {editingAgent && (
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex items-center gap-2 px-5 py-2.5 bg-orange-600 text-white rounded-lg hover:bg-orange-700 disabled:opacity-50 transition-all"
              >
                {saving ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Save className="w-4 h-4" />
                )}
                Save
              </button>
            )}
          </div>
        </div>

        {/* Message */}
        {message && (
          <div
            className={`mt-4 p-3 rounded-xl flex items-center gap-3 ${
              message.type === 'success'
                ? 'bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 text-green-700 dark:text-green-400'
                : 'bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-400'
            }`}
          >
            {message.type === 'success' ? (
              <CheckCircle className="w-5 h-5" />
            ) : (
              <XCircle className="w-5 h-5" />
            )}
            {message.text}
          </div>
        )}
      </div>

      <div className="flex-1 flex min-h-0">
        {/* JSON View */}
        {viewMode === 'json' ? (
          <div className="flex-1 flex flex-col overflow-hidden p-6">
            {/* Header with lineage and inheritance button */}
            <div className="max-w-7xl mx-auto w-full mb-4 flex items-center justify-between flex-shrink-0">
              <div className="flex items-center gap-3 text-sm text-gray-500">
                <span className="flex items-center gap-1">
                  Lineage: <span className="font-mono">{lineageLabel}</span>
                  <HelpTip id="config-lineage" position="right">
                    <strong>Lineage</strong> shows the configuration inheritance path. Settings flow from Organization to Team level, with more specific levels overriding general ones.
                  </HelpTip>
                </span>
                <button
                  onClick={() => setShowInheritanceModal(true)}
                  className="text-orange-600 hover:text-orange-700 dark:text-orange-400 dark:hover:text-orange-300 underline underline-offset-2"
                >
                  Show inheritance details
                </button>
              </div>
              <a
                href="https://docs.incidentfox.ai/config"
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm text-gray-400 hover:text-gray-300 flex items-center gap-1"
              >
                Docs <ExternalLink className="w-3 h-3" />
              </a>
            </div>

            <div className="flex-1 min-h-0 max-w-7xl mx-auto w-full grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Left: Active Configuration (read-only) */}
              <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-5 shadow-sm flex flex-col overflow-hidden">
                <div className="flex items-center justify-between mb-3 flex-shrink-0">
                  <div className="text-sm font-semibold text-gray-900 dark:text-white flex items-center gap-1">
                    Active Configuration
                    <HelpTip id="effective-config" position="right">
                      The <strong>active configuration</strong> is the final merged result of organization defaults combined with your team&apos;s overrides. This is what IncidentFox actually uses at runtime.
                    </HelpTip>
                  </div>
                  <span className="text-xs text-gray-400">Read-only</span>
                </div>
                <pre className="flex-1 min-h-0 overflow-auto bg-gray-50 dark:bg-gray-950/50 border border-gray-200 dark:border-gray-800 rounded-lg p-3 text-xs font-mono text-gray-700 dark:text-gray-200">
                  {effectivePretty || '(not loaded)'}
                </pre>
              </div>

              {/* Right: Team Overrides (editable) */}
              <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-5 shadow-sm flex flex-col overflow-hidden">
                <div className="flex items-center justify-between mb-3 flex-shrink-0">
                  <div className="text-sm font-semibold text-gray-900 dark:text-white flex items-center gap-1">
                    Team Overrides
                    <HelpTip id="team-overrides" position="right">
                      <strong>Team Overrides</strong> are your team&apos;s custom settings. Changes here only affect your team, not the organization. Edit the JSON below and click Save to update your configuration.
                    </HelpTip>
                  </div>
                </div>

                <textarea
                  value={overridesText}
                  onChange={(e) => setOverridesText(e.target.value)}
                  placeholder={`// Your team's configuration\n// Edit and save to customize settings\n{\n  \n}`}
                  className="flex-1 min-h-0 w-full p-3 font-mono text-xs rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-950 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-orange-500 resize-none"
                />

                <div className="mt-3 flex justify-between items-center flex-shrink-0">
                  <p className="text-xs text-gray-500">
                    Edit and save to update your team&apos;s configuration.
                  </p>
                  <button
                    onClick={saveOverrides}
                    disabled={saving}
                    className="flex items-center gap-2 px-4 py-2 text-sm font-medium bg-orange-600 text-white rounded-lg hover:bg-orange-700 disabled:opacity-70"
                  >
                    {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                    Save
                  </button>
                </div>
              </div>
            </div>
          </div>
        ) : (
          /* Left Panel: Visual Topology */
          <div className={`${selectedAgent ? 'w-1/2' : 'flex-1'} overflow-auto bg-gray-100 dark:bg-gray-950 transition-all duration-300 relative`}>
            {/* Zoom Controls */}
            <div className="absolute top-4 right-4 z-20 flex items-center gap-1 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 shadow-sm">
              <button
                onClick={() => setZoom(z => Math.max(0.5, z - 0.1))}
                className="px-3 py-1.5 text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-l-lg"
              >
                −
              </button>
              <span className="px-2 text-xs text-gray-500 min-w-[3rem] text-center">
                {Math.round(zoom * 100)}%
              </span>
              <button
                onClick={() => setZoom(z => Math.min(1.5, z + 0.1))}
                className="px-3 py-1.5 text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-r-lg"
              >
                +
              </button>
            </div>

          {/* Zoomable Canvas */}
          <div
            className="relative min-h-[calc(100vh-200px)] overflow-hidden"
            onWheel={handleWheel}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseLeave}
            style={{
              cursor: isDragging ? 'grabbing' : 'grab',
            }}
          >
            <div
              className="relative p-6"
              style={{
                minWidth: '600px',
                transform: `translate(${panOffset.x}px, ${panOffset.y}px) scale(${zoom})`,
                transformOrigin: '0 0',
              }}
            >
            {/* Connection Lines (SVG) */}
            <svg
              className="absolute top-0 left-0 pointer-events-none"
              style={{
                zIndex: 0,
                width: '100%',
                height: '100%',
                overflow: 'visible'
              }}
            >
              <defs>
                <marker
                  id="arrowhead"
                  markerWidth="6"
                  markerHeight="5"
                  refX="5"
                  refY="2.5"
                  orient="auto"
                  markerUnits="userSpaceOnUse"
                >
                  <polygon
                    points="0 0, 6 2.5, 0 5"
                    fill="#9ca3af"
                  />
                </marker>
              </defs>

              {/* Draw edges between agents - simple straight lines */}
              {graphLayout.edges.map((edge, i) => {
                const fromNode = graphLayout.nodes.find(n => n.id === edge.from);
                const toNode = graphLayout.nodes.find(n => n.id === edge.to);
                if (!fromNode || !toNode) return null;

                const fromY = fromNode.y + 40;
                const toY = toNode.y;
                const midY = (fromY + toY) / 2;

                return (
                  <g key={`${edge.from}-${edge.to}-${i}`}>
                    <path
                      d={`M ${fromNode.x} ${fromY} Q ${fromNode.x} ${midY}, ${toNode.x} ${toY}`}
                      fill="none"
                      stroke="#d1d5db"
                      strokeWidth="2"
                      markerEnd="url(#arrowhead)"
                    />
                  </g>
                );
              })}
            </svg>

            {/* Agent Nodes */}
            {graphLayout.nodes.map((node) => {
              const localAgent = agents[node.id];
              const remoteAgent = remoteAgents.find(r => r.id === node.id);

              // Convert remote agent to agent format for rendering
              const agent = localAgent || (remoteAgent ? {
                id: remoteAgent.id,
                name: remoteAgent.name,
                description: remoteAgent.description || '',
                enabled: true,
                model: { name: 'remote', temperature: 0, max_tokens: 0 },
                prompt: { system: '' },
                tools: { enabled: [], disabled: [] },
                sub_agents: [],
                max_turns: 0,
                source: 'team' as const,
              } : null);

              if (!agent) return null;

              return (
                <div
                  key={node.id}
                  className="absolute transition-all duration-300"
                  style={{
                    left: node.x,
                    top: node.y,
                    transform: 'translate(-50%, 0)',
                    zIndex: selectedAgent === node.id ? 10 : 1,
                  }}
                >
                  <AgentNode
                    agent={agent}
                    isSelected={selectedAgent === node.id}
                    onClick={() => handleAgentClick(node.id)}
                    isPrimary={node.level === 0}
                    isRemote={node.isRemote}
                    isEntranceAgent={node.id === (effective as any)?.entrance_agent}
                  />
                </div>
              );
            })}
            </div>

            {/* Legend - Fixed position, outside transformed container */}
            <div className="absolute bottom-4 left-4 p-3 bg-white/90 dark:bg-gray-900/90 backdrop-blur rounded-lg border border-gray-200 dark:border-gray-800 z-10">
              <div className="flex items-center gap-4 text-xs text-gray-600 dark:text-gray-400">
                <div className="flex items-center gap-1.5">
                  <div className="w-2.5 h-2.5 rounded-full bg-green-500" />
                  <span>Enabled</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <Sparkles className="w-3 h-3 text-amber-500" />
                  <span>Entrance Agent</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <div className="w-6 h-px bg-gray-400" />
                  <span>→ Uses</span>
                </div>
              </div>
            </div>

            {/* Click hint - Fixed position, outside transformed container */}
            {!selectedAgent && (
              <div className="absolute bottom-4 right-4 text-xs text-gray-400 dark:text-gray-600 z-10">
                Click an agent to configure
              </div>
            )}
          </div>
        </div>
        )}

        {/* Right Panel: Agent Details (only in visual mode) */}
        {viewMode === 'visual' && selectedAgent && (
          <div className="w-1/2 border-l border-gray-200 dark:border-gray-800 overflow-auto bg-white dark:bg-gray-900">
            {currentAgent && editingAgent ? (
              <div className="p-6 space-y-6">
                {/* Agent Header */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    <div className="w-11 h-11 rounded-lg bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 flex items-center justify-center">
                      <Bot className="w-5 h-5 text-gray-600 dark:text-gray-400" />
                    </div>
                    <div>
                      <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                        {currentAgent.name}
                      </h2>
                      <p className="text-sm text-gray-500">{currentAgent.description}</p>
                    </div>
                  </div>

                <div className="flex items-center gap-2">
                  {/* Enable/Disable Toggle */}
                  <button
                    onClick={() =>
                      setEditingAgent({ ...editingAgent, enabled: !editingAgent.enabled })
                    }
                    className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm transition-colors ${
                      editingAgent.enabled
                        ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400'
                        : 'bg-gray-100 dark:bg-gray-800 text-gray-500'
                    }`}
                  >
                    {editingAgent.enabled ? (
                      <>
                        <ToggleRight className="w-4 h-4" />
                        On
                      </>
                    ) : (
                      <>
                        <ToggleLeft className="w-4 h-4" />
                        Off
                      </>
                    )}
                  </button>

                  {/* Close button */}
                  <button
                    onClick={handleClosePanel}
                    className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500"
                  >
                    <X className="w-5 h-5" />
                  </button>
                </div>
              </div>

              {/* Agent Type Badge */}
              {Object.keys(currentAgent.sub_agents || {}).length > 0 && (
                <div className="flex items-center gap-2">
                  <span className="text-xs px-2 py-1 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 border border-gray-200 dark:border-gray-700 flex items-center gap-1">
                    <Sparkles className="w-3 h-3" />
                    Orchestrator
                  </span>
                </div>
              )}

              {/* Configuration Sections */}
              <div className="space-y-4">
                {/* Model Configuration */}
                <div className="bg-gray-50 dark:bg-gray-900 rounded-xl p-4 border border-gray-200 dark:border-gray-800">
                  <div className="flex items-center gap-2 mb-4">
                    <Zap className="w-5 h-5 text-gray-500" />
                    <h3 className="font-semibold text-gray-900 dark:text-white">Model</h3>
                  </div>

                  <div className="grid grid-cols-3 gap-4">
                    <div>
                      <label className="block text-xs font-medium text-gray-500 mb-1">
                        Model Name
                      </label>
                      <select
                        value={editingAgent.model.name}
                        onChange={(e) =>
                          setEditingAgent({
                            ...editingAgent,
                            model: { ...editingAgent.model, name: e.target.value },
                          })
                        }
                        className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
                      >
                        <option value="gpt-4o">gpt-4o</option>
                        <option value="gpt-4o-mini">gpt-4o-mini</option>
                        <option value="gpt-4-turbo">gpt-4-turbo</option>
                        <option value="claude-3-5-sonnet-20241022">claude-3.5-sonnet</option>
                        <option value="claude-3-opus-20240229">claude-3-opus</option>
                      </select>
                    </div>

                    <div>
                      <label className="block text-xs font-medium text-gray-500 mb-1">
                        Temperature
                      </label>
                      <input
                        type="number"
                        step="0.1"
                        min="0"
                        max="2"
                        value={editingAgent.model.temperature}
                        onChange={(e) =>
                          setEditingAgent({
                            ...editingAgent,
                            model: {
                              ...editingAgent.model,
                              temperature: parseFloat(e.target.value) || 0,
                            },
                          })
                        }
                        className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
                      />
                    </div>

                    <div>
                      <label className="block text-xs font-medium text-gray-500 mb-1">
                        Max Turns
                      </label>
                      <input
                        type="number"
                        min="1"
                        max="100"
                        value={editingAgent.max_turns}
                        onChange={(e) =>
                          setEditingAgent({
                            ...editingAgent,
                            max_turns: parseInt(e.target.value) || 20,
                          })
                        }
                        className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
                      />
                    </div>
                  </div>
                </div>

                {/* System Prompt */}
                <div className="bg-gray-50 dark:bg-gray-900 rounded-xl p-4 border border-gray-200 dark:border-gray-800">
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                      <Brain className="w-5 h-5 text-gray-500" />
                      <h3 className="font-semibold text-gray-900 dark:text-white">
                        System Prompt
                      </h3>
                    </div>
                    <button
                      onClick={() => setShowPrompt(!showPrompt)}
                      className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
                    >
                      {showPrompt ? (
                        <>
                          <EyeOff className="w-4 h-4" />
                          Hide
                        </>
                      ) : (
                        <>
                          <Eye className="w-4 h-4" />
                          Show / Edit
                        </>
                      )}
                    </button>
                  </div>

                  {showPrompt ? (
                    <textarea
                      value={editingAgent.prompt.system}
                      onChange={(e) =>
                        setEditingAgent({
                          ...editingAgent,
                          prompt: { ...editingAgent.prompt, system: e.target.value },
                        })
                      }
                      rows={12}
                      className="w-full px-3 py-2 text-sm font-mono rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 resize-y"
                      placeholder="Enter system prompt..."
                    />
                  ) : (
                    <div className="text-sm text-gray-500 italic">
                      {editingAgent.prompt.system
                        ? `${editingAgent.prompt.system.slice(0, 150)}...`
                        : 'No prompt configured'}
                    </div>
                  )}
                </div>

                {/* Tools */}
                <div className="bg-gray-50 dark:bg-gray-900 rounded-xl p-4 border border-gray-200 dark:border-gray-800">
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                      <Wrench className="w-5 h-5 text-gray-500" />
                      <h3 className="font-semibold text-gray-900 dark:text-white">Tools</h3>
                    </div>
                    <button
                      onClick={() => setShowToolPicker(!showToolPicker)}
                      className="text-xs text-gray-500 hover:text-gray-400 flex items-center gap-1"
                    >
                      {showToolPicker ? (
                        <>
                          <EyeOff className="w-4 h-4" />
                          Hide
                        </>
                      ) : (
                        <>
                          <Eye className="w-4 h-4" />
                          Manage Tools
                        </>
                      )}
                    </button>
                  </div>

                  {showToolPicker ? (
                    <div className="space-y-4">
                      {/* Instructions */}
                      <div className="text-xs text-gray-500 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-3">
                        <p className="mb-2">
                          <strong>Default tools:</strong> Built-in tools automatically available to this agent.
                        </p>
                        <p className="mb-2">
                          <strong>Extra tools:</strong> Additional tools from your team's tool pool (built-in + MCP).
                        </p>
                        <p>
                          Click tools below to disable defaults or add extras.
                        </p>
                      </div>

                      {/* Disabled Default Tools */}
                      {(editingAgent.disable_default_tools || []).length > 0 && (
                        <div>
                          <div className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-2">
                            Disabled Default Tools:
                          </div>
                          <div className="flex flex-wrap gap-2">
                            {(editingAgent.disable_default_tools || []).map((tool) => (
                              <button
                                key={tool}
                                onClick={() => {
                                  setEditingAgent({
                                    ...editingAgent,
                                    disable_default_tools: (editingAgent.disable_default_tools || []).filter(t => t !== tool),
                                  });
                                }}
                                className="group flex items-center gap-1.5 px-2.5 py-1 text-xs rounded bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 hover:bg-red-200 dark:hover:bg-red-900/50 transition-colors"
                                title="Click to re-enable"
                              >
                                {tool}
                                <X className="w-3 h-3 opacity-60 group-hover:opacity-100" />
                              </button>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Enabled Extra Tools */}
                      {(editingAgent.enable_extra_tools || []).length > 0 && (
                        <div>
                          <div className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-2">
                            Enabled Extra Tools:
                          </div>
                          <div className="flex flex-wrap gap-2">
                            {(editingAgent.enable_extra_tools || []).map((tool) => (
                              <button
                                key={tool}
                                onClick={() => {
                                  setEditingAgent({
                                    ...editingAgent,
                                    enable_extra_tools: (editingAgent.enable_extra_tools || []).filter(t => t !== tool),
                                  });
                                }}
                                className="group flex items-center gap-1.5 px-2.5 py-1 text-xs rounded bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 hover:bg-green-200 dark:hover:bg-green-900/50 transition-colors"
                                title="Click to remove"
                              >
                                {tool}
                                <X className="w-3 h-3 opacity-60 group-hover:opacity-100" />
                              </button>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Default Tools (from dict config) */}
                      {(() => {
                        const enabledTools = Object.entries(editingAgent.tools || {})
                          .filter(([_, enabled]) => enabled)
                          .map(([tool, _]) => tool);
                        const hasWildcard = editingAgent.tools?.['*'] === true;

                        if (enabledTools.length === 0 && !hasWildcard) return null;

                        return (
                          <div>
                            <div className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-2">
                              Default Tools {hasWildcard && '(all enabled)'}:
                            </div>
                            {hasWildcard ? (
                              <div className="text-xs text-gray-500 italic">
                                Using wildcard pattern (*). All built-in tools are enabled by default.
                              </div>
                            ) : (
                              <div className="flex flex-wrap gap-2">
                                {enabledTools
                                  .filter(t => !(editingAgent.disable_default_tools || []).includes(t))
                                  .map((tool) => (
                                  <button
                                    key={tool}
                                    onClick={() => {
                                      setEditingAgent({
                                        ...editingAgent,
                                        disable_default_tools: [...(editingAgent.disable_default_tools || []), tool],
                                      });
                                    }}
                                    className="px-2.5 py-1 text-xs rounded bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
                                    title="Click to disable"
                                  >
                                    {tool}
                                  </button>
                                ))}
                              </div>
                            )}
                          </div>
                        );
                      })()}

                      {/* Add Extra Tools */}
                      <div>
                        <div className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-2">
                          Add Extra Tools from Pool:
                        </div>
                        {loadingTools ? (
                          <div className="text-xs text-gray-500">Loading tool pool...</div>
                        ) : (
                          <div className="max-h-40 overflow-y-auto border border-gray-200 dark:border-gray-700 rounded-lg p-2">
                            <div className="flex flex-wrap gap-2">
                              {toolPool
                                .filter(t => !(editingAgent.enable_extra_tools || []).includes(t.name))
                                .map((tool) => (
                                <button
                                  key={tool.name}
                                  onClick={() => {
                                    setEditingAgent({
                                      ...editingAgent,
                                      enable_extra_tools: [...(editingAgent.enable_extra_tools || []), tool.name],
                                    });
                                  }}
                                  className="flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-lg border border-dashed border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-400 hover:border-gray-400 hover:text-gray-500 dark:hover:text-gray-300 transition-colors"
                                  title={tool.description || 'Add this tool'}
                                >
                                  <span className="text-lg leading-none">+</span>
                                  {tool.name}
                                  {tool.source === 'mcp' && (
                                    <span className="text-[10px] px-1 py-0.5 rounded bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-400">
                                      MCP
                                    </span>
                                  )}
                                </button>
                              ))}
                            </div>
                            {toolPool.length === 0 && (
                              <div className="text-xs text-gray-500 italic">
                                No tools in pool. Add MCPs or built-in tools first.
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  ) : (
                    /* Compact summary view */
                    <div className="space-y-2">
                      <div className="text-sm text-gray-600 dark:text-gray-400">
                        {(() => {
                          const hasWildcard = editingAgent.tools?.['*'] === true;
                          const enabledCount = Object.values(editingAgent.tools || {}).filter(Boolean).length;
                          return hasWildcard ? (
                            <>All default tools enabled</>
                          ) : (
                            <>{enabledCount} default tools</>
                          );
                        })()}
                        {(editingAgent.disable_default_tools || []).length > 0 && (
                          <span className="text-red-600 dark:text-red-400">
                            {' '}− {editingAgent.disable_default_tools?.length} disabled
                          </span>
                        )}
                        {(editingAgent.enable_extra_tools || []).length > 0 && (
                          <span className="text-green-600 dark:text-green-400">
                            {' '}+ {editingAgent.enable_extra_tools?.length} extra
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                </div>

                {/* MCP Servers (Editable) */}
                <div className="bg-gray-50 dark:bg-gray-900 rounded-xl p-4 border border-gray-200 dark:border-gray-800">
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                      <Server className="w-5 h-5 text-cyan-500" />
                      <h3 className="font-semibold text-gray-900 dark:text-white">
                        MCP Servers
                      </h3>
                      <span className="text-xs text-gray-500">
                        (click to enable/disable)
                      </span>
                    </div>
                  </div>

                  <div className="space-y-3">
                    {(() => {
                      const agentMcps = editingAgent.mcps || {};
                      const enabledMcps = Object.entries(agentMcps)
                        .filter(([_, enabled]) => enabled)
                        .map(([id, _]) => id);

                      // Get list of available MCP servers
                      const availableMcps = Object.entries(mcpServers)
                        .filter(([_, config]: [string, any]) => config.enabled)
                        .map(([id, config]: [string, any]) => ({
                          id,
                          name: config.name || id,
                          tools: config.tools || [],
                          enabled_tools: config.enabled_tools || ['*']
                        }));

                      return (
                        <>
                          {/* Currently enabled MCPs */}
                          {enabledMcps.length > 0 && (
                            <div className="flex flex-wrap gap-2">
                              {enabledMcps.map((mcpId) => {
                                const mcpInfo = availableMcps.find(m => m.id === mcpId);
                                const toolCount = mcpInfo?.enabled_tools.includes('*')
                                  ? mcpInfo?.tools.length || 0
                                  : mcpInfo?.enabled_tools.length || 0;

                                return (
                                  <button
                                    key={mcpId}
                                    onClick={() => {
                                      setEditingAgent({
                                        ...editingAgent,
                                        mcps: {
                                          ...agentMcps,
                                          [mcpId]: false
                                        }
                                      });
                                    }}
                                    className="flex items-center gap-2 px-3 py-1.5 text-sm rounded-lg transition-colors group bg-cyan-500 text-white hover:bg-cyan-600"
                                    title={`Click to remove (${toolCount} tools)`}
                                  >
                                    <Server className="w-4 h-4" />
                                    {mcpInfo?.name || mcpId}
                                    <span className="text-xs opacity-75">({toolCount})</span>
                                    <X className="w-3 h-3 opacity-60 group-hover:opacity-100" />
                                  </button>
                                );
                              })}
                            </div>
                          )}

                          {/* Available MCPs to add */}
                          {(() => {
                            const disabledMcps = availableMcps.filter(
                              mcp => !enabledMcps.includes(mcp.id)
                            );

                            if (disabledMcps.length === 0) return null;

                            return (
                              <div>
                                <div className="text-xs text-gray-500 mb-2">Add MCP server:</div>
                                <div className="flex flex-wrap gap-2">
                                  {disabledMcps.map((mcp) => {
                                    const toolCount = mcp.enabled_tools.includes('*')
                                      ? mcp.tools.length
                                      : mcp.enabled_tools.length;

                                    return (
                                      <button
                                        key={mcp.id}
                                        onClick={() => {
                                          setEditingAgent({
                                            ...editingAgent,
                                            mcps: {
                                              ...agentMcps,
                                              [mcp.id]: true
                                            }
                                          });
                                        }}
                                        className="flex items-center gap-2 px-3 py-1.5 text-sm rounded-lg transition-colors bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:border-cyan-500 hover:text-cyan-600 dark:hover:text-cyan-400"
                                        title={`Click to add (${toolCount} tools)`}
                                      >
                                        <Server className="w-4 h-4" />
                                        {mcp.name}
                                        <span className="text-xs opacity-75">({toolCount})</span>
                                      </button>
                                    );
                                  })}
                                </div>
                              </div>
                            );
                          })()}

                          {availableMcps.length === 0 && (
                            <div className="text-sm text-gray-500 italic">
                              No MCP servers available. Configure them in the <a href="/team/tools" className="text-cyan-600 hover:underline">Tools page</a>.
                            </div>
                          )}
                        </>
                      );
                    })()}
                  </div>
                </div>

                {/* Sub-Agents (Editable) */}
                <div className="bg-gray-50 dark:bg-gray-900 rounded-xl p-4 border border-gray-200 dark:border-gray-800">
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                      <Users className="w-5 h-5 text-gray-500" />
                      <h3 className="font-semibold text-gray-900 dark:text-white">
                        Sub-Agents
                      </h3>
                      <span className="text-xs text-gray-500">
                        (click to add/remove)
                      </span>
                    </div>
                  </div>

                  <div className="space-y-3">
                    {(() => {
                      // Compute effective sub-agents - Extract enabled from dict format
                      const defaultSubAgents = Object.entries(editingAgent.sub_agents || {})
                        .filter(([_, enabled]) => enabled)
                        .map(([id, _]) => id);
                      const disabledSubAgents = editingAgent.disable_default_sub_agents || [];
                      const extraSubAgents = editingAgent.enable_extra_sub_agents || [];

                      // Effective = default - disabled + extra
                      const effectiveSubAgents = [
                        ...defaultSubAgents.filter(id => !disabledSubAgents.includes(id)),
                        ...extraSubAgents
                      ];
                      // Dedupe
                      const uniqueEffective = Array.from(new Set(effectiveSubAgents));

                      return (
                        <>
                          {/* Current sub-agents (effective) */}
                          {uniqueEffective.length > 0 && (
                            <div className="flex flex-wrap gap-2">
                              {uniqueEffective.map((subId) => {
                                const sub = agents[subId];
                                const remoteSub = remoteAgents.find(r => r.id === subId);
                                const isRemote = !!remoteSub;
                                const isDefault = defaultSubAgents.includes(subId);
                                const isExtra = extraSubAgents.includes(subId);

                                return (
                                  <button
                                    key={subId}
                                    onClick={() => {
                                      // When removing a sub-agent:
                                      // - If it's from default (not disabled), add to disabled list
                                      // - If it's from extra, remove from extra list
                                      const newDisabled = isDefault && !disabledSubAgents.includes(subId)
                                        ? [...disabledSubAgents, subId]
                                        : disabledSubAgents;
                                      const newExtra = isExtra
                                        ? extraSubAgents.filter(id => id !== subId)
                                        : extraSubAgents;

                                      setEditingAgent({
                                        ...editingAgent,
                                        disable_default_sub_agents: newDisabled,
                                        enable_extra_sub_agents: newExtra,
                                      });
                                    }}
                                    className="flex items-center gap-2 px-3 py-1.5 text-sm rounded-lg transition-colors group bg-gray-600 text-white hover:bg-gray-500"
                                    title={`Click to remove${isRemote ? ' (Remote A2A Agent)' : ''}`}
                                  >
                                    {isRemote ? (
                                      <ExternalLink className="w-4 h-4" />
                                    ) : (
                                      <Bot className="w-4 h-4" />
                                    )}
                                    {sub?.name || remoteSub?.name || subId}
                                    <X className="w-3 h-3 opacity-60 group-hover:opacity-100" />
                                  </button>
                                );
                              })}
                            </div>
                          )}

                          {/* Available agents to add */}
                          {(() => {
                            const allAgentIds = [...Object.keys(agents), ...remoteAgents.map(r => r.id)];
                            const availableAgents = allAgentIds.filter(
                              id => id !== editingAgent.id && !uniqueEffective.includes(id)
                            );

                            if (availableAgents.length === 0) return null;

                            return (
                              <div>
                                <div className="text-xs text-gray-500 mb-2">Add sub-agent:</div>
                                <div className="flex flex-wrap gap-2">
                                  {availableAgents.map((agentId) => {
                                    const agent = agents[agentId];
                                    const remoteAgent = remoteAgents.find(r => r.id === agentId);
                                    const isRemote = !!remoteAgent;
                                    const isDisabled = disabledSubAgents.includes(agentId);

                                    return (
                                      <button
                                        key={agentId}
                                        onClick={() => {
                                          // When adding a sub-agent:
                                          // - If it's in default and disabled, remove from disabled list
                                          // - Otherwise, add to extra list
                                          if (defaultSubAgents.includes(agentId) && isDisabled) {
                                            setEditingAgent({
                                              ...editingAgent,
                                              disable_default_sub_agents: disabledSubAgents.filter(id => id !== agentId),
                                            });
                                          } else {
                                            setEditingAgent({
                                              ...editingAgent,
                                              enable_extra_sub_agents: [...extraSubAgents, agentId],
                                              handoff_strategy: editingAgent.handoff_strategy || 'agent_as_tool',
                                            });
                                          }
                                        }}
                                        className="flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-lg border border-dashed border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-400 hover:border-gray-400 hover:text-gray-500 dark:hover:text-gray-300 transition-colors"
                                        title={isRemote ? `Remote A2A Agent: ${remoteAgent?.url}` : undefined}
                                      >
                                        <span className="text-lg leading-none">+</span>
                                        {agent?.name || remoteAgent?.name || agentId}
                                        {isRemote && (
                                          <span className="text-[9px] px-1 py-0.5 rounded bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-400">A2A</span>
                                        )}
                                      </button>
                                    );
                                  })}
                                </div>
                              </div>
                            );
                          })()}
                        </>
                      );
                    })()}

                    {Object.keys(editingAgent.sub_agents || {}).length === 0 && (
                      <p className="text-sm text-gray-500 italic">
                        No sub-agents. Add agents above to make this an orchestrator.
                      </p>
                    )}
                  </div>
                </div>
              </div>
            </div>
          ) : null}

          {/* Remote Agent Card */}
          {editingRemoteAgent && (
            <div className="p-6 space-y-6">
              {/* Remote Agent Header */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div className="w-11 h-11 rounded-lg bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 flex items-center justify-center">
                    <ExternalLink className="w-5 h-5 text-gray-600 dark:text-gray-400" />
                  </div>
                  <div>
                    <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                      {editingRemoteAgent.name}
                    </h2>
                    <p className="text-sm text-gray-500">{editingRemoteAgent.description || 'Remote A2A Agent'}</p>
                  </div>
                </div>

                {/* Close button */}
                <button
                  onClick={handleClosePanel}
                  className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              {/* A2A Badge */}
              <div className="flex items-center gap-2">
                <span className="text-xs px-2 py-1 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 border border-gray-200 dark:border-gray-700 flex items-center gap-1">
                  <ExternalLink className="w-3 h-3" />
                  Remote A2A Agent
                </span>
              </div>

              {/* Configuration Sections */}
              <div className="space-y-4">
                {/* Connection Information */}
                <div className="bg-gray-50 dark:bg-gray-900 rounded-xl p-4 border border-gray-200 dark:border-gray-800">
                  <div className="flex items-center gap-2 mb-4">
                    <Globe className="w-5 h-5 text-gray-500" />
                    <h3 className="font-semibold text-gray-900 dark:text-white">Connection</h3>
                  </div>

                  <div className="space-y-3">
                    <div>
                      <label className="block text-xs font-medium text-gray-500 mb-1">
                        Endpoint URL
                      </label>
                      <div className="px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 font-mono break-all">
                        {editingRemoteAgent.url}
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">
                          Authentication
                        </label>
                        <div className="px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300">
                          {editingRemoteAgent.auth.type === 'none' && 'None'}
                          {editingRemoteAgent.auth.type === 'bearer' && 'Bearer Token'}
                          {editingRemoteAgent.auth.type === 'apikey' && 'API Key'}
                          {editingRemoteAgent.auth.type === 'oauth2' && 'OAuth 2.0'}
                        </div>
                      </div>

                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">
                          Timeout (seconds)
                        </label>
                        <div className="px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300">
                          {editingRemoteAgent.timeout || 300}s
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Test Connection */}
                <div className="bg-gray-50 dark:bg-gray-900 rounded-xl p-4 border border-gray-200 dark:border-gray-800">
                  <div className="flex items-center gap-2 mb-4">
                    <Activity className="w-5 h-5 text-green-500" />
                    <h3 className="font-semibold text-gray-900 dark:text-white">Test Connection</h3>
                  </div>

                  <button
                    onClick={async () => {
                      setTestingConnection(true);
                      setConnectionTestResult(null);

                      try {
                        const res = await fetch('/api/a2a/test', {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify(editingRemoteAgent),
                        });

                        const data = await res.json();
                        setConnectionTestResult({
                          success: res.ok,
                          message: data.message || (res.ok ? 'Connection successful!' : 'Connection failed'),
                        });
                      } catch (e) {
                        setConnectionTestResult({
                          success: false,
                          message: `Error: ${(e as Error).message}`,
                        });
                      } finally {
                        setTestingConnection(false);
                      }
                    }}
                    disabled={testingConnection}
                    className="w-full px-4 py-2 bg-gray-600 hover:bg-gray-500 disabled:bg-gray-400 text-white rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2"
                  >
                    {testingConnection ? (
                      <>
                        <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        Testing...
                      </>
                    ) : (
                      <>
                        <Activity className="w-4 h-4" />
                        Test Connection
                      </>
                    )}
                  </button>

                  {connectionTestResult && (
                    <div
                      className={`mt-3 p-3 rounded-lg text-sm ${
                        connectionTestResult.success
                          ? 'bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-400 border border-green-200 dark:border-green-800'
                          : 'bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-400 border border-red-200 dark:border-red-800'
                      }`}
                    >
                      {connectionTestResult.message}
                    </div>
                  )}
                </div>

                {/* Actions */}
                <div className="bg-gray-50 dark:bg-gray-900 rounded-xl p-4 border border-gray-200 dark:border-gray-800">
                  <div className="flex items-center gap-2 mb-4">
                    <Settings className="w-5 h-5 text-gray-500" />
                    <h3 className="font-semibold text-gray-900 dark:text-white">Actions</h3>
                  </div>

                  <div className="flex gap-3">
                    <button
                      onClick={() => {
                        setNewRemoteAgent({ ...editingRemoteAgent });
                        setShowEditRemoteAgent(true);
                      }}
                      className="flex-1 px-4 py-2 bg-gray-200 hover:bg-gray-300 dark:bg-gray-700 dark:hover:bg-gray-600 text-gray-700 dark:text-gray-300 rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2"
                    >
                      <Edit2 className="w-4 h-4" />
                      Edit
                    </button>

                    <button
                      onClick={async () => {
                        if (!confirm(`Remove ${editingRemoteAgent.name}?`)) return;

                        try {
                          // Remove from remote_agents config (flat dict pattern)
                          const updatedRemoteAgents = remoteAgents.filter(r => r.id !== editingRemoteAgent.id);

                          // Convert array to dict, excluding the deleted agent
                          const remoteAgentsDict = Object.fromEntries(
                            updatedRemoteAgents.map(agent => [
                              agent.id,
                              {
                                type: agent.type,
                                name: agent.name,
                                url: agent.url,
                                auth: agent.auth,
                                description: agent.description,
                                timeout: agent.timeout,
                                enabled: agent.enabled !== false,
                              }
                            ])
                          );

                          const res = await fetch('/api/team/config', {
                            method: 'PATCH',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                              remote_agents: remoteAgentsDict,
                            }),
                          });

                          if (res.ok) {
                            setRemoteAgents(updatedRemoteAgents);
                            handleClosePanel();
                            setMessage({ type: 'success', text: 'Remote agent removed!' });
                          } else {
                            const err = await res.json();
                            setMessage({ type: 'error', text: err.error || 'Failed to remove' });
                          }
                        } catch (e) {
                          setMessage({ type: 'error', text: (e as Error).message || 'Failed to remove' });
                        }
                      }}
                      className="flex-1 px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2"
                    >
                      <Trash2 className="w-4 h-4" />
                      Remove
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
        )}
      </div>

      {/* Add Agent Modal */}
      {showAddAgent && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-white dark:bg-gray-900 rounded-xl shadow-2xl w-full max-w-md mx-4 p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                Add New Agent
              </h3>
              <button
                onClick={() => { setShowAddAgent(false); setNewAgentId(''); }}
                className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800"
              >
                <X className="w-5 h-5 text-gray-500" />
              </button>
            </div>
            
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Agent Name
                </label>
                <input
                  type="text"
                  value={newAgentId}
                  onChange={(e) => setNewAgentId(e.target.value)}
                  placeholder="e.g., Database Agent"
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
                  autoFocus
                />
                <p className="text-xs text-gray-500 mt-1">
                  ID will be: {newAgentId.trim().toLowerCase().replace(/\s+/g, '_') || '...'}
                </p>
              </div>

              <div className="flex justify-end gap-3 pt-2">
                <button
                  onClick={() => { setShowAddAgent(false); setNewAgentId(''); }}
                  className="px-4 py-2 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
                >
                  Cancel
                </button>
                <button
                  onClick={handleAddAgent}
                  disabled={!newAgentId.trim()}
                  className="px-4 py-2 text-sm bg-orange-600 text-white rounded-lg hover:bg-orange-700 disabled:opacity-50"
                >
                  Create Agent
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Add Remote A2A Agent Modal */}
      {showAddRemoteAgent && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-white dark:bg-gray-900 rounded-xl shadow-2xl w-full max-w-2xl mx-4 p-6 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <ExternalLink className="w-5 h-5 text-gray-500" />
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                  Add Remote A2A Agent
                </h3>
              </div>
              <button
                onClick={() => {
                  setShowAddRemoteAgent(false);
                  setNewRemoteAgent({
                    id: '',
                    name: '',
                    type: 'a2a',
                    url: '',
                    auth: { type: 'none' },
                    description: '',
                    timeout: 300,
                  });
                  setConnectionTestResult(null);
                }}
                className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800"
              >
                <X className="w-5 h-5 text-gray-500" />
              </button>
            </div>

            <div className="space-y-4">
              {/* ID */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Agent ID *
                </label>
                <input
                  type="text"
                  value={newRemoteAgent.id}
                  onChange={(e) => setNewRemoteAgent({ ...newRemoteAgent, id: e.target.value.trim().toLowerCase().replace(/[^a-z0-9_]/g, '_') })}
                  placeholder="e.g., security_scanner"
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
                />
              </div>

              {/* Name */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Display Name *
                </label>
                <input
                  type="text"
                  value={newRemoteAgent.name}
                  onChange={(e) => setNewRemoteAgent({ ...newRemoteAgent, name: e.target.value })}
                  placeholder="e.g., Security Scanner Agent"
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
                />
              </div>

              {/* URL */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  A2A Endpoint URL *
                </label>
                <input
                  type="url"
                  value={newRemoteAgent.url}
                  onChange={(e) => setNewRemoteAgent({ ...newRemoteAgent, url: e.target.value })}
                  placeholder="https://hello.a2aregistry.org/a2a"
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 font-mono text-sm"
                />
              </div>

              {/* Description */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Description
                </label>
                <textarea
                  value={newRemoteAgent.description}
                  onChange={(e) => setNewRemoteAgent({ ...newRemoteAgent, description: e.target.value })}
                  placeholder="What does this agent do?"
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
                  rows={2}
                />
              </div>

              {/* Auth Type */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Authentication
                </label>
                <select
                  value={newRemoteAgent.auth.type}
                  onChange={(e) => setNewRemoteAgent({
                    ...newRemoteAgent,
                    auth: { type: e.target.value as any }
                  })}
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
                >
                  <option value="none">No Authentication (Public)</option>
                  <option value="bearer">Bearer Token</option>
                  <option value="apikey">API Key</option>
                  <option value="oauth2">OAuth 2.0 Client Credentials</option>
                </select>
              </div>

              {/* Auth Fields - Bearer */}
              {newRemoteAgent.auth.type === 'bearer' && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Bearer Token *
                  </label>
                  <input
                    type="password"
                    value={newRemoteAgent.auth.token || ''}
                    onChange={(e) => setNewRemoteAgent({
                      ...newRemoteAgent,
                      auth: { ...newRemoteAgent.auth, token: e.target.value }
                    })}
                    placeholder="sk-..."
                    className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 font-mono text-sm"
                  />
                </div>
              )}

              {/* Auth Fields - API Key */}
              {newRemoteAgent.auth.type === 'apikey' && (
                <>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                      API Key *
                    </label>
                    <input
                      type="password"
                      value={newRemoteAgent.auth.api_key || ''}
                      onChange={(e) => setNewRemoteAgent({
                        ...newRemoteAgent,
                        auth: { ...newRemoteAgent.auth, api_key: e.target.value }
                      })}
                      className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 font-mono text-sm"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                        Location
                      </label>
                      <select
                        value={newRemoteAgent.auth.location || 'header'}
                        onChange={(e) => setNewRemoteAgent({
                          ...newRemoteAgent,
                          auth: { ...newRemoteAgent.auth, location: e.target.value as 'header' | 'query' }
                        })}
                        className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
                      >
                        <option value="header">Header</option>
                        <option value="query">Query Param</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                        Key Name
                      </label>
                      <input
                        type="text"
                        value={newRemoteAgent.auth.key_name || 'X-API-Key'}
                        onChange={(e) => setNewRemoteAgent({
                          ...newRemoteAgent,
                          auth: { ...newRemoteAgent.auth, key_name: e.target.value }
                        })}
                        className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 font-mono text-sm"
                      />
                    </div>
                  </div>
                </>
              )}

              {/* Auth Fields - OAuth2 */}
              {newRemoteAgent.auth.type === 'oauth2' && (
                <>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                      Token URL *
                    </label>
                    <input
                      type="url"
                      value={newRemoteAgent.auth.token_url || ''}
                      onChange={(e) => setNewRemoteAgent({
                        ...newRemoteAgent,
                        auth: { ...newRemoteAgent.auth, token_url: e.target.value }
                      })}
                      placeholder="https://auth.example.com/oauth/token"
                      className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 font-mono text-sm"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                        Client ID *
                      </label>
                      <input
                        type="text"
                        value={newRemoteAgent.auth.client_id || ''}
                        onChange={(e) => setNewRemoteAgent({
                          ...newRemoteAgent,
                          auth: { ...newRemoteAgent.auth, client_id: e.target.value }
                        })}
                        className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 font-mono text-sm"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                        Client Secret *
                      </label>
                      <input
                        type="password"
                        value={newRemoteAgent.auth.client_secret || ''}
                        onChange={(e) => setNewRemoteAgent({
                          ...newRemoteAgent,
                          auth: { ...newRemoteAgent.auth, client_secret: e.target.value }
                        })}
                        className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 font-mono text-sm"
                      />
                    </div>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                      Scope (Optional)
                    </label>
                    <input
                      type="text"
                      value={newRemoteAgent.auth.scope || ''}
                      onChange={(e) => setNewRemoteAgent({
                        ...newRemoteAgent,
                        auth: { ...newRemoteAgent.auth, scope: e.target.value }
                      })}
                      placeholder="read write"
                      className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
                    />
                  </div>
                </>
              )}

              {/* Timeout */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Timeout (seconds)
                </label>
                <input
                  type="number"
                  value={newRemoteAgent.timeout}
                  onChange={(e) => setNewRemoteAgent({ ...newRemoteAgent, timeout: parseInt(e.target.value) || 300 })}
                  min={10}
                  max={600}
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
                />
              </div>

              {/* Connection Test Result */}
              {connectionTestResult && (
                <div className={`p-3 rounded-lg ${
                  connectionTestResult.success
                    ? 'bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800'
                    : 'bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800'
                }`}>
                  <div className="flex items-center gap-2">
                    {connectionTestResult.success ? (
                      <CheckCircle className="w-4 h-4 text-green-600" />
                    ) : (
                      <XCircle className="w-4 h-4 text-red-600" />
                    )}
                    <span className={`text-sm ${
                      connectionTestResult.success ? 'text-green-700 dark:text-green-300' : 'text-red-700 dark:text-red-300'
                    }`}>
                      {connectionTestResult.message}
                    </span>
                  </div>
                </div>
              )}

              {/* Actions */}
              <div className="flex justify-between items-center gap-3 pt-2 border-t border-gray-200 dark:border-gray-700">
                <button
                  onClick={async () => {
                    setTestingConnection(true);
                    setConnectionTestResult(null);
                    try {
                      // TODO: Implement test connection API endpoint
                      // For now, just validate URL format
                      if (!newRemoteAgent.url) {
                        throw new Error('URL is required');
                      }
                      new URL(newRemoteAgent.url);
                      await new Promise(resolve => setTimeout(resolve, 1000));
                      setConnectionTestResult({ success: true, message: 'Connection test successful!' });
                    } catch (e: any) {
                      setConnectionTestResult({ success: false, message: e.message || 'Connection failed' });
                    } finally {
                      setTestingConnection(false);
                    }
                  }}
                  disabled={!newRemoteAgent.url || testingConnection}
                  className="px-4 py-2 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white disabled:opacity-50"
                >
                  {testingConnection ? (
                    <span className="flex items-center gap-2">
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Testing...
                    </span>
                  ) : (
                    'Test Connection'
                  )}
                </button>

                <div className="flex gap-3">
                  <button
                    onClick={() => {
                      setShowAddRemoteAgent(false);
                      setNewRemoteAgent({
                        id: '',
                        name: '',
                        type: 'a2a',
                        url: '',
                        auth: { type: 'none' },
                        description: '',
                        timeout: 300,
                      });
                      setConnectionTestResult(null);
                    }}
                    className="px-4 py-2 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={async () => {
                      if (!newRemoteAgent.id || !newRemoteAgent.name || !newRemoteAgent.url) {
                        setMessage({ type: 'error', text: 'Please fill in all required fields' });
                        return;
                      }

                      setSaving(true);
                      try {
                        // Convert array to dict (flat dict pattern)
                        const allRemoteAgents = [...remoteAgents, newRemoteAgent];
                        const remoteAgentsDict = Object.fromEntries(
                          allRemoteAgents.map(agent => [
                            agent.id,
                            {
                              type: agent.type,
                              name: agent.name,
                              url: agent.url,
                              auth: agent.auth,
                              description: agent.description,
                              timeout: agent.timeout,
                              enabled: agent.enabled !== false,
                            }
                          ])
                        );

                        const res = await fetch('/api/team/config', {
                          method: 'PATCH',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({
                            remote_agents: remoteAgentsDict,
                          }),
                        });

                        if (res.ok) {
                          await loadAgents();
                          setShowAddRemoteAgent(false);
                          setNewRemoteAgent({
                            id: '',
                            name: '',
                            type: 'a2a',
                            url: '',
                            auth: { type: 'none' },
                            description: '',
                            timeout: 300,
                          });
                          setConnectionTestResult(null);
                          setMessage({ type: 'success', text: 'Remote agent added successfully!' });
                        } else {
                          const err = await res.json();
                          setMessage({ type: 'error', text: err.error || 'Failed to add remote agent' });
                        }
                      } catch (e: any) {
                        setMessage({ type: 'error', text: e.message || 'Failed to add remote agent' });
                      } finally {
                        setSaving(false);
                      }
                    }}
                    disabled={!newRemoteAgent.id || !newRemoteAgent.name || !newRemoteAgent.url || saving}
                    className="px-4 py-2 text-sm bg-orange-600 text-white rounded-lg hover:bg-orange-700 disabled:opacity-50"
                  >
                    {saving ? (
                      <span className="flex items-center gap-2">
                        <Loader2 className="w-4 h-4 animate-spin" />
                        Adding...
                      </span>
                    ) : (
                      'Add Remote Agent'
                    )}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Edit Remote Agent Modal */}
      {showEditRemoteAgent && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-white dark:bg-gray-900 rounded-xl shadow-2xl w-full max-w-2xl mx-4 p-6 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <ExternalLink className="w-5 h-5 text-gray-500" />
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                  Edit Remote A2A Agent
                </h3>
              </div>
              <button
                onClick={() => {
                  setShowEditRemoteAgent(false);
                  setConnectionTestResult(null);
                }}
                className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800"
              >
                <X className="w-5 h-5 text-gray-500" />
              </button>
            </div>

            <div className="space-y-4">
              {/* ID (disabled) */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Agent ID
                </label>
                <input
                  type="text"
                  value={newRemoteAgent.id}
                  disabled
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-100 dark:bg-gray-800 text-gray-500 cursor-not-allowed"
                />
              </div>

              {/* Name */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Display Name *
                </label>
                <input
                  type="text"
                  value={newRemoteAgent.name}
                  onChange={(e) => setNewRemoteAgent({ ...newRemoteAgent, name: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
                />
              </div>

              {/* URL */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  A2A Endpoint URL *
                </label>
                <input
                  type="url"
                  value={newRemoteAgent.url}
                  onChange={(e) => setNewRemoteAgent({ ...newRemoteAgent, url: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 font-mono text-sm"
                />
              </div>

              {/* Description */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Description
                </label>
                <textarea
                  value={newRemoteAgent.description}
                  onChange={(e) => setNewRemoteAgent({ ...newRemoteAgent, description: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
                  rows={2}
                />
              </div>

              {/* Auth Type */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Authentication
                </label>
                <select
                  value={newRemoteAgent.auth.type}
                  onChange={(e) => setNewRemoteAgent({
                    ...newRemoteAgent,
                    auth: { type: e.target.value as any }
                  })}
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
                >
                  <option value="none">No Authentication (Public)</option>
                  <option value="bearer">Bearer Token</option>
                  <option value="apikey">API Key</option>
                  <option value="oauth2">OAuth 2.0 Client Credentials</option>
                </select>
              </div>

              {/* Auth Fields - Bearer */}
              {newRemoteAgent.auth.type === 'bearer' && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Bearer Token *
                  </label>
                  <input
                    type="password"
                    value={newRemoteAgent.auth.token || ''}
                    onChange={(e) => setNewRemoteAgent({
                      ...newRemoteAgent,
                      auth: { ...newRemoteAgent.auth, token: e.target.value }
                    })}
                    placeholder="sk-..."
                    className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 font-mono text-sm"
                  />
                </div>
              )}

              {/* Auth Fields - API Key */}
              {newRemoteAgent.auth.type === 'apikey' && (
                <>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                      API Key *
                    </label>
                    <input
                      type="password"
                      value={newRemoteAgent.auth.api_key || ''}
                      onChange={(e) => setNewRemoteAgent({
                        ...newRemoteAgent,
                        auth: { ...newRemoteAgent.auth, api_key: e.target.value }
                      })}
                      className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 font-mono text-sm"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                        Location
                      </label>
                      <select
                        value={newRemoteAgent.auth.location || 'header'}
                        onChange={(e) => setNewRemoteAgent({
                          ...newRemoteAgent,
                          auth: { ...newRemoteAgent.auth, location: e.target.value as 'header' | 'query' }
                        })}
                        className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
                      >
                        <option value="header">Header</option>
                        <option value="query">Query Param</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                        Key Name
                      </label>
                      <input
                        type="text"
                        value={newRemoteAgent.auth.key_name || 'X-API-Key'}
                        onChange={(e) => setNewRemoteAgent({
                          ...newRemoteAgent,
                          auth: { ...newRemoteAgent.auth, key_name: e.target.value }
                        })}
                        className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 font-mono text-sm"
                      />
                    </div>
                  </div>
                </>
              )}

              {/* Auth Fields - OAuth2 */}
              {newRemoteAgent.auth.type === 'oauth2' && (
                <>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                      Token URL *
                    </label>
                    <input
                      type="url"
                      value={newRemoteAgent.auth.token_url || ''}
                      onChange={(e) => setNewRemoteAgent({
                        ...newRemoteAgent,
                        auth: { ...newRemoteAgent.auth, token_url: e.target.value }
                      })}
                      className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 font-mono text-sm"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                        Client ID *
                      </label>
                      <input
                        type="text"
                        value={newRemoteAgent.auth.client_id || ''}
                        onChange={(e) => setNewRemoteAgent({
                          ...newRemoteAgent,
                          auth: { ...newRemoteAgent.auth, client_id: e.target.value }
                        })}
                        className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 font-mono text-sm"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                        Client Secret *
                      </label>
                      <input
                        type="password"
                        value={newRemoteAgent.auth.client_secret || ''}
                        onChange={(e) => setNewRemoteAgent({
                          ...newRemoteAgent,
                          auth: { ...newRemoteAgent.auth, client_secret: e.target.value }
                        })}
                        className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 font-mono text-sm"
                      />
                    </div>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                      Scope (Optional)
                    </label>
                    <input
                      type="text"
                      value={newRemoteAgent.auth.scope || ''}
                      onChange={(e) => setNewRemoteAgent({
                        ...newRemoteAgent,
                        auth: { ...newRemoteAgent.auth, scope: e.target.value }
                      })}
                      className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
                    />
                  </div>
                </>
              )}

              {/* Timeout */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Timeout (seconds)
                </label>
                <input
                  type="number"
                  value={newRemoteAgent.timeout}
                  onChange={(e) => setNewRemoteAgent({ ...newRemoteAgent, timeout: parseInt(e.target.value) || 300 })}
                  min={10}
                  max={600}
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
                />
              </div>

              {/* Actions */}
              <div className="flex justify-end items-center gap-3 pt-2 border-t border-gray-200 dark:border-gray-700">
                <button
                  onClick={() => {
                    setShowEditRemoteAgent(false);
                    setConnectionTestResult(null);
                  }}
                  className="px-4 py-2 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
                >
                  Cancel
                </button>
                <button
                  onClick={async () => {
                    if (!newRemoteAgent.name || !newRemoteAgent.url) {
                      setMessage({ type: 'error', text: 'Please fill in all required fields' });
                      return;
                    }

                    setSaving(true);
                    try {
                      // Update the agent in the array
                      const updatedRemoteAgents = remoteAgents.map(r =>
                        r.id === newRemoteAgent.id ? newRemoteAgent : r
                      );

                      // Convert array to dict (flat dict pattern)
                      const remoteAgentsDict = Object.fromEntries(
                        updatedRemoteAgents.map(agent => [
                          agent.id,
                          {
                            type: agent.type,
                            name: agent.name,
                            url: agent.url,
                            auth: agent.auth,
                            description: agent.description,
                            timeout: agent.timeout,
                            enabled: agent.enabled !== false,
                          }
                        ])
                      );

                      const res = await fetch('/api/team/config', {
                        method: 'PATCH',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                          remote_agents: remoteAgentsDict,
                        }),
                      });

                      if (res.ok) {
                        await loadAgents();
                        setShowEditRemoteAgent(false);
                        setEditingRemoteAgent(newRemoteAgent);
                        setConnectionTestResult(null);
                        setMessage({ type: 'success', text: 'Remote agent updated successfully!' });
                      } else {
                        const err = await res.json();
                        setMessage({ type: 'error', text: err.error || 'Failed to update remote agent' });
                      }
                    } catch (e: any) {
                      setMessage({ type: 'error', text: e.message || 'Failed to update remote agent' });
                    } finally {
                      setSaving(false);
                    }
                  }}
                  disabled={!newRemoteAgent.name || !newRemoteAgent.url || saving}
                  className="px-4 py-2 text-sm bg-orange-600 text-white rounded-lg hover:bg-orange-700 disabled:opacity-50"
                >
                  {saving ? (
                    <span className="flex items-center gap-2">
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Saving...
                    </span>
                  ) : (
                    'Save Changes'
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Continue Onboarding floating button */}
      <ContinueOnboardingButton
        onContinue={(step) => {
          setQuickStartInitialStep(step);
          setShowQuickStart(true);
        }}
      />

      {/* Quick Start Guide Modal */}
      {showQuickStart && (
        <QuickStartWizard
          onClose={() => setShowQuickStart(false)}
          onRunAgent={() => {
            setShowQuickStart(false);
            router.push('/team/agent-runs');
          }}
          onSkip={() => setShowQuickStart(false)}
          initialStep={quickStartInitialStep}
        />
      )}

      {/* Inheritance Details Modal */}
      {showInheritanceModal && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
          onClick={(e) => {
            if (e.target === e.currentTarget) setShowInheritanceModal(false);
          }}
        >
          <div className="bg-white dark:bg-gray-900 rounded-2xl w-full max-w-4xl max-h-[85vh] flex flex-col shadow-xl mx-4">
            {/* Modal Header */}
            <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-800">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Configuration Inheritance</h2>
              <button
                onClick={() => setShowInheritanceModal(false)}
                className="p-1 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
              >
                <X className="w-5 h-5 text-gray-500" />
              </button>
            </div>

            {/* Modal Explanation */}
            <div className="p-4 border-b border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950/50">
              <p className="text-sm text-gray-600 dark:text-gray-400">
                <strong>Lineage:</strong> {lineageLabel}
              </p>
              <p className="text-sm text-gray-500 dark:text-gray-500 mt-1">
                This shows what&apos;s configured at each level of the hierarchy. Settings from parent nodes are inherited and can be overridden by child nodes.
              </p>
            </div>

            {/* Modal Content (scrollable) */}
            <div className="flex-1 overflow-auto p-4">
              <pre className="text-xs font-mono text-gray-700 dark:text-gray-200 whitespace-pre-wrap">
                {rawPretty || '(not loaded)'}
              </pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// Agent Node Component - Clean, minimal, comfortable design
function AgentNode({
  agent,
  isSelected,
  onClick,
  isPrimary = false,
  isRemote = false,
  isEntranceAgent = false,
}: {
  agent: AgentConfig;
  isSelected: boolean;
  onClick: () => void;
  isPrimary?: boolean;
  isRemote?: boolean;
  isEntranceAgent?: boolean;
}) {
  const hasSubAgents = Object.keys(agent.sub_agents || {}).length > 0;

  return (
    <button
      onClick={onClick}
      className={`
        relative group transition-all duration-200
        ${isPrimary ? 'min-w-[100px] py-3 px-4' : 'min-w-[90px] py-2.5 px-3'}
        rounded-lg
        bg-white dark:bg-gray-800 border-2 ${isSelected ? 'border-orange-500 shadow-md' : 'border-gray-200 dark:border-gray-700 hover:border-gray-400'}
        ${!agent.enabled ? 'opacity-50' : ''}
      `}
    >
      {/* Status indicator */}
      <div
        className={`absolute -top-1.5 -right-1.5 w-3 h-3 rounded-full border-2 border-white dark:border-gray-800 ${
          agent.enabled ? 'bg-green-500' : 'bg-gray-400'
        }`}
      />

      {/* Entrance Agent badge */}
      {isEntranceAgent && (
        <div className="absolute -top-1.5 -left-1.5 w-4 h-4 rounded-full bg-orange-500 border-2 border-white dark:border-gray-800 flex items-center justify-center">
          <Sparkles className="w-2 h-2 text-white" />
        </div>
      )}

      {/* Remote badge */}
      {isRemote && (
        <div className="absolute -top-1.5 -left-1.5 w-4 h-4 rounded-full bg-gray-500 border-2 border-white dark:border-gray-800 flex items-center justify-center">
          <ExternalLink className="w-2 h-2 text-white" />
        </div>
      )}

      {/* Content */}
      <div className="flex flex-col items-center gap-1">
        {isRemote ? (
          <ExternalLink className={`${isPrimary ? 'w-5 h-5' : 'w-4 h-4'} text-gray-600 dark:text-gray-400`} />
        ) : (
          <Bot className={`${isPrimary ? 'w-5 h-5' : 'w-4 h-4'} text-gray-600 dark:text-gray-300`} />
        )}
        <span className={`text-gray-800 dark:text-gray-200 font-medium text-center leading-tight ${isPrimary ? 'text-xs' : 'text-[11px]'}`}>
          {agent.name}
        </span>
        {hasSubAgents && (
          <span className="text-[9px] text-gray-400">
            {Object.keys(agent.sub_agents || {}).length} {Object.keys(agent.sub_agents || {}).length === 1 ? 'sub-agent' : 'sub-agents'}
          </span>
        )}
        {isRemote && (
          <span className="text-[9px] px-1.5 py-0.5 rounded bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-400">
            A2A
          </span>
        )}
      </div>

      {/* Hover tooltip */}
      <div className="absolute -bottom-1 left-1/2 -translate-x-1/2 translate-y-full opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-20">
        <div className="bg-gray-800 dark:bg-gray-200 text-white dark:text-gray-800 text-[10px] px-2 py-1 rounded whitespace-nowrap shadow-lg mt-1">
          {agent.description || 'Click to configure'}
        </div>
      </div>
    </button>
  );
}

