'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import Link from 'next/link';
import { useIdentity } from '@/lib/useIdentity';
import { Eye, EyeOff, Check, X, AlertTriangle, Settings, Network, Code, Bot, Sparkles, ExternalLink, ArrowLeft, Home, LayoutTemplate, Plus, Trash2, ToggleLeft, ToggleRight, Server, Zap, Brain, Wrench, Users, Loader2, CheckCircle, XCircle } from 'lucide-react';

interface AgentConfig {
  id: string;
  enabled: boolean;
  name: string;
  description?: string;
  model: { name: string; temperature: number; max_tokens?: number };
  prompt: { system: string; prefix: string; suffix: string };
  max_turns: number;
  tools: { [tool_id: string]: boolean };  // Changed from {enabled: [], disabled: []}
  sub_agents: { [agent_id: string]: boolean };  // Changed from string[]
  mcps?: { [mcp_id: string]: boolean };  // NEW field
  disable_default_tools?: string[];  // Tools from default set to disable
  enable_extra_tools?: string[];  // Extra tools to enable
  disable_default_sub_agents?: string[];  // Sub-agents from default set to disable
  enable_extra_sub_agents?: string[];  // Extra sub-agents to enable
  handoff_strategy?: string;  // Strategy for sub-agent handoff
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

// Integration field schema
interface IntegrationField {
  name: string;
  type: 'string' | 'secret' | 'boolean' | 'integer';
  required: boolean;
  default?: string | boolean | number;
  display_name: string;
  description?: string;
  placeholder?: string;
  allowed_values?: string[];
  level?: string;
}

// Integration schema from API
interface IntegrationSchemaResponse {
  id: string;
  name: string;
  category: string;
  description: string;
  docs_url?: string;
  icon_url?: string;
  display_order: number;
  featured: boolean;
  fields: IntegrationField[];
}

// Transformed integration schema for rendering
interface IntegrationSchema {
  name: string;
  description: string;
  level: 'org' | 'team';
  org_fields: IntegrationField[];
  team_fields: IntegrationField[];
  docs_url?: string;
}

interface ToolMetadata {
  id: string;
  name: string;
  description: string;
  category: string;
  required_integrations: string[];
}

interface EffectiveConfig {
  agents: Record<string, AgentConfig>;
  // Team-level tool overrides (canonical format)
  tools?: Record<string, boolean>;
  // Built-in tools catalog from config service
  built_in_tools?: unknown[];
  // MCP servers in canonical dict format (keyed by mcp_id)
  mcp_servers?: Record<string, any>;
  // Remote A2A agents (flat dict by agent_id)
  remote_agents?: Record<string, any>;
  // Integrations
  integrations: Record<string, unknown>;
  runtime: Record<string, unknown>;
  // Entrance agent - which agent runs on webhook triggers
  entrance_agent?: string;
}

interface NodeConfig {
  node_id: string;
  node_type: string;
  config: Record<string, unknown>;
  version: number;
  updated_at: string | null;
  updated_by: string | null;
}

type ConfigTab = 'agents' | 'tools' | 'mcps' | 'integrations' | 'raw';

// Agent Node Component - Clean, minimal design for topology view
function AgentNode({
  agent,
  isSelected,
  onClick,
  isPrimary = false,
  allAgents,
  isEntranceAgent = false,
}: {
  agent: AgentConfig;
  isSelected: boolean;
  onClick: () => void;
  isPrimary?: boolean;
  allAgents?: Record<string, AgentConfig>;
  isEntranceAgent?: boolean;
}) {
  // Helper to get sub-agent count (object format with boolean values)
  // Only counts globally-enabled sub-agents
  const getSubAgentCount = (subAgents: any): number => {
    if (!subAgents) return 0;

    // sub_agents is an object with boolean values
    const subAgentIds = Object.keys(subAgents).filter(key => subAgents[key]);

    // Filter to only include globally-enabled agents
    if (allAgents) {
      return subAgentIds.filter(id => allAgents[id]?.enabled !== false).length;
    }

    return subAgentIds.length;
  };

  const subAgentCount = getSubAgentCount(agent.sub_agents);
  const hasSubAgents = subAgentCount > 0;

  return (
    <button
      onClick={onClick}
      className={`
        relative group transition-all duration-200
        ${isPrimary ? 'min-w-[100px] py-3 px-4' : 'min-w-[90px] py-2.5 px-3'}
        rounded-lg
        bg-slate-800 border-2
        ${isSelected ? 'border-cyan-500 shadow-md' : 'border-slate-700 hover:border-cyan-400'}
        ${!agent.enabled ? 'opacity-50' : ''}
      `}
    >
      {/* Status indicator */}
      <div
        className={`absolute -top-1.5 -right-1.5 w-3 h-3 rounded-full border-2 border-slate-900 ${
          agent.enabled ? 'bg-green-500' : 'bg-slate-600'
        }`}
      />

      {/* Entrance Agent badge */}
      {isEntranceAgent && (
        <div className="absolute -top-1.5 -left-1.5 w-4 h-4 rounded-full bg-amber-500 border-2 border-slate-900 flex items-center justify-center">
          <Sparkles className="w-2 h-2 text-white" />
        </div>
      )}

      {/* Content */}
      <div className="flex flex-col items-center gap-1">
        <Bot className={`${isPrimary ? 'w-5 h-5' : 'w-4 h-4'} text-slate-300`} />
        <span className={`text-slate-200 font-medium text-center leading-tight ${isPrimary ? 'text-xs' : 'text-[11px]'}`}>
          {agent.name}
        </span>
        {hasSubAgents && (
          <span className="text-[9px] text-slate-500">
            {subAgentCount} sub-agents
          </span>
        )}
      </div>

      {/* Hover tooltip */}
      <div className="absolute -bottom-1 left-1/2 -translate-x-1/2 translate-y-full opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-20">
        <div className="bg-slate-200 text-slate-800 text-[10px] px-2 py-1 rounded whitespace-nowrap shadow-lg mt-1">
          {agent.description || 'Click to configure'}
        </div>
      </div>
    </button>
  );
}

export default function AdminConfigPage() {
  const { identity, loading: identityLoading } = useIdentity();
  const [activeTab, setActiveTab] = useState<ConfigTab>('agents');
  const [effectiveConfig, setEffectiveConfig] = useState<EffectiveConfig | null>(null);
  const [rawConfig, setRawConfig] = useState<NodeConfig | null>(null);
  const [selectedNode, setSelectedNode] = useState<string>('');
  const [nodes, setNodes] = useState<{ node_id: string; node_type: string; name: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  
  // Editing states
  const [agentDraft, setAgentDraft] = useState<Partial<AgentConfig>>({});
  const [showAddAgent, setShowAddAgent] = useState(false);
  const [showAgentTypeMenu, setShowAgentTypeMenu] = useState(false);
  const [newAgentId, setNewAgentId] = useState('');
  const [showAddMcpModal, setShowAddMcpModal] = useState(false);
  const [newMcpForm, setNewMcpForm] = useState({
    name: '',
    description: '',
    command: '',
    args: '',
    env: '',
  });

  // Remote agent states
  const [showAddRemoteAgent, setShowAddRemoteAgent] = useState(false);
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

  // Agent topology view states
  const [agentViewMode, setAgentViewMode] = useState<'visual' | 'json'>('visual');
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [showPrompt, setShowPrompt] = useState(false);
  const [showToolPicker, setShowToolPicker] = useState(false);

  // Tools data
  const [toolMetadata, setToolMetadata] = useState<ToolMetadata[]>([]);
  const [toolPool, setToolPool] = useState<Array<{name: string; description: string; source: 'built-in' | 'mcp'}>>([]);
  const [loadingTools, setLoadingTools] = useState(false);
  const [mcpServers, setMcpServers] = useState<Record<string, any>>({});

  // Default prompts from agent code (used as placeholders when config is empty)
  const [defaultPrompts, setDefaultPrompts] = useState<Record<string, string>>({});

  // Integration editing states
  const [editingIntegration, setEditingIntegration] = useState<string | null>(null);
  const [integrationDraft, setIntegrationDraft] = useState<{ config: Record<string, string | boolean>; team_config: Record<string, string | boolean> }>({ config: {}, team_config: {} });
  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({});

  // Integration schemas from API
  const [integrationSchemas, setIntegrationSchemas] = useState<Record<string, IntegrationSchema>>({});
  const [loadingSchemas, setLoadingSchemas] = useState(true);

  const loadNodes = useCallback(async () => {
    if (!identity?.org_id) return;
    try {
      const res = await fetch(`/api/admin/orgs/${identity.org_id}/nodes`);
      if (res.ok) {
        const data = await res.json();
        // API returns array directly, not {nodes: [...]}
        const nodeList = Array.isArray(data) ? data : (data.nodes || []);
        setNodes(nodeList);
        // Select org root by default
        const orgNode = nodeList.find((n: { node_type: string }) => n.node_type === 'org');
        if (orgNode && !selectedNode) {
          setSelectedNode(orgNode.node_id);
        }
      } else {
        // If API fails, set loading to false to avoid infinite spinner
        setLoading(false);
        setError('Failed to load organization nodes');
      }
    } catch (e) {
      console.error('Failed to load nodes', e);
      setLoading(false);
      setError('Failed to load organization nodes');
    }
  }, [identity?.org_id, selectedNode]);

  const loadConfig = useCallback(async () => {
    if (!identity?.org_id || !selectedNode) return;
    setLoading(true);
    setError(null);
    
    try {
      // Load effective config
      const effectiveRes = await fetch(
        `/api/admin/orgs/${identity.org_id}/config/${selectedNode}/effective`
      );
      if (effectiveRes.ok) {
        const data = await effectiveRes.json();
        // Handle both wrapped format {effective_config: {...}} and direct dict format
        setEffectiveConfig(data.effective_config || data);
      }

      // Load raw config
      const rawRes = await fetch(
        `/api/admin/orgs/${identity.org_id}/config/${selectedNode}/raw`
      );
      if (rawRes.ok) {
        const data = await rawRes.json();
        setRawConfig(data);

        // Load remote agents from config (flat dict pattern)
        if (data.config?.remote_agents) {
          // Convert dict to array for state management
          const agentsArray = Object.entries(data.config.remote_agents)
            .filter(([_, config]: [string, any]) => config && typeof config === 'object')
            .map(([id, config]: [string, any]) => ({
              id,
              ...config,
            }));
          setRemoteAgents(agentsArray);
        } else {
          setRemoteAgents([]);
        }
      }
    } catch (e) {
      setError('Failed to load configuration');
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [identity?.org_id, selectedNode]);

  useEffect(() => {
    if (identity?.org_id) {
      loadNodes();
    }
  }, [identity?.org_id, loadNodes]);

  // Load integration schemas from API
  useEffect(() => {
    const loadIntegrationSchemas = async () => {
      setLoadingSchemas(true);
      try {
        const res = await fetch('/api/v1/integrations/schemas');
        if (res.ok) {
          const data = await res.json();
          // Transform API response to match rendering format
          const transformed: Record<string, IntegrationSchema> = {};
          for (const schema of (data.integrations || [])) {
            // Separate fields by level
            const orgFields = schema.fields.filter((f: IntegrationField) => f.level === 'org' || !f.level);
            const teamFields = schema.fields.filter((f: IntegrationField) => f.level === 'team');

            transformed[schema.id] = {
              name: schema.name,
              description: schema.description,
              level: teamFields.length > 0 ? 'team' : 'org',
              org_fields: orgFields,
              team_fields: teamFields,
              docs_url: schema.docs_url,
            };
          }
          setIntegrationSchemas(transformed);
        } else {
          console.error('Failed to load integration schemas:', res.status);
        }
      } catch (e) {
        console.error('Failed to load integration schemas:', e);
      } finally {
        setLoadingSchemas(false);
      }
    };
    loadIntegrationSchemas();
  }, []);

  const loadToolPool = useCallback(async () => {
    if (!identity?.org_id || !selectedNode) return;
    setLoadingTools(true);
    try {
      // For admin, we need to fetch tools from the node's team context
      // Use the same endpoint pattern as team
      const res = await fetch(`/api/admin/orgs/${identity.org_id}/nodes/${selectedNode}/tools`);
      if (res.ok) {
        const data = await res.json();
        const tools: Array<{name: string; description: string; source: 'built-in' | 'mcp'}> = (data.tools || []).map((tool: any) => ({
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
  }, [identity?.org_id, selectedNode]);

  useEffect(() => {
    if (selectedNode) {
      loadConfig();
      loadToolPool();
    }
  }, [selectedNode, loadConfig, loadToolPool]);

  useEffect(() => {
    // Extract MCP servers from effective config
    if (effectiveConfig?.mcp_servers) {
      setMcpServers(effectiveConfig.mcp_servers);
    }
  }, [effectiveConfig]);

  useEffect(() => {
    // Load tool metadata (all 178 built-in tools)
    const loadToolMetadata = async () => {
      try {
        const res = await fetch('/api/v1/tools/metadata');
        if (res.ok) {
          const data = await res.json();
          setToolMetadata(data.tools || []);
        }
      } catch (e) {
        console.error('Failed to load tool metadata:', e);
      }
    };
    loadToolMetadata();
  }, []);

  // Load default prompts from agent service (used as placeholders in UI)
  useEffect(() => {
    const loadDefaultPrompts = async () => {
      try {
        const res = await fetch('/api/agents/prompts/defaults');
        if (res.ok) {
          const data = await res.json();
          setDefaultPrompts(data.prompts || {});
        }
      } catch (e) {
        console.error('Failed to load default prompts:', e);
      }
    };
    loadDefaultPrompts();
  }, []);

  const saveConfig = async (patch: Record<string, unknown>) => {
    if (!identity?.org_id || !selectedNode) return;
    setSaving(true);
    setError(null);
    setSuccess(null);

    try {
      const res = await fetch(
        `/api/admin/orgs/${identity.org_id}/nodes/${selectedNode}/config`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ patch }),
        }
      );
      
      if (res.ok) {
        setSuccess('Configuration saved successfully');
        await loadConfig();
        setTimeout(() => setSuccess(null), 3000);
      } else {
        const data = await res.json();
        // Handle validation errors with structured error messages
        if (data.detail && typeof data.detail === 'object') {
          if (data.detail.errors && Array.isArray(data.detail.errors)) {
            // Show all error messages
            setError(data.detail.errors.join('\n'));
          } else if (data.detail.message) {
            setError(data.detail.message);
          } else {
            setError(JSON.stringify(data.detail));
          }
        } else {
          setError(data.detail || 'Failed to save configuration');
        }
      }
    } catch (e) {
      setError('Failed to save configuration');
      console.error(e);
    } finally {
      setSaving(false);
    }
  };

  const saveAgentConfig = async () => {
    if (!selectedAgentId || !agentDraft) return;
    await saveConfig({
      agents: {
        [selectedAgentId]: agentDraft,
      },
    });
    setSelectedAgentId(null);
    setAgentDraft({});
    setShowPrompt(false);
  };

  const handleCreateAgent = async () => {
    if (!newAgentId.trim()) {
      setError('Agent ID is required');
      return;
    }

    // Check if agent already exists
    if (effectiveConfig?.agents?.[newAgentId]) {
      setError(`Agent "${newAgentId}" already exists`);
      return;
    }

    // Create new agent with defaults (using new dict schema)
    const newAgent = {
      name: newAgentId.charAt(0).toUpperCase() + newAgentId.slice(1),
      description: '',
      enabled: true,
      model: {
        name: 'gpt-4o',
        temperature: 0.3,
        max_tokens: 16000,
      },
      prompt: {
        system: '',
        prefix: '',
        suffix: '',
      },
      tools: {
        think: true,
        llm_call: true,
        web_search: true,
      },
      sub_agents: {},
      mcps: {},
      max_turns: 20,
    };

    await saveConfig({
      agents: {
        [newAgentId]: newAgent,
      },
    });

    setShowAddAgent(false);
    setNewAgentId('');
  };

  const handleCreateMcp = async () => {
    if (!newMcpForm.name.trim() || !newMcpForm.command.trim()) {
      setError('Name and command are required');
      return;
    }

    const mcpId = newMcpForm.name.toLowerCase().replace(/\s+/g, '-');

    // Parse args and env
    const args = newMcpForm.args ? newMcpForm.args.split(',').map(a => a.trim()).filter(Boolean) : [];
    const env: Record<string, string> = {};
    if (newMcpForm.env) {
      newMcpForm.env.split('\n').forEach(line => {
        const [key, ...valueParts] = line.split('=');
        if (key && valueParts.length) {
          env[key.trim()] = valueParts.join('=').trim();
        }
      });
    }

    const newMcp = {
      name: newMcpForm.name,
      description: newMcpForm.description,
      enabled: true,
      command: newMcpForm.command,
      args,
      env,
    };

    // Add to mcp_servers dict (canonical format)
    const currentMcpServers = (effectiveConfig?.mcp_servers as Record<string, any>) || {};
    await saveConfig({
      mcp_servers: {
        ...currentMcpServers,
        [mcpId]: newMcp,
      },
    });

    setShowAddMcpModal(false);
    setNewMcpForm({ name: '', description: '', command: '', args: '', env: '' });
  };

  const handleToggleTool = async (toolId: string, currentlyEnabled: boolean) => {
    // Canonical format: tools is a dict {tool_id: bool}
    const currentTools = (effectiveConfig?.tools as Record<string, boolean>) || {};

    // Toggle the tool in the dict
    await saveConfig({
      tools: {
        ...currentTools,
        [toolId]: !currentlyEnabled,
      },
    });
  };

  const saveIntegrationConfig = async () => {
    if (!editingIntegration) return;
    await saveConfig({
      integrations: {
        [editingIntegration]: {
          config: integrationDraft.config,
          team_config: integrationDraft.team_config,
        },
      },
    });
    setEditingIntegration(null);
    setIntegrationDraft({ config: {}, team_config: {} });
    setShowSecrets({});
  };

  const openIntegrationEditor = (integrationId: string) => {
    const currentConfig = effectiveConfig?.integrations?.[integrationId] as {
      config?: Record<string, string | boolean>;
      team_config?: Record<string, string | boolean>;
    } | undefined;
    setEditingIntegration(integrationId);
    setIntegrationDraft({
      config: { ...(currentConfig?.config || {}) },
      team_config: { ...(currentConfig?.team_config || {}) },
    });
    setShowSecrets({});
  };

  const getFieldValue = (fieldName: string, isOrgField: boolean): string | boolean => {
    if (isOrgField) {
      return integrationDraft.config[fieldName] ?? '';
    }
    return integrationDraft.team_config[fieldName] ?? '';
  };

  const setFieldValue = (fieldName: string, value: string | boolean, isOrgField: boolean) => {
    if (isOrgField) {
      setIntegrationDraft({
        ...integrationDraft,
        config: { ...integrationDraft.config, [fieldName]: value },
      });
    } else {
      setIntegrationDraft({
        ...integrationDraft,
        team_config: { ...integrationDraft.team_config, [fieldName]: value },
      });
    }
  };

  const isIntegrationConfigured = (integrationId: string): boolean => {
    const schema = integrationSchemas[integrationId];
    if (!schema) return true;
    const int = effectiveConfig?.integrations?.[integrationId] as {
      config?: Record<string, unknown>;
      team_config?: Record<string, unknown>;
    } | undefined;

    // Check org required fields
    for (const field of schema.org_fields) {
      if (field.required && !int?.config?.[field.name]) return false;
    }
    // Check team required fields
    for (const field of schema.team_fields) {
      if (field.required && !int?.team_config?.[field.name]) return false;
    }
    return true;
  };

  // Graph layout computation for agent topology view
  const graphLayout = useMemo(() => {
    if (!effectiveConfig?.agents) return { nodes: [], edges: [], bounds: null };

    const agents = effectiveConfig.agents;
    // Only include enabled agents in topology (enabled !== false)
    const agentIds = Object.keys(agents).filter(id => agents[id]?.enabled !== false);

    if (agentIds.length === 0) return { nodes: [], edges: [], bounds: null };

    // Helper to get enabled sub-agents
    const getEnabledSubAgents = (agent: any): string[] => {
      const subAgents = agent.sub_agents || {};

      // sub_agents is an object with boolean values
      return Object.entries(subAgents)
        .filter(([_, enabled]) => enabled)
        .map(([subId, _]) => subId);
    };

    // Find which agents are used as sub-agents
    const usedAgentIds = new Set<string>();
    agentIds.forEach(id => {
      const agent = agents[id];
      getEnabledSubAgents(agent).forEach(subId => {
        usedAgentIds.add(subId);
      });
    });

    // Find root orchestrators (agents that use others but aren't used themselves)
    const rootAgentIds = agentIds.filter(id => {
      const agent = agents[id];
      const hasSubAgents = getEnabledSubAgents(agent).length > 0;
      const isUsedBySomeone = usedAgentIds.has(id);
      return hasSubAgents && !isUsedBySomeone;
    });

    // Build reachable set: start from root agents, traverse down
    const reachableAgents = new Set<string>();
    const toVisit = [...rootAgentIds];

    while (toVisit.length > 0) {
      const current = toVisit.pop()!;
      if (reachableAgents.has(current)) continue;

      reachableAgents.add(current);

      // Add sub-agents to visit list
      if (agents[current]) {
        getEnabledSubAgents(agents[current]).forEach(subId => {
          if (!reachableAgents.has(subId) && agents[subId]) {
            toVisit.push(subId);
          }
        });
      }
    }

    // Only include reachable agents
    const connectedAgentIds = agentIds.filter(id => reachableAgents.has(id));

    if (connectedAgentIds.length === 0) return { nodes: [], edges: [], bounds: null };

    // Count how many agents use each agent as a sub-agent
    const usedByCount: Record<string, number> = {};
    connectedAgentIds.forEach(id => { usedByCount[id] = 0; });

    connectedAgentIds.forEach(id => {
      const agent = agents[id];
      getEnabledSubAgents(agent).forEach(subId => {
        if (usedByCount[subId] !== undefined) {
          usedByCount[subId]++;
        }
      });
    });

    // Group agents by level (usedByCount)
    const levelGroups: Record<number, string[]> = {};
    connectedAgentIds.forEach(id => {
      const level = usedByCount[id];
      if (!levelGroups[level]) levelGroups[level] = [];
      levelGroups[level].push(id);
    });

    // Sort levels and create node positions
    const sortedLevels = Object.keys(levelGroups).map(Number).sort((a, b) => a - b);
    const nodes: { id: string; x: number; y: number; level: number }[] = [];
    const levelSpacingY = 140;
    const centerX = 400;

    sortedLevels.forEach((level, levelIndex) => {
      const agentsInLevel = levelGroups[level];
      const spacing = 150;
      const startX = centerX - ((agentsInLevel.length - 1) * spacing) / 2;

      agentsInLevel.forEach((id, i) => {
        nodes.push({
          id,
          x: startX + i * spacing,
          y: 50 + levelIndex * levelSpacingY,
          level,
        });
      });
    });

    // Build edges (only for connected agents)
    const edges: { from: string; to: string }[] = [];
    connectedAgentIds.forEach(id => {
      const agent = agents[id];
      getEnabledSubAgents(agent).forEach(subId => {
        if (agents[subId] && reachableAgents.has(subId)) {
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
    } : null;

    return { nodes, edges, bounds };
  }, [effectiveConfig?.agents]);

  if (identityLoading || loading) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100 p-8">
        <div className="animate-pulse">Loading configuration...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      {/* Breadcrumb Navigation */}
      <div className="border-b border-slate-800 bg-slate-900 px-8 py-3">
        <div className="flex items-center gap-2 text-sm">
          <Link
            href="/admin"
            className="flex items-center gap-1.5 text-slate-400 hover:text-white transition-colors"
          >
            <Home className="w-4 h-4" />
            <span>Admin Dashboard</span>
          </Link>
          <span className="text-slate-600">/</span>
          <span className="text-white">Configuration</span>
        </div>
      </div>

      {/* Header */}
      <div className="border-b border-slate-800 bg-slate-900/50 px-8 py-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-white">Configuration</h1>
            <p className="text-slate-400 mt-1">
              Manage agent, tool, and integration settings
            </p>
          </div>
          
          {/* Node Selector */}
          <div className="flex items-center gap-4">
            <label className="text-sm text-slate-400">Viewing:</label>
            <select
              value={selectedNode}
              onChange={(e) => setSelectedNode(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500"
            >
              {nodes.map((node) => (
                <option key={node.node_id} value={node.node_id}>
                  {node.name || node.node_id} ({node.node_type})
                </option>
              ))}
            </select>
          </div>
        </div>
        
        {/* Tabs */}
        <div className="flex gap-1 mt-6">
          {[
            { id: 'agents', label: 'Agents' },
            { id: 'tools', label: 'Tools' },
            { id: 'mcps', label: 'MCPs' },
            { id: 'integrations', label: 'Integrations' },
            { id: 'raw', label: 'Raw JSON' },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as ConfigTab)}
              className={`px-4 py-2 rounded-t-lg text-sm font-medium transition-colors ${
                activeTab === tab.id
                  ? 'bg-slate-800 text-cyan-400 border-t border-l border-r border-slate-700'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800/50'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="p-8">
        {/* Status Messages */}
        {error && (
          <div className="mb-6 p-4 bg-red-900/30 border border-red-700 rounded-lg text-red-300 whitespace-pre-line">
            {error}
          </div>
        )}
        {success && (
          <div className="mb-6 p-4 bg-green-900/30 border border-green-700 rounded-lg text-green-300">
            {success}
          </div>
        )}

        {/* Agents Tab */}
        {activeTab === 'agents' && effectiveConfig?.agents && (
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold text-white">Agent Configuration</h2>
                {selectedNode === identity?.org_id && (
                  <p className="text-sm text-blue-400 mt-1">
                    🌐 Org-Level Configuration - All teams inherit these settings
                  </p>
                )}
              </div>
              <div className="flex items-center gap-3">
                {/* Templates Button */}
                <button
                  onClick={() => window.location.href = '/admin/templates'}
                  className="flex items-center gap-2 px-4 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition-all"
                  title="View agent templates marketplace"
                >
                  <LayoutTemplate className="w-4 h-4" />
                  Templates
                </button>
                {/* Add Agent Button */}
                <div className="relative">
                  <button
                    onClick={() => setShowAgentTypeMenu(!showAgentTypeMenu)}
                    className="flex items-center gap-2 px-4 py-2.5 bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg transition-all"
                  >
                    <span className="text-lg leading-none">+</span>
                    Add Agent
                  </button>
                  {showAgentTypeMenu && (
                    <div className="absolute right-0 mt-2 w-56 bg-slate-800 rounded-lg shadow-xl border border-slate-700 z-50">
                      <button
                        onClick={() => {
                          setShowAgentTypeMenu(false);
                          setShowAddAgent(true);
                        }}
                        className="w-full px-4 py-3 text-left hover:bg-slate-700 transition-colors rounded-t-lg flex items-center gap-3"
                      >
                        <Bot className="w-4 h-4 text-cyan-400" />
                        <div>
                          <div className="text-sm font-medium text-white">Add Local Agent</div>
                          <div className="text-xs text-slate-400">Create a new internal agent</div>
                        </div>
                      </button>
                      <button
                        onClick={() => {
                          setShowAgentTypeMenu(false);
                          setShowAddRemoteAgent(true);
                        }}
                        className="w-full px-4 py-3 text-left hover:bg-slate-700 transition-colors rounded-b-lg flex items-center gap-3"
                      >
                        <ExternalLink className="w-4 h-4 text-cyan-500" />
                        <div>
                          <div className="text-sm font-medium text-white">Add Remote A2A Agent</div>
                          <div className="text-xs text-slate-400">Integrate external AI agent</div>
                        </div>
                      </button>
                    </div>
                  )}
                </div>
                {/* View toggle */}
                <div className="flex items-center bg-slate-800 rounded-lg p-1">
                  <button
                    onClick={() => setAgentViewMode('visual')}
                    className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-sm transition-all ${
                      agentViewMode === 'visual'
                        ? 'bg-slate-700 text-cyan-400 shadow-sm'
                        : 'text-slate-400 hover:text-slate-300'
                    }`}
                  >
                    <Network className="w-4 h-4" />
                    Visual
                  </button>
                  <button
                    onClick={() => setAgentViewMode('json')}
                    className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-sm transition-all ${
                      agentViewMode === 'json'
                        ? 'bg-slate-700 text-cyan-400 shadow-sm'
                        : 'text-slate-400 hover:text-slate-300'
                    }`}
                  >
                    <Code className="w-4 h-4" />
                    JSON
                  </button>
                </div>
              </div>
            </div>

            {/* Visual Mode - Topology */}
            {agentViewMode === 'visual' && (
              <div className="flex gap-4 min-h-[600px]">
                {/* Left: Topology Canvas */}
                <div className="flex-1 bg-slate-900 border border-slate-800 rounded-lg overflow-auto relative">
                  <div className="absolute inset-0 p-6">
                    <div className="relative" style={{ minWidth: '800px', minHeight: '500px' }}>
                      {/* Connection Lines (SVG) */}
                      <svg className="absolute inset-0 w-full h-full pointer-events-none" style={{ zIndex: 0 }}>
                        <defs>
                          <marker
                            id="arrowhead-admin"
                            markerWidth="6"
                            markerHeight="5"
                            refX="5"
                            refY="2.5"
                            orient="auto"
                          >
                            <polygon points="0 0, 6 2.5, 0 5" className="fill-slate-500" />
                          </marker>
                        </defs>

                        {/* Draw edges between agents */}
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
                                className="stroke-slate-700"
                                strokeWidth="1.5"
                                markerEnd="url(#arrowhead-admin)"
                              />
                            </g>
                          );
                        })}
                      </svg>

                      {/* Agent Nodes */}
                      {graphLayout.nodes.map((node) => {
                        const agent = effectiveConfig.agents[node.id];
                        if (!agent) return null;

                        return (
                          <div
                            key={node.id}
                            className="absolute transition-all duration-300"
                            style={{
                              left: node.x,
                              top: node.y,
                              transform: 'translate(-50%, 0)',
                              zIndex: selectedAgentId === node.id ? 10 : 1,
                            }}
                          >
                            <AgentNode
                              agent={{ ...agent, id: node.id }}
                              isSelected={selectedAgentId === node.id}
                              onClick={() => {
                                setSelectedAgentId(node.id);
                                setAgentDraft(agent);
                              }}
                              isPrimary={node.level === 0}
                              allAgents={effectiveConfig?.agents}
                              isEntranceAgent={node.id === effectiveConfig?.entrance_agent}
                            />
                          </div>
                        );
                      })}

                      {/* Legend */}
                      <div className="absolute bottom-4 left-4 p-3 bg-slate-800/90 backdrop-blur rounded-lg border border-slate-700">
                        <div className="flex items-center gap-4 text-xs text-slate-400">
                          <div className="flex items-center gap-1.5">
                            <div className="w-2.5 h-2.5 rounded-full bg-green-500" />
                            <span>Enabled</span>
                          </div>
                          <div className="flex items-center gap-1.5">
                            <Sparkles className="w-3 h-3 text-amber-500" />
                            <span>Entrance Agent</span>
                          </div>
                          <div className="flex items-center gap-1.5">
                            <div className="w-6 h-px bg-slate-500" />
                            <span>→ Uses</span>
                          </div>
                        </div>
                      </div>

                      {/* Click hint */}
                      {!selectedAgentId && (
                        <div className="absolute bottom-4 right-4 text-xs text-slate-500">
                          Click an agent to configure
                        </div>
                      )}
                    </div>
                  </div>
                </div>

                {/* Right: Agent Details Panel */}
                {selectedAgentId && agentDraft && (() => {
                  const currentAgent = effectiveConfig?.agents?.[selectedAgentId];
                  if (!currentAgent) return null;

                  return (
                    <div className="w-96 bg-slate-900 border-l border-slate-800 overflow-auto">
                      <div className="p-6 space-y-6">
                        {/* Agent Header */}
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-4">
                            <div className="w-11 h-11 rounded-lg bg-cyan-900/30 border border-cyan-800 flex items-center justify-center">
                              <Bot className="w-5 h-5 text-cyan-400" />
                            </div>
                            <div>
                              <h2 className="text-lg font-semibold text-white">
                                {currentAgent.name}
                              </h2>
                              <p className="text-sm text-slate-500">{currentAgent.description}</p>
                            </div>
                          </div>

                          <div className="flex items-center gap-2">
                            {/* Enable/Disable Toggle */}
                            <button
                              onClick={() =>
                                setAgentDraft({ ...agentDraft, enabled: !agentDraft.enabled })
                              }
                              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm transition-colors ${
                                agentDraft.enabled
                                  ? 'bg-green-900/30 text-green-400'
                                  : 'bg-slate-800 text-slate-500'
                              }`}
                            >
                              {agentDraft.enabled ? (
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
                              onClick={() => {
                                setSelectedAgentId(null);
                                setAgentDraft({});
                                setShowPrompt(false);
                              }}
                              className="p-2 rounded-lg hover:bg-slate-800 text-slate-500"
                            >
                              <X className="w-5 h-5" />
                            </button>
                          </div>
                        </div>

                        {/* Agent Type Badge */}
                        {(() => {
                          const subAgents = currentAgent.sub_agents || {};
                          const hasSubAgents = Object.keys(subAgents).length > 0;
                          return hasSubAgents && (
                            <div className="flex items-center gap-2">
                              <span className="text-xs px-2 py-1 rounded-full bg-cyan-900/30 text-cyan-400 flex items-center gap-1">
                                <Sparkles className="w-3 h-3" />
                                Orchestrator
                              </span>
                            </div>
                          );
                        })()}

                        {/* Configuration Sections */}
                        <div className="space-y-4">
                          {/* Model Configuration */}
                          <div className="bg-slate-800 rounded-xl p-4 border border-slate-700">
                            <div className="flex items-center gap-2 mb-4">
                              <Zap className="w-5 h-5 text-yellow-500" />
                              <h3 className="font-semibold text-white">Model</h3>
                            </div>

                            <div className="grid grid-cols-3 gap-4">
                              <div>
                                <label className="block text-xs font-medium text-slate-500 mb-1">
                                  Model Name
                                </label>
                                <select
                                  value={agentDraft.model?.name || 'gpt-4o'}
                                  onChange={(e) =>
                                    setAgentDraft({
                                      ...agentDraft,
                                      model: { ...agentDraft.model, name: e.target.value } as AgentConfig['model'],
                                    })
                                  }
                                  className="w-full px-3 py-2 text-sm rounded-lg border border-slate-600 bg-slate-900 text-white"
                                >
                                  <option value="gpt-5">gpt-5</option>
                                  <option value="gpt-4o">gpt-4o</option>
                                  <option value="gpt-4o-2024-11-20">gpt-4o-2024-11-20</option>
                                  <option value="gpt-4o-mini">gpt-4o-mini</option>
                                  <option value="gpt-4-turbo">gpt-4-turbo</option>
                                  <option value="gpt-3.5-turbo">gpt-3.5-turbo</option>
                                  <option value="o1">o1</option>
                                  <option value="o1-mini">o1-mini</option>
                                  <option value="o3-mini">o3-mini</option>
                                  <option value="o4-mini">o4-mini</option>
                                </select>
                              </div>

                              <div>
                                <label className="block text-xs font-medium text-slate-500 mb-1">
                                  Temperature
                                </label>
                                <input
                                  type="number"
                                  step="0.1"
                                  min="0"
                                  max="2"
                                  value={agentDraft.model?.temperature ?? 0.4}
                                  onChange={(e) =>
                                    setAgentDraft({
                                      ...agentDraft,
                                      model: {
                                        ...agentDraft.model,
                                        temperature: parseFloat(e.target.value) || 0,
                                      } as AgentConfig['model'],
                                    })
                                  }
                                  className="w-full px-3 py-2 text-sm rounded-lg border border-slate-600 bg-slate-900 text-white"
                                />
                              </div>

                              <div>
                                <label className="block text-xs font-medium text-slate-500 mb-1">
                                  Max Turns
                                </label>
                                <input
                                  type="number"
                                  min="1"
                                  max="100"
                                  value={agentDraft.max_turns ?? 20}
                                  onChange={(e) =>
                                    setAgentDraft({
                                      ...agentDraft,
                                      max_turns: parseInt(e.target.value) || 20,
                                    })
                                  }
                                  className="w-full px-3 py-2 text-sm rounded-lg border border-slate-600 bg-slate-900 text-white"
                                />
                              </div>
                            </div>
                          </div>

                          {/* System Prompt */}
                          <div className="bg-slate-800 rounded-xl p-4 border border-slate-700">
                            <div className="flex items-center justify-between mb-4">
                              <div className="flex items-center gap-2">
                                <Brain className="w-5 h-5 text-cyan-500" />
                                <h3 className="font-semibold text-white">
                                  System Prompt
                                </h3>
                              </div>
                              <button
                                onClick={() => setShowPrompt(!showPrompt)}
                                className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300"
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
                              <div className="space-y-2">
                                {!agentDraft.prompt?.system && selectedAgentId && defaultPrompts[selectedAgentId] && (
                                  <div className="flex items-center gap-2 text-xs text-amber-400">
                                    <span className="px-2 py-0.5 bg-amber-500/20 rounded">Using code default</span>
                                    <span className="text-slate-500">Edit below to customize</span>
                                  </div>
                                )}
                                <textarea
                                  value={agentDraft.prompt?.system || ''}
                                  onChange={(e) =>
                                    setAgentDraft({
                                      ...agentDraft,
                                      prompt: { ...(agentDraft.prompt || { system: '', prefix: '', suffix: '' }), system: e.target.value },
                                    })
                                  }
                                  rows={12}
                                  className="w-full px-3 py-2 text-sm font-mono rounded-lg border border-slate-600 bg-slate-900 text-white resize-y"
                                  placeholder={selectedAgentId && defaultPrompts[selectedAgentId]
                                    ? defaultPrompts[selectedAgentId]
                                    : "Enter system prompt..."}
                                />
                                {!agentDraft.prompt?.system && selectedAgentId && defaultPrompts[selectedAgentId] && (
                                  <button
                                    onClick={() => setAgentDraft({
                                      ...agentDraft,
                                      prompt: { ...(agentDraft.prompt || { system: '', prefix: '', suffix: '' }), system: defaultPrompts[selectedAgentId] },
                                    })}
                                    className="text-xs text-blue-400 hover:text-blue-300"
                                  >
                                    Copy default to editor
                                  </button>
                                )}
                              </div>
                            ) : (
                              <div className="text-sm text-slate-500 italic">
                                {agentDraft.prompt?.system
                                  ? `${agentDraft.prompt.system.slice(0, 150)}...`
                                  : (selectedAgentId && defaultPrompts[selectedAgentId]
                                    ? <span className="flex items-center gap-2">
                                        <span className="px-2 py-0.5 bg-amber-500/20 text-amber-400 rounded text-xs not-italic">Default</span>
                                        {defaultPrompts[selectedAgentId].slice(0, 100)}...
                                      </span>
                                    : 'No prompt configured')}
                              </div>
                            )}
                          </div>

                          {/* Tools */}
                          <div className="bg-slate-800 rounded-xl p-4 border border-slate-700">
                            <div className="flex items-center justify-between mb-4">
                              <div className="flex items-center gap-2">
                                <Wrench className="w-5 h-5 text-blue-500" />
                                <h3 className="font-semibold text-white">Tools</h3>
                              </div>
                              <button
                                onClick={() => setShowToolPicker(!showToolPicker)}
                                className="text-xs text-orange-400 hover:text-orange-300 flex items-center gap-1"
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
                                <div className="text-xs text-slate-400 bg-blue-900/20 border border-blue-800 rounded-lg p-3">
                                  <p className="mb-2">
                                    <strong>Default tools:</strong> Built-in tools automatically available to this agent.
                                  </p>
                                  <p className="mb-2">
                                    <strong>Extra tools:</strong> Additional tools from tool pool (built-in + MCP).
                                  </p>
                                  <p>
                                    Click tools below to disable defaults or add extras.
                                  </p>
                                </div>

                                {/* Disabled Default Tools */}
                                {(agentDraft.disable_default_tools || []).length > 0 && (
                                  <div>
                                    <div className="text-xs font-medium text-slate-300 mb-2">
                                      Disabled Default Tools:
                                    </div>
                                    <div className="flex flex-wrap gap-2">
                                      {(agentDraft.disable_default_tools || []).map((tool) => (
                                        <button
                                          key={tool}
                                          onClick={() => {
                                            setAgentDraft({
                                              ...agentDraft,
                                              disable_default_tools: (agentDraft.disable_default_tools || []).filter(t => t !== tool),
                                            });
                                          }}
                                          className="group flex items-center gap-1.5 px-2.5 py-1 text-xs rounded bg-red-900/30 text-red-400 hover:bg-red-900/50 transition-colors"
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
                                {(agentDraft.enable_extra_tools || []).length > 0 && (
                                  <div>
                                    <div className="text-xs font-medium text-slate-300 mb-2">
                                      Enabled Extra Tools:
                                    </div>
                                    <div className="flex flex-wrap gap-2">
                                      {(agentDraft.enable_extra_tools || []).map((tool) => (
                                        <button
                                          key={tool}
                                          onClick={() => {
                                            setAgentDraft({
                                              ...agentDraft,
                                              enable_extra_tools: (agentDraft.enable_extra_tools || []).filter(t => t !== tool),
                                            });
                                          }}
                                          className="group flex items-center gap-1.5 px-2.5 py-1 text-xs rounded bg-green-900/30 text-green-400 hover:bg-green-900/50 transition-colors"
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
                                  const enabledTools = Object.entries(agentDraft.tools || {})
                                    .filter(([_, enabled]) => enabled)
                                    .map(([tool, _]) => tool);
                                  const hasWildcard = agentDraft.tools?.['*'] === true;

                                  if (enabledTools.length === 0 && !hasWildcard) return null;

                                  return (
                                    <div>
                                      <div className="text-xs font-medium text-slate-300 mb-2">
                                        Default Tools {hasWildcard && '(all enabled)'}:
                                      </div>
                                      {hasWildcard ? (
                                        <div className="text-xs text-slate-500 italic">
                                          Using wildcard pattern (*). All built-in tools are enabled by default.
                                        </div>
                                      ) : (
                                        <div className="flex flex-wrap gap-2">
                                          {enabledTools
                                            .filter(t => !(agentDraft.disable_default_tools || []).includes(t))
                                            .map((tool) => (
                                            <button
                                              key={tool}
                                              onClick={() => {
                                                setAgentDraft({
                                                  ...agentDraft,
                                                  disable_default_tools: [...(agentDraft.disable_default_tools || []), tool],
                                                });
                                              }}
                                              className="px-2.5 py-1 text-xs rounded bg-slate-700 text-slate-300 hover:bg-slate-600 transition-colors"
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
                                  <div className="text-xs font-medium text-slate-300 mb-2">
                                    Add Extra Tools from Pool:
                                  </div>
                                  {loadingTools ? (
                                    <div className="text-xs text-slate-500">Loading tool pool...</div>
                                  ) : (
                                    <div className="max-h-40 overflow-y-auto border border-slate-600 rounded-lg p-2">
                                      <div className="flex flex-wrap gap-2">
                                        {toolPool
                                          .filter(t => !(agentDraft.enable_extra_tools || []).includes(t.name))
                                          .map((tool) => (
                                          <button
                                            key={tool.name}
                                            onClick={() => {
                                              setAgentDraft({
                                                ...agentDraft,
                                                enable_extra_tools: [...(agentDraft.enable_extra_tools || []), tool.name],
                                              });
                                            }}
                                            className="flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-lg border border-dashed border-slate-500 text-slate-400 hover:border-blue-400 hover:text-blue-400 transition-colors"
                                            title={tool.description || 'Add this tool'}
                                          >
                                            <span className="text-lg leading-none">+</span>
                                            {tool.name}
                                            {tool.source === 'mcp' && (
                                              <span className="text-[10px] px-1 py-0.5 rounded bg-cyan-900/30 text-cyan-400">
                                                MCP
                                              </span>
                                            )}
                                          </button>
                                        ))}
                                      </div>
                                      {toolPool.length === 0 && (
                                        <div className="text-xs text-slate-500 italic">
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
                                <div className="text-sm text-slate-400">
                                  {(() => {
                                    const hasWildcard = agentDraft.tools?.['*'] === true;
                                    const enabledCount = Object.values(agentDraft.tools || {}).filter(Boolean).length;
                                    return hasWildcard ? (
                                      <>All default tools enabled</>
                                    ) : (
                                      <>{enabledCount} default tools</>
                                    );
                                  })()}
                                  {(agentDraft.disable_default_tools || []).length > 0 && (
                                    <span className="text-red-400">
                                      {' '}− {agentDraft.disable_default_tools?.length} disabled
                                    </span>
                                  )}
                                  {(agentDraft.enable_extra_tools || []).length > 0 && (
                                    <span className="text-green-400">
                                      {' '}+ {agentDraft.enable_extra_tools?.length} extra
                                    </span>
                                  )}
                                </div>
                              </div>
                            )}
                          </div>

                          {/* MCP Servers (Interactive) */}
                          <div className="bg-slate-800 rounded-xl p-4 border border-slate-700">
                            <div className="flex items-center justify-between mb-4">
                              <div className="flex items-center gap-2">
                                <Server className="w-5 h-5 text-cyan-500" />
                                <h3 className="font-semibold text-white">
                                  MCP Servers
                                </h3>
                                <span className="text-xs text-slate-500">
                                  (click to enable/disable)
                                </span>
                              </div>
                            </div>

                            <div className="space-y-3">
                              {(() => {
                                const agentMcps = agentDraft.mcps || {};
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
                                                setAgentDraft({
                                                  ...agentDraft,
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
                                          <div className="text-xs text-slate-500 mb-2">Add MCP server:</div>
                                          <div className="flex flex-wrap gap-2">
                                            {disabledMcps.map((mcp) => {
                                              const toolCount = mcp.enabled_tools.includes('*')
                                                ? mcp.tools.length
                                                : mcp.enabled_tools.length;

                                              return (
                                                <button
                                                  key={mcp.id}
                                                  onClick={() => {
                                                    setAgentDraft({
                                                      ...agentDraft,
                                                      mcps: {
                                                        ...agentMcps,
                                                        [mcp.id]: true
                                                      }
                                                    });
                                                  }}
                                                  className="flex items-center gap-2 px-3 py-1.5 text-sm rounded-lg transition-colors bg-slate-700 border border-slate-600 text-slate-300 hover:border-cyan-500 hover:text-cyan-400"
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
                                      <div className="text-sm text-slate-500 italic">
                                        No MCP servers available. Configure them in the MCPs tab.
                                      </div>
                                    )}
                                  </>
                                );
                              })()}
                            </div>
                          </div>

                          {/* Sub-Agents (Interactive) */}
                          <div className="bg-slate-800 rounded-xl p-4 border border-slate-700">
                            <div className="flex items-center justify-between mb-4">
                              <div className="flex items-center gap-2">
                                <Users className="w-5 h-5 text-indigo-500" />
                                <h3 className="font-semibold text-white">
                                  Sub-Agents
                                </h3>
                                <span className="text-xs text-slate-500">
                                  (click to add/remove)
                                </span>
                              </div>
                            </div>

                            <div className="space-y-3">
                              {(() => {
                                // sub_agents is an object with boolean values
                                const agentSubAgents = agentDraft.sub_agents || {};

                                // Get all local agents (excluding current agent)
                                const allAgents = effectiveConfig?.agents || {};
                                const localAgentIds = Object.keys(allAgents).filter(
                                  id => id !== selectedAgentId
                                );

                                // Combine local agents and remote agents for display
                                const combinedAgents = {
                                  ...allAgents,
                                  ...Object.fromEntries(
                                    remoteAgents.map(ra => [ra.id, {
                                      id: ra.id,
                                      name: ra.name,
                                      enabled: true,
                                      isRemote: true,
                                      description: ra.description,
                                    }])
                                  )
                                };

                                // Get all available agent IDs (local + remote, excluding current)
                                const allAvailableIds = [
                                  ...localAgentIds,
                                  ...remoteAgents.map(ra => ra.id)
                                ];

                                // Filter enabled sub-agents to only include globally-enabled agents
                                const enabledSubAgents = Object.entries(agentSubAgents)
                                  .filter(([_, enabled]) => enabled)
                                  .map(([id, _]) => id)
                                  .filter(id => combinedAgents[id]?.enabled !== false);

                                return (
                                  <>
                                    {/* Currently enabled sub-agents */}
                                    {enabledSubAgents.length > 0 && (
                                      <div className="flex flex-wrap gap-2">
                                        {enabledSubAgents.map((subId) => {
                                          const sub = combinedAgents[subId];
                                          const isRemote = (sub as any)?.isRemote === true;
                                          return (
                                            <button
                                              key={subId}
                                              onClick={() => {
                                                setAgentDraft({
                                                  ...agentDraft,
                                                  sub_agents: {
                                                    ...agentSubAgents,
                                                    [subId]: false
                                                  }
                                                });
                                              }}
                                              className={`flex items-center gap-2 px-3 py-1.5 text-sm rounded-lg transition-colors group ${
                                                isRemote
                                                  ? 'bg-cyan-500 text-white hover:bg-cyan-600'
                                                  : 'bg-orange-500 text-white hover:bg-orange-600'
                                              }`}
                                              title={isRemote ? 'Remote A2A Agent - Click to remove' : 'Local Agent - Click to remove'}
                                            >
                                              {isRemote ? (
                                                <ExternalLink className="w-4 h-4" />
                                              ) : (
                                                <Bot className="w-4 h-4" />
                                              )}
                                              {sub?.name || subId}
                                              <X className="w-3 h-3 opacity-60 group-hover:opacity-100" />
                                            </button>
                                          );
                                        })}
                                      </div>
                                    )}

                                    {/* Available agents to add */}
                                    {(() => {
                                      // Filter to exclude already-enabled sub-agents and globally-disabled agents
                                      const availableToAdd = allAvailableIds.filter(
                                        id => !enabledSubAgents.includes(id) && combinedAgents[id]?.enabled !== false
                                      );

                                      if (availableToAdd.length === 0) return null;

                                      return (
                                        <div>
                                          <div className="text-xs text-slate-500 mb-2">Add sub-agent:</div>
                                          <div className="flex flex-wrap gap-2">
                                            {availableToAdd.map((agentId) => {
                                              const agent = combinedAgents[agentId];
                                              const isRemote = (agent as any)?.isRemote === true;
                                              return (
                                                <button
                                                  key={agentId}
                                                  onClick={() => {
                                                    setAgentDraft({
                                                      ...agentDraft,
                                                      sub_agents: {
                                                        ...agentSubAgents,
                                                        [agentId]: true
                                                      },
                                                      handoff_strategy: agentDraft.handoff_strategy || 'agent_as_tool'
                                                    });
                                                  }}
                                                  className={`flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-lg border border-dashed transition-colors ${
                                                    isRemote
                                                      ? 'border-cyan-600 text-cyan-400 hover:border-cyan-400 hover:text-cyan-300'
                                                      : 'border-slate-600 text-slate-400 hover:border-indigo-400 hover:text-indigo-400'
                                                  }`}
                                                  title={isRemote ? 'Remote A2A Agent - Click to add' : 'Local Agent - Click to add'}
                                                >
                                                  <span className="text-lg leading-none">+</span>
                                                  {isRemote && <ExternalLink className="w-3 h-3" />}
                                                  {agent?.name || agentId}
                                                </button>
                                              );
                                            })}
                                          </div>
                                        </div>
                                      );
                                    })()}

                                    {allAvailableIds.length === 0 && (
                                      <p className="text-sm text-slate-500 italic">
                                        No other agents available. Create more agents or add remote A2A agents.
                                      </p>
                                    )}
                                  </>
                                );
                              })()}
                            </div>
                          </div>
                        </div>

                        {/* Save button */}
                        <button
                          onClick={saveAgentConfig}
                          disabled={saving}
                          className="w-full px-4 py-2 bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg transition-colors disabled:opacity-50"
                        >
                          {saving ? 'Saving...' : 'Save Changes'}
                        </button>
                      </div>
                    </div>
                  );
                })()}
              </div>
            )}

            {/* JSON Mode */}
            {agentViewMode === 'json' && (
              <div className="grid grid-cols-2 gap-6">
                <div className="space-y-3">
                  <h3 className="text-sm font-medium text-slate-400">Effective Configuration</h3>
                  <pre className="bg-slate-900 border border-slate-800 rounded-lg p-4 text-xs font-mono overflow-auto max-h-[500px] text-slate-300">
                    {JSON.stringify({ agents: effectiveConfig.agents }, null, 2)}
                  </pre>
                </div>
                <div className="space-y-3">
                  <h3 className="text-sm font-medium text-slate-400">Raw Configuration</h3>
                  <pre className="bg-slate-900 border border-slate-800 rounded-lg p-4 text-xs font-mono overflow-auto max-h-[500px] text-slate-300">
                    {JSON.stringify(rawConfig?.config?.agents || {}, null, 2)}
                  </pre>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Tools Tab */}
        {activeTab === 'tools' && (
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold text-white">Built-in Tools</h2>
                <p className="text-sm text-slate-400 mt-1">
                  {toolMetadata.length} tools available across all categories
                </p>
              </div>
            </div>

            {toolMetadata.length === 0 ? (
              <div className="bg-slate-900 border border-slate-800 rounded-lg p-8 text-center">
                <p className="text-slate-400">Loading tools...</p>
              </div>
            ) : (
              <div className="space-y-4">
                {/* Group tools by category */}
                {Object.entries(
                  toolMetadata.reduce((acc, tool) => {
                    const category = tool.category || 'other';
                    if (!acc[category]) acc[category] = [];
                    acc[category].push(tool);
                    return acc;
                  }, {} as Record<string, ToolMetadata[]>)
                ).sort(([a], [b]) => a.localeCompare(b)).map(([category, tools]) => (
                  <div key={category} className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
                    <div className="bg-slate-800/50 px-4 py-3 border-b border-slate-700">
                      <h3 className="text-sm font-medium text-white capitalize">
                        {category} ({tools.length})
                      </h3>
                    </div>
                    <div className="divide-y divide-slate-800">
                      {tools.map((tool) => {
                        // Canonical format: tools dict has explicit true/false values
                        const toolsDict = (effectiveConfig?.tools as Record<string, boolean>) || {};
                        // If tool is in dict with value false, it's disabled
                        // If tool is not in dict or true, it's enabled (default)
                        const isEnabled = toolsDict[tool.id] !== false;

                        return (
                          <div key={tool.id} className="px-4 py-3 hover:bg-slate-800/30 transition-colors">
                            <div className="flex items-start justify-between gap-4">
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2">
                                  <code className="text-sm font-mono text-cyan-400">{tool.id}</code>
                                  {tool.required_integrations && tool.required_integrations.length > 0 && (
                                    <div className="flex items-center gap-1">
                                      {tool.required_integrations.map((int) => (
                                        <span
                                          key={int}
                                          className="px-1.5 py-0.5 text-[10px] font-medium rounded bg-cyan-900/30 text-cyan-400"
                                        >
                                          {int}
                                        </span>
                                      ))}
                                    </div>
                                  )}
                                </div>
                                <p className="text-sm text-slate-400 mt-1">{tool.description}</p>
                              </div>
                              <button
                                onClick={() => handleToggleTool(tool.id, isEnabled)}
                                disabled={saving}
                                className="flex items-center gap-2 px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50"
                              >
                                {isEnabled ? (
                                  <>
                                    <ToggleRight className="w-4 h-4 text-green-500" />
                                    <span className="text-xs text-green-500">Enabled</span>
                                  </>
                                ) : (
                                  <>
                                    <ToggleLeft className="w-4 h-4 text-slate-500" />
                                    <span className="text-xs text-slate-500">Disabled</span>
                                  </>
                                )}
                              </button>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* MCPs Tab */}
        {activeTab === 'mcps' && effectiveConfig && (
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-white">MCP Servers</h2>
              <button
                onClick={() => setShowAddMcpModal(true)}
                className="flex items-center gap-2 px-4 py-2.5 bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg transition-all"
              >
                <Plus className="w-4 h-4" />
                Add MCP Server
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <h3 className="text-sm font-medium text-slate-400 mb-2">Default MCPs (Org-defined)</h3>
                <div className="grid gap-2">
                  {Object.entries((effectiveConfig.mcp_servers as Record<string, any>) || {}).map(([id, mcp]) => (
                    <div
                      key={id}
                      className="bg-slate-900 border border-slate-800 rounded-lg p-4 flex items-center justify-between"
                    >
                      <div className="flex items-center gap-3">
                        <div className={`w-2 h-2 rounded-full ${mcp.enabled !== false ? 'bg-green-500' : 'bg-slate-600'}`} />
                        <span className="text-white">{mcp.name || id}</span>
                        <span className="text-xs text-slate-500">{mcp.type || 'mcp'}</span>
                      </div>
                      <span className="text-xs text-slate-500">Inherited</span>
                    </div>
                  ))}
                </div>
              </div>

              {Object.keys((effectiveConfig.mcp_servers as Record<string, any>) || {}).length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-slate-400 mb-2">MCP Servers</h3>
                  <div className="grid gap-2">
                    {Object.entries((effectiveConfig.mcp_servers as Record<string, any>) || {}).map(([id, mcp]) => (
                      <div
                        key={id}
                        className="bg-slate-900 border border-cyan-800 rounded-lg p-4"
                      >
                        <span className="text-white">{mcp.name || id}</span>
                        {mcp.description && (
                          <p className="text-sm text-slate-500 mt-1">{mcp.description}</p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {Object.entries((effectiveConfig.tools as Record<string, boolean>) || {}).filter(([, enabled]) => !enabled).length > 0 && (
                <div className="text-sm text-slate-500">
                  Disabled tools: {Object.entries((effectiveConfig.tools as Record<string, boolean>) || {})
                    .filter(([, enabled]) => !enabled)
                    .map(([id]) => id)
                    .join(', ')}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Integrations Tab */}
        {activeTab === 'integrations' && (
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold text-white">Integrations</h2>
                <p className="text-sm text-slate-400 mt-1">
                  Configure third-party service connections. Click Configure to set credentials.
                </p>
              </div>
            </div>
            
            <div className="grid gap-4">
              {Object.entries(integrationSchemas).map(([integrationId, schema]) => {
                const int = effectiveConfig?.integrations?.[integrationId] as { 
                  level?: string; 
                  locked?: boolean; 
                  config?: Record<string, unknown>; 
                  team_config?: Record<string, unknown> 
                } | undefined;
                const isConfigured = isIntegrationConfigured(integrationId);
                const hasOrgFields = schema.org_fields.length > 0;
                const hasTeamFields = schema.team_fields.length > 0;
                
                return (
                  <div
                    key={integrationId}
                    className="bg-slate-900 border border-slate-800 rounded-lg p-5 hover:border-slate-700 transition-colors"
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-3">
                          <div className={`w-2.5 h-2.5 rounded-full ${isConfigured ? 'bg-green-500' : 'bg-yellow-500'}`} />
                          <span className="font-semibold text-white">{schema.name}</span>
                          <span className={`px-2 py-0.5 text-xs rounded ${
                            schema.level === 'org' 
                              ? 'bg-purple-900/50 text-cyan-400' 
                              : 'bg-cyan-900/50 text-cyan-400'
                          }`}>
                            {schema.level}-level
                          </span>
                          {isConfigured ? (
                            <span className="flex items-center gap-1 px-2 py-0.5 text-xs rounded bg-green-900/50 text-green-400">
                              <Check className="w-3 h-3" /> Configured
                            </span>
                          ) : (
                            <span className="flex items-center gap-1 px-2 py-0.5 text-xs rounded bg-yellow-900/50 text-yellow-400">
                              <AlertTriangle className="w-3 h-3" /> Needs Setup
                            </span>
                          )}
                          {int?.locked && (
                            <span className="px-2 py-0.5 text-xs rounded bg-red-900/50 text-red-400">
                              Locked
                            </span>
                          )}
                        </div>
                        <p className="text-sm text-slate-400 mt-2 ml-5">{schema.description}</p>
                        
                        {/* Field summary */}
                        <div className="mt-3 ml-5 text-xs text-slate-500">
                          {hasOrgFields && <span>{schema.org_fields.length} org fields</span>}
                          {hasOrgFields && hasTeamFields && <span className="mx-2">•</span>}
                          {hasTeamFields && <span>{schema.team_fields.length} team fields</span>}
                        </div>
                      </div>
                      
                      <button
                        onClick={() => openIntegrationEditor(integrationId)}
                        className="flex items-center gap-2 px-4 py-2 text-sm bg-slate-800 hover:bg-slate-700 rounded-lg transition-colors"
                      >
                        <Settings className="w-4 h-4" />
                        Configure
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Raw JSON Tab */}
        {activeTab === 'raw' && rawConfig && (
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-white">Raw Configuration</h2>
              <div className="text-sm text-slate-400">
                Version {rawConfig.version} • 
                {rawConfig.updated_at && ` Updated ${new Date(rawConfig.updated_at).toLocaleString()}`}
              </div>
            </div>
            
            <div className="bg-slate-900 border border-slate-800 rounded-lg p-6">
              <pre className="text-sm text-slate-300 overflow-auto max-h-96">
                {JSON.stringify(rawConfig.config, null, 2)}
              </pre>
            </div>
            
            <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-6">
              <h3 className="text-sm font-medium text-slate-400 mb-4">Effective Configuration (Merged)</h3>
              <pre className="text-sm text-slate-300 overflow-auto max-h-96">
                {JSON.stringify(effectiveConfig, null, 2)}
              </pre>
            </div>
          </div>
        )}
      </div>

      {/* Integration Edit Modal */}
      {editingIntegration && integrationSchemas[editingIntegration] && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
          <div className="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-2xl max-h-[90vh] overflow-auto">
            <div className="p-6 border-b border-slate-800">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-xl font-semibold text-white">
                    Configure {integrationSchemas[editingIntegration].name}
                  </h2>
                  <p className="text-sm text-slate-400 mt-1">
                    {integrationSchemas[editingIntegration].description}
                  </p>
                </div>
                <button
                  onClick={() => {
                    setEditingIntegration(null);
                    setIntegrationDraft({ config: {}, team_config: {} });
                    setShowSecrets({});
                  }}
                  className="p-2 text-slate-400 hover:text-white transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>
            
            <div className="p-6 space-y-8">
              {/* Org-level fields */}
              {integrationSchemas[editingIntegration].org_fields.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-cyan-400 mb-4 flex items-center gap-2">
                    <span className="w-2 h-2 bg-purple-400 rounded-full" />
                    Organization Settings
                  </h3>
                  <div className="space-y-4">
                    {integrationSchemas[editingIntegration].org_fields.map((field) => (
                      <div key={field.name}>
                        <label className="block text-sm text-slate-300 mb-2">
                          {field.display_name}
                          {field.required && <span className="text-red-400 ml-1">*</span>}
                        </label>
                        {field.description && (
                          <p className="text-xs text-slate-500 mb-2">{field.description}</p>
                        )}
                        
                        {field.type === 'boolean' ? (
                          <label className="flex items-center gap-3">
                            <input
                              type="checkbox"
                              checked={getFieldValue(field.name, true) as boolean}
                              onChange={(e) => setFieldValue(field.name, e.target.checked, true)}
                              className="w-4 h-4 rounded bg-slate-800 border-slate-600"
                            />
                            <span className="text-slate-400 text-sm">Enable</span>
                          </label>
                        ) : field.allowed_values ? (
                          <select
                            value={String(getFieldValue(field.name, true) || field.default || '')}
                            onChange={(e) => setFieldValue(field.name, e.target.value, true)}
                            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 text-white"
                          >
                            <option value="">Select...</option>
                            {field.allowed_values.map((val) => (
                              <option key={val} value={val}>{val}</option>
                            ))}
                          </select>
                        ) : field.type === 'secret' ? (
                          <div className="relative">
                            <input
                              type={showSecrets[field.name] ? 'text' : 'password'}
                              value={getFieldValue(field.name, true) as string}
                              onChange={(e) => setFieldValue(field.name, e.target.value, true)}
                              placeholder={field.placeholder || '••••••••'}
                              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 pr-12 text-white font-mono text-sm"
                            />
                            <button
                              type="button"
                              onClick={() => setShowSecrets({ ...showSecrets, [field.name]: !showSecrets[field.name] })}
                              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white"
                            >
                              {showSecrets[field.name] ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                            </button>
                          </div>
                        ) : (
                          <input
                            type="text"
                            value={getFieldValue(field.name, true) as string}
                            onChange={(e) => setFieldValue(field.name, e.target.value, true)}
                            placeholder={field.placeholder || ''}
                            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 text-white"
                          />
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
              
              {/* Team-level fields */}
              {integrationSchemas[editingIntegration].team_fields.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-cyan-400 mb-4 flex items-center gap-2">
                    <span className="w-2 h-2 bg-cyan-400 rounded-full" />
                    Team Settings
                  </h3>
                  <div className="space-y-4">
                    {integrationSchemas[editingIntegration].team_fields.map((field) => (
                      <div key={field.name}>
                        <label className="block text-sm text-slate-300 mb-2">
                          {field.display_name}
                          {field.required && <span className="text-red-400 ml-1">*</span>}
                        </label>
                        {field.description && (
                          <p className="text-xs text-slate-500 mb-2">{field.description}</p>
                        )}
                        
                        {field.type === 'boolean' ? (
                          <label className="flex items-center gap-3">
                            <input
                              type="checkbox"
                              checked={getFieldValue(field.name, false) as boolean}
                              onChange={(e) => setFieldValue(field.name, e.target.checked, false)}
                              className="w-4 h-4 rounded bg-slate-800 border-slate-600"
                            />
                            <span className="text-slate-400 text-sm">Enable</span>
                          </label>
                        ) : field.allowed_values ? (
                          <select
                            value={String(getFieldValue(field.name, false) || field.default || '')}
                            onChange={(e) => setFieldValue(field.name, e.target.value, false)}
                            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 text-white"
                          >
                            <option value="">Select...</option>
                            {field.allowed_values.map((val) => (
                              <option key={val} value={val}>{val}</option>
                            ))}
                          </select>
                        ) : field.type === 'secret' ? (
                          <div className="relative">
                            <input
                              type={showSecrets[`team_${field.name}`] ? 'text' : 'password'}
                              value={getFieldValue(field.name, false) as string}
                              onChange={(e) => setFieldValue(field.name, e.target.value, false)}
                              placeholder={field.placeholder || '••••••••'}
                              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 pr-12 text-white font-mono text-sm"
                            />
                            <button
                              type="button"
                              onClick={() => setShowSecrets({ ...showSecrets, [`team_${field.name}`]: !showSecrets[`team_${field.name}`] })}
                              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white"
                            >
                              {showSecrets[`team_${field.name}`] ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                            </button>
                          </div>
                        ) : (
                          <input
                            type="text"
                            value={getFieldValue(field.name, false) as string}
                            onChange={(e) => setFieldValue(field.name, e.target.value, false)}
                            placeholder={field.placeholder || ''}
                            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 text-white"
                          />
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
              
              {/* Docs link */}
              {integrationSchemas[editingIntegration].docs_url && (
                <div className="pt-4 border-t border-slate-800">
                  <a
                    href={integrationSchemas[editingIntegration].docs_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm text-cyan-400 hover:text-cyan-300"
                  >
                    📚 View documentation →
                  </a>
                </div>
              )}
            </div>
            
            <div className="p-6 border-t border-slate-800 flex justify-end gap-3">
              <button
                onClick={() => {
                  setEditingIntegration(null);
                  setIntegrationDraft({ config: {}, team_config: {} });
                  setShowSecrets({});
                }}
                className="px-4 py-2 text-slate-400 hover:text-white transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={saveIntegrationConfig}
                disabled={saving}
                className="px-4 py-2 bg-orange-600 hover:bg-orange-500 text-white rounded-lg transition-colors disabled:opacity-50"
              >
                {saving ? 'Saving...' : 'Save Configuration'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add Agent Modal */}
      {showAddAgent && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-md">
            <div className="p-6 border-b border-slate-800">
              <h2 className="text-xl font-semibold text-white">Add New Agent</h2>
            </div>

            <div className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-400 mb-2">
                  Agent ID *
                </label>
                <input
                  type="text"
                  value={newAgentId}
                  onChange={(e) => setNewAgentId(e.target.value)}
                  placeholder="e.g., security-scanner, database-expert"
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 text-white"
                  autoFocus
                />
                <p className="text-xs text-slate-500 mt-1">
                  Use lowercase with hyphens (e.g., my-agent)
                </p>
              </div>
            </div>

            <div className="p-6 border-t border-slate-800 flex justify-end gap-3">
              <button
                onClick={() => {
                  setShowAddAgent(false);
                  setNewAgentId('');
                }}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-white rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleCreateAgent}
                disabled={saving || !newAgentId.trim()}
                className="px-4 py-2 bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg transition-colors disabled:opacity-50"
              >
                {saving ? 'Creating...' : 'Create Agent'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add Remote A2A Agent Modal */}
      {showAddRemoteAgent && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
          <div className="bg-slate-900 border border-slate-700 rounded-xl shadow-2xl w-full max-w-2xl mx-4 p-6 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <ExternalLink className="w-5 h-5 text-cyan-500" />
                <h3 className="text-lg font-semibold text-white">
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
                className="p-1 rounded hover:bg-slate-800"
              >
                <X className="w-5 h-5 text-slate-500" />
              </button>
            </div>

            <div className="space-y-4">
              {/* ID */}
              <div>
                <label className="block text-sm font-medium text-slate-400 mb-1">
                  Agent ID *
                </label>
                <input
                  type="text"
                  value={newRemoteAgent.id}
                  onChange={(e) => setNewRemoteAgent({ ...newRemoteAgent, id: e.target.value.trim().toLowerCase().replace(/[^a-z0-9_]/g, '_') })}
                  placeholder="e.g., security_scanner"
                  className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-white"
                />
              </div>

              {/* Name */}
              <div>
                <label className="block text-sm font-medium text-slate-400 mb-1">
                  Display Name *
                </label>
                <input
                  type="text"
                  value={newRemoteAgent.name}
                  onChange={(e) => setNewRemoteAgent({ ...newRemoteAgent, name: e.target.value })}
                  placeholder="e.g., Security Scanner Agent"
                  className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-white"
                />
              </div>

              {/* URL */}
              <div>
                <label className="block text-sm font-medium text-slate-400 mb-1">
                  A2A Endpoint URL *
                </label>
                <input
                  type="url"
                  value={newRemoteAgent.url}
                  onChange={(e) => setNewRemoteAgent({ ...newRemoteAgent, url: e.target.value })}
                  placeholder="https://hello.a2aregistry.org/a2a"
                  className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-white font-mono text-sm"
                />
              </div>

              {/* Description */}
              <div>
                <label className="block text-sm font-medium text-slate-400 mb-1">
                  Description
                </label>
                <textarea
                  value={newRemoteAgent.description}
                  onChange={(e) => setNewRemoteAgent({ ...newRemoteAgent, description: e.target.value })}
                  placeholder="What does this agent do?"
                  className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-white"
                  rows={2}
                />
              </div>

              {/* Auth Type */}
              <div>
                <label className="block text-sm font-medium text-slate-400 mb-1">
                  Authentication
                </label>
                <select
                  value={newRemoteAgent.auth.type}
                  onChange={(e) => setNewRemoteAgent({
                    ...newRemoteAgent,
                    auth: { type: e.target.value as any }
                  })}
                  className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-white"
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
                  <label className="block text-sm font-medium text-slate-400 mb-1">
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
                    className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-white font-mono text-sm"
                  />
                </div>
              )}

              {/* Auth Fields - API Key */}
              {newRemoteAgent.auth.type === 'apikey' && (
                <>
                  <div>
                    <label className="block text-sm font-medium text-slate-400 mb-1">
                      API Key *
                    </label>
                    <input
                      type="password"
                      value={newRemoteAgent.auth.api_key || ''}
                      onChange={(e) => setNewRemoteAgent({
                        ...newRemoteAgent,
                        auth: { ...newRemoteAgent.auth, api_key: e.target.value }
                      })}
                      className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-white font-mono text-sm"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-sm font-medium text-slate-400 mb-1">
                        Location
                      </label>
                      <select
                        value={newRemoteAgent.auth.location || 'header'}
                        onChange={(e) => setNewRemoteAgent({
                          ...newRemoteAgent,
                          auth: { ...newRemoteAgent.auth, location: e.target.value as 'header' | 'query' }
                        })}
                        className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-white"
                      >
                        <option value="header">Header</option>
                        <option value="query">Query Param</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-slate-400 mb-1">
                        Key Name
                      </label>
                      <input
                        type="text"
                        value={newRemoteAgent.auth.key_name || 'X-API-Key'}
                        onChange={(e) => setNewRemoteAgent({
                          ...newRemoteAgent,
                          auth: { ...newRemoteAgent.auth, key_name: e.target.value }
                        })}
                        className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-white font-mono text-sm"
                      />
                    </div>
                  </div>
                </>
              )}

              {/* Auth Fields - OAuth2 */}
              {newRemoteAgent.auth.type === 'oauth2' && (
                <>
                  <div>
                    <label className="block text-sm font-medium text-slate-400 mb-1">
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
                      className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-white font-mono text-sm"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-sm font-medium text-slate-400 mb-1">
                        Client ID *
                      </label>
                      <input
                        type="text"
                        value={newRemoteAgent.auth.client_id || ''}
                        onChange={(e) => setNewRemoteAgent({
                          ...newRemoteAgent,
                          auth: { ...newRemoteAgent.auth, client_id: e.target.value }
                        })}
                        className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-white font-mono text-sm"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-slate-400 mb-1">
                        Client Secret *
                      </label>
                      <input
                        type="password"
                        value={newRemoteAgent.auth.client_secret || ''}
                        onChange={(e) => setNewRemoteAgent({
                          ...newRemoteAgent,
                          auth: { ...newRemoteAgent.auth, client_secret: e.target.value }
                        })}
                        className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-white font-mono text-sm"
                      />
                    </div>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-400 mb-1">
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
                      className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-white"
                    />
                  </div>
                </>
              )}

              {/* Timeout */}
              <div>
                <label className="block text-sm font-medium text-slate-400 mb-1">
                  Timeout (seconds)
                </label>
                <input
                  type="number"
                  value={newRemoteAgent.timeout}
                  onChange={(e) => setNewRemoteAgent({ ...newRemoteAgent, timeout: parseInt(e.target.value) || 300 })}
                  min={10}
                  max={600}
                  className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-white"
                />
              </div>

              {/* Connection Test Result */}
              {connectionTestResult && (
                <div className={`p-3 rounded-lg ${
                  connectionTestResult.success
                    ? 'bg-green-900/20 border border-green-800'
                    : 'bg-red-900/20 border border-red-800'
                }`}>
                  <div className="flex items-center gap-2">
                    {connectionTestResult.success ? (
                      <CheckCircle className="w-4 h-4 text-green-600" />
                    ) : (
                      <XCircle className="w-4 h-4 text-red-600" />
                    )}
                    <span className={`text-sm ${
                      connectionTestResult.success ? 'text-green-300' : 'text-red-300'
                    }`}>
                      {connectionTestResult.message}
                    </span>
                  </div>
                </div>
              )}

              {/* Actions */}
              <div className="flex justify-between items-center gap-3 pt-2 border-t border-slate-700">
                <button
                  onClick={async () => {
                    setTestingConnection(true);
                    setConnectionTestResult(null);
                    try {
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
                  className="px-4 py-2 text-sm text-slate-400 hover:text-white disabled:opacity-50"
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
                    className="px-4 py-2 text-sm text-slate-400 hover:text-white"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={async () => {
                      if (!newRemoteAgent.id || !newRemoteAgent.name || !newRemoteAgent.url) {
                        setError('Please fill in all required fields');
                        return;
                      }

                      setSaving(true);
                      try {
                        // Get current remote agents dict and add the new one
                        const currentRemoteAgents = (effectiveConfig?.remote_agents as Record<string, any>) || {};
                        await saveConfig({
                          remote_agents: {
                            ...currentRemoteAgents,
                            [newRemoteAgent.id]: {
                              type: 'a2a',
                              name: newRemoteAgent.name,
                              url: newRemoteAgent.url,
                              auth: newRemoteAgent.auth,
                              description: newRemoteAgent.description,
                              timeout: newRemoteAgent.timeout,
                              enabled: true,
                            },
                          },
                        });

                        await loadConfig();
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
                        setSuccess('Remote agent added successfully!');
                      } catch (e: any) {
                        setError(e.message || 'Failed to add remote agent');
                      } finally {
                        setSaving(false);
                      }
                    }}
                    disabled={!newRemoteAgent.id || !newRemoteAgent.name || !newRemoteAgent.url || saving}
                    className="px-4 py-2 text-sm bg-cyan-600 text-white rounded-lg hover:bg-cyan-700 disabled:opacity-50"
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

      {/* Add MCP Modal */}
      {showAddMcpModal && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-2xl max-h-[90vh] overflow-auto">
            <div className="p-6 border-b border-slate-800 sticky top-0 bg-slate-900 z-10">
              <h2 className="text-xl font-semibold text-white">Add Custom MCP Server</h2>
              <p className="text-sm text-slate-400 mt-1">Add a custom Model Context Protocol server</p>
            </div>

            <div className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-400 mb-2">
                  Name *
                </label>
                <input
                  type="text"
                  value={newMcpForm.name}
                  onChange={(e) => setNewMcpForm({ ...newMcpForm, name: e.target.value })}
                  placeholder="My Custom Server"
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 text-white"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-400 mb-2">
                  Description
                </label>
                <input
                  type="text"
                  value={newMcpForm.description}
                  onChange={(e) => setNewMcpForm({ ...newMcpForm, description: e.target.value })}
                  placeholder="Provides access to..."
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 text-white"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-400 mb-2">
                  Command *
                </label>
                <input
                  type="text"
                  value={newMcpForm.command}
                  onChange={(e) => setNewMcpForm({ ...newMcpForm, command: e.target.value })}
                  placeholder="npx"
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 text-white font-mono"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-400 mb-2">
                  Arguments (comma-separated)
                </label>
                <input
                  type="text"
                  value={newMcpForm.args}
                  onChange={(e) => setNewMcpForm({ ...newMcpForm, args: e.target.value })}
                  placeholder="-y, @modelcontextprotocol/server-filesystem"
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 text-white font-mono"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-400 mb-2">
                  Environment Variables (one per line, KEY=VALUE format)
                </label>
                <textarea
                  value={newMcpForm.env}
                  onChange={(e) => setNewMcpForm({ ...newMcpForm, env: e.target.value })}
                  placeholder="API_KEY=your-key&#10;BASE_URL=https://api.example.com"
                  rows={4}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 text-white font-mono text-sm"
                />
              </div>
            </div>

            <div className="p-6 border-t border-slate-800 flex justify-end gap-3 sticky bottom-0 bg-slate-900">
              <button
                onClick={() => {
                  setShowAddMcpModal(false);
                  setNewMcpForm({ name: '', description: '', command: '', args: '', env: '' });
                }}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-white rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleCreateMcp}
                disabled={saving || !newMcpForm.name.trim() || !newMcpForm.command.trim()}
                className="flex items-center gap-2 px-4 py-2 bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg transition-colors disabled:opacity-50"
              >
                <Plus className="w-4 h-4" />
                {saving ? 'Adding...' : 'Add MCP Server'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
