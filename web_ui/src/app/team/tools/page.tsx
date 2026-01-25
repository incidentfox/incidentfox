'use client';

import { useEffect, useState, useCallback } from 'react';
import { useIdentity } from '@/lib/useIdentity';
import {
  Server,
  Plus,
  Save,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Eye,
  EyeOff,
  Wrench,
  X,
  ToggleLeft,
  ToggleRight,
  Box,
  Cloud,
  BarChart3,
  Code,
  GitBranch,
  FileSearch,
  MessageSquare,
  FileText,
  Container,
  Brain,
  ChevronDown,
  ChevronRight,
  Settings,
  Trash2,
} from 'lucide-react';

interface ConfigField {
  type: string;
  required: boolean;
  display_name: string;
  description?: string;
  placeholder?: string;
  default?: string;
  allowed_values?: string[];
}

interface ToolItem {
  id: string;
  name: string;
  description?: string;
  type: 'tool' | 'mcp_server' | 'integration';
  enabled: boolean;
  config_schema: Record<string, ConfigField>;
  config_values: Record<string, string>;
  source: 'org' | 'team';
  category?: string;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  tools?: Array<{
    name: string;
    display_name: string;
    description: string;
    category?: string;
  }>;
  enabled_tools?: string[];  // NEW: Tool filtering for MCPs
}

interface CatalogTool {
  id: string;
  name: string;
  description: string;
  category: string;
}

interface ToolMetadata {
  id: string;
  name: string;
  description: string;
  category: string;
  required_integrations: string[];
}

const CATEGORY_ICONS: Record<string, React.ReactNode> = {
  kubernetes: <Box className="w-4 h-4" />,
  aws: <Cloud className="w-4 h-4" />,
  analytics: <BarChart3 className="w-4 h-4" />,
  observability: <BarChart3 className="w-4 h-4" />,
  code: <Code className="w-4 h-4" />,
  github: <GitBranch className="w-4 h-4" />,
  logs: <FileSearch className="w-4 h-4" />,
  communication: <MessageSquare className="w-4 h-4" />,
  documentation: <FileText className="w-4 h-4" />,
  docker: <Container className="w-4 h-4" />,
  agent: <Brain className="w-4 h-4" />,
  data: <BarChart3 className="w-4 h-4" />,
  cicd: <GitBranch className="w-4 h-4" />,
};

const CATEGORY_LABELS: Record<string, string> = {
  kubernetes: 'Kubernetes',
  aws: 'AWS',
  analytics: 'Analytics',
  observability: 'Observability',
  code: 'Code & Git',
  github: 'GitHub',
  logs: 'Logs',
  communication: 'Communication',
  documentation: 'Documentation',
  docker: 'Docker',
  agent: 'Agent Core',
  data: 'Data Warehouse',
  cicd: 'CI/CD',
};

// Suppress unused variable warning for categories
void CATEGORY_ICONS;
void CATEGORY_LABELS;

interface IntegrationSchemaResponse {
  id: string;
  name: string;
  description: string;
  category: string;
}

export default function TeamToolsPage() {
  const { identity } = useIdentity();
  const [items, setItems] = useState<ToolItem[]>([]);
  const [toolsCatalog, setToolsCatalog] = useState<CatalogTool[]>([]);
  const [toolMetadata, setToolMetadata] = useState<ToolMetadata[]>([]);
  const [integrationSchemas, setIntegrationSchemas] = useState<IntegrationSchemaResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editingItem, setEditingItem] = useState<ToolItem | null>(null);
  const [editValues, setEditValues] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<{ type: 'success' | 'error' | 'info'; text: string } | null>(null);
  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({});
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set([]));
  const [showAddCustomModal, setShowAddCustomModal] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [newServerForm, setNewServerForm] = useState({
    name: '',
    description: '',
    command: '',
    args: '',
    env: '',
  });
  const [previewingTools, setPreviewingTools] = useState(false);
  const [previewedTools, setPreviewedTools] = useState<{
    success: boolean;
    tool_count: number;
    tools: Array<{
      name: string;
      display_name: string;
      description: string;
      category: string;
    }>;
    warnings: string[];
    error?: string;
  } | null>(null);

  // NEW: Tool filtering modal state
  const [filteringMcp, setFilteringMcp] = useState<ToolItem | null>(null);
  const [selectedTools, setSelectedTools] = useState<Set<string>>(new Set());

  const teamId = identity?.team_node_id;

  const loadItems = useCallback(async () => {
    if (!teamId) return;
    setLoading(true);

    try {
      // Fetch both config, tools catalog, and raw config (to detect team vs org)
      const [configRes, toolsRes, rawConfigRes] = await Promise.all([
        fetch('/api/team/config'),
        fetch('/api/team/tools'),
        fetch('/api/config/me/raw'),
      ]);

      if (!configRes.ok || !toolsRes.ok) {
        throw new Error('Failed to load configuration or tools catalog');
      }

      const data = await configRes.json();
      const toolsData = await toolsRes.json();
      const rawConfigData = rawConfigRes.ok ? await rawConfigRes.json() : null;

      // Extract configuration
      const integrations = data.integrations || {};
      const mcpServersDict = data.mcp_servers || {};
      const builtInTools = toolsData.tools || [];
      // Canonical format: tools is a dict {tool_id: boolean}
      const toolsDict = (data.tools || {}) as Record<string, boolean>;

      // Detect team-level MCP servers (exist in raw team config)
      const teamMcpIds = new Set<string>();
      if (rawConfigData?.configs && rawConfigData?.lineage) {
        // Find team node ID from lineage (last item is current team)
        const teamNodeId = rawConfigData.lineage[rawConfigData.lineage.length - 1];
        const teamConfig = rawConfigData.configs[teamNodeId];

        if (teamConfig?.mcp_servers) {
          Object.keys(teamConfig.mcp_servers).forEach(id => teamMcpIds.add(id));
        }
      }

      // Convert integrations object to array
      // Use schema descriptions (generic) instead of config descriptions (org-specific)
      const integrationItems = Object.entries(integrations).map(([id, config]: [string, any]) => {
        // Merge org-level and team-level config schemas
        const orgSchema = config.config_schema || {};
        const teamSchema = config.team_config_schema || {};
        const mergedSchema = { ...orgSchema, ...teamSchema };

        // Extract config values from the flat structure
        // Values are stored at the integration top level (e.g., slack.bot_token),
        // not in a nested config_values object
        const extractedValues: Record<string, string> = {};
        for (const fieldName of Object.keys(mergedSchema)) {
          if (config[fieldName] !== undefined) {
            extractedValues[fieldName] = config[fieldName];
          }
        }

        return {
          id,
          name: config.name || id,
          description: '', // Will be populated from schema in next step
          type: 'integration',
          enabled: true,  // Integrations are always "available", tools use them
          config_schema: mergedSchema,
          config_values: extractedValues,
          source: 'org' as const,
        };
      });

      // Convert mcp_servers dict to array and extract individual tools
      const mcpServerItems: ToolItem[] = [];

      Object.entries(mcpServersDict).forEach(([id, config]: [string, any]) => {
        const isTeamLevel = teamMcpIds.has(id);

        // Add MCP server card
        mcpServerItems.push({
          id,
          name: config.name || id,
          description: config.description || 'Custom MCP server',
          type: 'mcp_server' as const,
          enabled: config.enabled !== false,
          config_schema: {},
          config_values: config,
          source: isTeamLevel ? 'team' : 'org',
          tools: config.tools || [], // Include tools for display in card
          enabled_tools: config.enabled_tools || ['*'], // Include tool filter settings
        });
      });

      // Built-in tools
      const toolItems = builtInTools.map((item: ToolItem) => ({
        ...item,
        source: 'org' as const,
      }));

      // Combine all items and apply enabled/disabled logic
      const allItems = [...integrationItems, ...mcpServerItems, ...toolItems].map((item: ToolItem) => {
        // Integrations are always "available"
        if (item.type === 'integration') {
          return item;
        }

        // For tools/MCPs: check enabled/disabled status in canonical format
        // If tool is explicitly set in toolsDict, use that value
        // Otherwise, use the default enabled state
        const isEnabled = item.id in toolsDict ? toolsDict[item.id] : (item.enabled !== false);
        return { ...item, enabled: isEnabled };
      });

      setItems(allItems);
      setToolsCatalog(builtInTools);

      // Load tool metadata (integration dependencies)
      try {
        const metadataRes = await fetch('/api/v1/tools/metadata');
        if (metadataRes.ok) {
          const metadataData = await metadataRes.json();
          setToolMetadata(metadataData.tools || []);
        }
      } catch (e) {
        console.error('Failed to load tool metadata:', e);
      }

      // Load integration schemas (for descriptions)
      try {
        const schemasRes = await fetch('/api/v1/integrations/schemas');
        if (schemasRes.ok) {
          const schemasData = await schemasRes.json();
          setIntegrationSchemas(schemasData.integrations || []);
        }
      } catch (e) {
        console.error('Failed to load integration schemas:', e);
      }
    } catch (e) {
      console.error('Failed to load tools/MCPs:', e);
    } finally {
      setLoading(false);
    }
  }, [teamId]);

  useEffect(() => {
    loadItems();
  }, [loadItems]);

  // Update integration descriptions from schemas (use generic descriptions, not org-specific ones)
  useEffect(() => {
    if (integrationSchemas.length > 0 && items.length > 0) {
      const schemaLookup = new Map(integrationSchemas.map(s => [s.id, s]));
      const updatedItems = items.map(item => {
        if (item.type === 'integration') {
          const schema = schemaLookup.get(item.id);
          if (schema) {
            return { ...item, description: schema.description };
          }
        }
        return item;
      });
      setItems(updatedItems);
    }
  }, [integrationSchemas]);

  // Auto-expand sections with search matches
  useEffect(() => {
    if (searchQuery) {
      const sectionsWithMatches = new Set<string>();

      // Build catalog lookup
      const catalogLookup = new Map(toolsCatalog.map(t => [t.id, t]));

      // Check integrations for matches
      const integrationItems = items.filter(i => {
        const hasRequiredConfig = Object.values(i.config_schema || {}).some(f => f.required);
        const catalogEntry = catalogLookup.get(i.id);
        return hasRequiredConfig && !catalogEntry;
      });

      integrationItems.forEach(item => {
        if (item.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
            item.description?.toLowerCase().includes(searchQuery.toLowerCase())) {
          sectionsWithMatches.add('integration');
        }
      });

      // Check custom servers for matches
      const serverItems = items.filter(i => i.type === 'mcp_server');
      serverItems.forEach(item => {
        if (item.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
            item.description?.toLowerCase().includes(searchQuery.toLowerCase())) {
          sectionsWithMatches.add('mcp');
        }
      });

      // Check built-in tools by category for matches
      const toolItems = items.filter(i => i.type === 'tool' || (!Object.values(i.config_schema || {}).some(f => f.required) && i.type !== 'mcp_server'));
      toolItems.forEach(item => {
        const catalogEntry = catalogLookup.get(item.id);
        const category = catalogEntry?.category || item.category || 'other';
        if (item.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
            item.description?.toLowerCase().includes(searchQuery.toLowerCase())) {
          sectionsWithMatches.add(category);
        }
      });

      // Also check catalog tools that aren't in items yet
      const seenIds = new Set(items.map(i => i.id));
      toolsCatalog.forEach(catalogTool => {
        if (!seenIds.has(catalogTool.id)) {
          if (catalogTool.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
              catalogTool.description?.toLowerCase().includes(searchQuery.toLowerCase())) {
            sectionsWithMatches.add(catalogTool.category);
          }
        }
      });

      // Auto-expand sections with matches
      setExpandedCategories(sectionsWithMatches);
    } else {
      // When search is cleared, collapse all sections
      setExpandedCategories(new Set());
    }
  }, [searchQuery, items, toolsCatalog]);

  const getMissingRequiredFields = (item: ToolItem): string[] => {
    const missing: string[] = [];
    if (!item.config_schema) return missing;
    
    for (const [fieldName, fieldSchema] of Object.entries(item.config_schema)) {
      if (fieldSchema.required) {
        const value = item.config_values?.[fieldName];
        if (!value || value === '') {
          missing.push(fieldSchema.display_name || fieldName);
        }
      }
    }
    return missing;
  };

  const saveConfig = async () => {
    if (!editingItem) return;
    setSaving(true);
    setMessage(null);

    try {
      // Send integration config as flat structure (DB stores it flat)
      // editValues is already {api_key: "value", region: "value"}, send it directly
      const res = await fetch('/api/team/config', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          integrations: {
            [editingItem.id]: editValues,  // Send flat, no config_values wrapper
          },
        }),
      });

      if (res.ok) {
        setMessage({ type: 'success', text: 'Configuration saved!' });
        setEditingItem(null);
        await loadItems();
      } else {
        setMessage({ type: 'error', text: 'Failed to save configuration' });
      }
    } catch {
      setMessage({ type: 'error', text: 'Failed to save configuration' });
    } finally {
      setSaving(false);
    }
  };

  const toggleEnabled = async (item: ToolItem) => {
    // Integrations cannot be toggled (they're always available)
    if (item.type === 'integration') {
      return;
    }

    setSaving(true);
    try {
      // Get current lists
      const res = await fetch('/api/team/config');
      if (!res.ok) return;

      const data = await res.json();
      // Canonical format: tools is a dict {tool_id: boolean}
      const currentTools = (data.tools || {}) as Record<string, boolean>;

      // Toggle the tool in the dict
      const newTools = {
        ...currentTools,
        [item.id]: !item.enabled,
      };

      const patchRes = await fetch('/api/team/config', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tools: newTools,
        }),
      });

      if (patchRes.ok) {
        // Update local state immediately
        setItems(prev => prev.map(i =>
          i.id === item.id ? { ...i, enabled: !i.enabled } : i
        ));
      }
    } catch (e) {
      console.error('Failed to toggle:', e);
    } finally {
      setSaving(false);
    }
  };

  const previewMCPServer = async () => {
    if (!newServerForm.command) {
      setMessage({ type: 'error', text: 'Command is required to preview' });
      return;
    }

    setPreviewingTools(true);
    setMessage(null);
    setPreviewedTools(null);

    try {
      // Parse args and env
      const argsArray = newServerForm.args
        .split('\n')
        .map(line => line.trim())
        .filter(line => line.length > 0);

      const envObject: Record<string, string> = {};
      if (newServerForm.env) {
        newServerForm.env.split('\n').forEach(line => {
          const trimmed = line.trim();
          if (trimmed && trimmed.includes('=')) {
            const [key, ...valueParts] = trimmed.split('=');
            envObject[key.trim()] = valueParts.join('=').trim();
          }
        });
      }

      const res = await fetch('/api/team/mcp-servers/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newServerForm.name || 'Preview',
          description: newServerForm.description,
          command: newServerForm.command,
          args: argsArray,
          env_vars: envObject,
        }),
      });

      const data = await res.json();

      if (data.success) {
        setPreviewedTools(data);
        setMessage({ type: 'success', text: `Discovered ${data.tool_count} tools!` });
      } else {
        // Use error_details for better context, fallback to error
        const errorMsg = data.error_details || data.error || 'Failed to preview MCP server';
        setMessage({ type: 'error', text: errorMsg });
      }
    } catch (e) {
      console.error('Failed to preview MCP:', e);
      setMessage({ type: 'error', text: 'Failed to connect to MCP server' });
    } finally {
      setPreviewingTools(false);
    }
  };

  const saveCustomServer = async () => {
    if (!newServerForm.name || !newServerForm.command) {
      setMessage({ type: 'error', text: 'Name and command are required' });
      return;
    }

    setSaving(true);
    setMessage(null);

    try {
      // Auto-run preview if not already done
      let toolsToSave = previewedTools?.success ? previewedTools.tools : undefined;

      if (!toolsToSave) {
        setMessage({ type: 'info', text: 'Discovering tools...' });

        // Parse args and env for preview
        const argsArray = newServerForm.args
          .split('\n')
          .map(line => line.trim())
          .filter(line => line.length > 0);

        const envObject: Record<string, string> = {};
        if (newServerForm.env) {
          newServerForm.env.split('\n').forEach(line => {
            const trimmed = line.trim();
            if (trimmed && trimmed.includes('=')) {
              const [key, ...valueParts] = trimmed.split('=');
              envObject[key.trim()] = valueParts.join('=').trim();
            }
          });
        }

        // Run preview
        const previewRes = await fetch('/api/team/mcp-servers/preview', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: newServerForm.name || 'Preview',
            description: newServerForm.description,
            command: newServerForm.command,
            args: argsArray,
            env_vars: envObject,
          }),
        });

        const previewData = await previewRes.json();

        if (previewData.success) {
          toolsToSave = previewData.tools;
          setMessage({ type: 'success', text: `Discovered ${previewData.tool_count} tools!` });
        } else {
          // Use error_details for better context, fallback to error
          const errorMsg = previewData.error_details || previewData.error || 'Failed to discover tools';
          setMessage({ type: 'error', text: errorMsg });
          setSaving(false);
          return;
        }
      }

      // Parse args and env again for server creation
      const argsArray = newServerForm.args
        .split('\n')
        .map(line => line.trim())
        .filter(line => line.length > 0);

      const envObject: Record<string, string> = {};
      if (newServerForm.env) {
        newServerForm.env.split('\n').forEach(line => {
          const trimmed = line.trim();
          if (trimmed && trimmed.includes('=')) {
            const [key, ...valueParts] = trimmed.split('=');
            envObject[key.trim()] = valueParts.join('=').trim();
          }
        });
      }

      // Create new server object
      const newServer: ToolItem = {
        id: `custom_${newServerForm.name.toLowerCase().replace(/\s+/g, '_')}`,
        name: newServerForm.name,
        description: newServerForm.description || 'Custom MCP server',
        type: 'mcp_server',
        enabled: true,
        config_schema: {},
        config_values: {},
        source: 'team',
        command: newServerForm.command,
        args: argsArray.length > 0 ? argsArray : undefined,
        env: Object.keys(envObject).length > 0 ? envObject : undefined,
        tools: toolsToSave,
      };

      // Get current config
      const res = await fetch('/api/team/config');
      if (!res.ok) {
        setMessage({ type: 'error', text: 'Failed to load current config' });
        return;
      }

      const data = await res.json();
      const mcpServers = data.mcp_servers || {};

      // Add new server to mcp_servers dict (keyed by MCP ID)
      const updatedMcpServers = {
        ...mcpServers,
        [newServer.id]: newServer,
      };

      // Save to config
      const patchRes = await fetch('/api/team/config', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mcp_servers: updatedMcpServers,
        }),
      });

      if (patchRes.ok) {
        setMessage({ type: 'success', text: 'Custom server added successfully!' });
        setShowAddCustomModal(false);
        setNewServerForm({
          name: '',
          description: '',
          command: '',
          args: '',
          env: '',
        });
        await loadItems();
      } else {
        setMessage({ type: 'error', text: 'Failed to save custom server' });
      }
    } catch (e) {
      console.error('Failed to save custom server:', e);
      setMessage({ type: 'error', text: 'Failed to save custom server' });
    } finally {
      setSaving(false);
    }
  };

  const deleteMCPServer = async (item: ToolItem) => {
    if (!confirm(`Are you sure you want to delete "${item.name}"? This will also remove all tools from this MCP server from your agents.`)) {
      return;
    }

    setSaving(true);
    setMessage(null);

    try {
      // Get current config
      const res = await fetch('/api/team/config');
      if (!res.ok) {
        setMessage({ type: 'error', text: 'Failed to load current config' });
        return;
      }

      const data = await res.json();
      const mcpServers = data.mcp_servers || {};

      // Find the MCP server being deleted
      const mcpToDelete = mcpServers[item.id];

      // Get list of tool names from this MCP server
      const mcpToolNames = new Set<string>();
      if (mcpToDelete && mcpToDelete.tools) {
        mcpToDelete.tools.forEach((tool: any) => {
          mcpToolNames.add(tool.name);
        });
      }

      // Remove the server from mcp_servers dict
      const updatedMcpServers = { ...mcpServers };
      delete updatedMcpServers[item.id];

      // Clean up agent tool assignments
      const agents = data.agents || {};
      const updatedAgents: Record<string, any> = {};
      let toolsRemoved = 0;

      Object.entries(agents).forEach(([agentId, agentConfig]: [string, any]) => {
        const updatedAgent = { ...agentConfig };
        let modified = false;

        // Remove MCP tools from enable_extra_tools
        if (updatedAgent.enable_extra_tools && Array.isArray(updatedAgent.enable_extra_tools)) {
          const filtered = updatedAgent.enable_extra_tools.filter((toolName: string) => !mcpToolNames.has(toolName));
          if (filtered.length !== updatedAgent.enable_extra_tools.length) {
            updatedAgent.enable_extra_tools = filtered;
            toolsRemoved += updatedAgent.enable_extra_tools.length - filtered.length;
            modified = true;
          }
        }

        // Remove from mcp_tools if present (per-agent MCP tool filtering)
        if (updatedAgent.mcp_tools && Array.isArray(updatedAgent.mcp_tools)) {
          const filtered = updatedAgent.mcp_tools.filter((toolName: string) => !mcpToolNames.has(toolName));
          if (filtered.length !== updatedAgent.mcp_tools.length) {
            updatedAgent.mcp_tools = filtered;
            modified = true;
          }
        }

        updatedAgents[agentId] = modified ? updatedAgent : agentConfig;
      });

      // Save to config
      const patchRes = await fetch('/api/team/config', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mcp_servers: updatedMcpServers,
          agents: updatedAgents,
        }),
      });

      if (patchRes.ok) {
        const msg = toolsRemoved > 0
          ? `MCP server deleted and ${toolsRemoved} tool(s) removed from agents`
          : 'MCP server deleted successfully!';
        setMessage({ type: 'success', text: msg });
        await loadItems();
      } else {
        setMessage({ type: 'error', text: 'Failed to delete MCP server' });
      }
    } catch (e) {
      console.error('Failed to delete MCP server:', e);
      setMessage({ type: 'error', text: 'Failed to delete MCP server' });
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="h-screen flex items-center justify-center">
        <div className="text-gray-500">Loading...</div>
      </div>
    );
  }

  // Build category lookup from catalog
  const catalogById = new Map(toolsCatalog.map(t => [t.id, t]));

  // Build integration schema lookup (for descriptions)
  const integrationSchemaById = new Map(integrationSchemas.map(s => [s.id, s]));

  // Separate integrations (configurable items like Grafana, Kubernetes) from tools
  const integrations: ToolItem[] = [];
  const customServers: ToolItem[] = [];
  const toolsFromConfig: ToolItem[] = [];

  for (const item of items) {
    // Items with config_schema and required fields are "integrations"
    const hasRequiredConfig = Object.values(item.config_schema || {}).some(f => f.required);
    const catalogEntry = catalogById.get(item.id);
    const integrationSchema = integrationSchemaById.get(item.id);

    // Skip orphaned items (no description, not in catalog, not a real integration)
    // These are likely legacy/junk data from old config structure
    if (!item.description && !catalogEntry && !hasRequiredConfig && item.type !== 'mcp_server') {
      console.warn(`Skipping orphaned item with no description: ${item.id}`);
      continue;
    }

    if (item.type === 'mcp_server') {
      customServers.push({ ...item, category: 'mcp' });
    } else if (hasRequiredConfig && !catalogEntry) {
      // Configurable integration (Grafana, Kubernetes, Datadog, etc.)
      // Merge description from schema if available
      integrations.push({
        ...item,
        description: integrationSchema?.description || item.description,
        type: 'integration',
        category: 'integration'
      });
    } else {
      // Tool from config (with optional category from catalog)
      toolsFromConfig.push({ ...item, category: catalogEntry?.category || 'other' });
    }
  }

  // Add catalog tools that aren't already in config
  const seenIds = new Set(items.map(i => i.id));
  const catalogTools: ToolItem[] = [];
  
  for (const catalogTool of toolsCatalog) {
    if (!seenIds.has(catalogTool.id)) {
      catalogTools.push({
        id: catalogTool.id,
        name: catalogTool.name,
        description: catalogTool.description,
        type: 'tool',
        enabled: true,
        config_schema: {},
        config_values: {},
        source: 'org',
        category: catalogTool.category,
      });
    }
  }
  
  // Combine all tools
  const allBuiltInTools = [...toolsFromConfig, ...catalogTools];
  
  // Group tools by category
  const toolsByCategory = allBuiltInTools.reduce((acc, tool) => {
    const cat = tool.category || 'other';
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(tool);
    return acc;
  }, {} as Record<string, ToolItem[]>);

  // Separate enabled/disabled for custom servers (integrations don't have enabled/disabled)
  const enabledServers = customServers.filter(i => i.enabled);
  const disabledServers = customServers.filter(i => !i.enabled);
  
  // Count enabled/disabled tools
  const enabledToolCount = allBuiltInTools.filter(t => t.enabled).length;
  const disabledToolCount = allBuiltInTools.filter(t => !t.enabled).length;

  const renderCard = (item: ToolItem) => {
    const missingFields = getMissingRequiredFields(item);
    const hasMissing = missingFields.length > 0;

    // Get tools that depend on this integration
    const dependentTools = item.type === 'integration'
      ? toolMetadata.filter(tool => tool.required_integrations.includes(item.id))
      : [];

    return (
      <div
        key={item.id}
        className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800 p-4"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="font-medium text-gray-900 dark:text-white">{item.name}</h3>
              {item.source === 'org' && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-gray-500">
                  Inherited
                </span>
              )}
            </div>
            <p className="text-sm text-gray-500 mt-1 line-clamp-2">{item.description}</p>

            {/* Show dependent tools for integrations */}
            {dependentTools.length > 0 && (
              <div className="mt-2 pt-2 border-t border-gray-100 dark:border-gray-800">
                <p className="text-[10px] font-medium text-gray-500 uppercase tracking-wide mb-1">
                  Powers {dependentTools.length} tool{dependentTools.length !== 1 ? 's' : ''}:
                </p>
                <div className="flex flex-wrap gap-1">
                  {dependentTools.map(tool => (
                    <span
                      key={tool.id}
                      className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400"
                      title={tool.description}
                    >
                      {tool.name}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Show tools provided by MCP servers */}
            {item.type === 'mcp_server' && item.tools && Array.isArray(item.tools) && item.tools.length > 0 && (
              <div className="mt-2 pt-2 border-t border-gray-100 dark:border-gray-800">
                <p className="text-[10px] font-medium text-gray-500 uppercase tracking-wide mb-1">
                  Provides {item.tools.length} tool{item.tools.length !== 1 ? 's' : ''}:
                </p>
                <div className="flex flex-wrap gap-1">
                  {item.tools.map((tool: any, idx: number) => {
                    // Handle both string arrays and object arrays
                    const toolName = typeof tool === 'string' ? tool : (tool.display_name || tool.name);
                    const toolDesc = typeof tool === 'string' ? tool : (tool.description || tool.name);
                    return (
                      <span
                        key={idx}
                        className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-50 dark:bg-cyan-900/30 text-cyan-700 dark:text-cyan-300"
                        title={toolDesc}
                      >
                        {toolName}
                      </span>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
          
          <div className="flex items-center gap-2 flex-shrink-0">
            {/* Enable/Disable Toggle - Only for tools and MCPs, NOT for integrations */}
            {item.type !== 'integration' && (
              <button
                onClick={() => toggleEnabled(item)}
                disabled={saving}
                className={`p-1 rounded transition-colors ${
                  item.enabled
                    ? 'text-green-600 hover:text-green-700'
                    : 'text-gray-400 hover:text-gray-500'
                }`}
                title={item.enabled ? 'Disable' : 'Enable'}
              >
                {item.enabled ? (
                  <ToggleRight className="w-6 h-6" />
                ) : (
                  <ToggleLeft className="w-6 h-6" />
                )}
              </button>
            )}

            {/* Filter Tools button - only for MCP servers with tools */}
            {item.type === 'mcp_server' && item.tools && item.tools.length > 0 && (
              <button
                onClick={() => {
                  // Debug: Log the item data
                  console.log('🔍 Debug - Opening filter for MCP:', item.id);
                  console.log('🔍 Debug - Full item object:', item);
                  console.log('🔍 Debug - item.tools:', item.tools);
                  console.log('🔍 Debug - item.enabled_tools:', item.enabled_tools);
                  console.log('🔍 Debug - enabled_tools type:', typeof item.enabled_tools);
                  console.log('🔍 Debug - enabled_tools is array?', Array.isArray(item.enabled_tools));

                  setFilteringMcp(item);
                  // Initialize selected tools
                  const enabled = item.enabled_tools || ['*'];
                  console.log('🔍 Debug - Computed enabled:', enabled);
                  console.log('🔍 Debug - enabled.includes("*")?', enabled.includes('*'));

                  if (enabled.includes('*')) {
                    // All tools enabled - handle both string and object arrays
                    const toolNames = item.tools?.map(t =>
                      typeof t === 'string' ? t : (t.name || t.display_name)
                    ) || [];
                    console.log('🔍 Debug - All tools selected, extracted toolNames:', toolNames);
                    setSelectedTools(new Set(toolNames));
                  } else {
                    console.log('🔍 Debug - Using specific enabled tools:', enabled);
                    setSelectedTools(new Set(enabled));
                  }
                }}
                className="p-1 rounded text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
                title="Filter Tools"
              >
                <Settings className="w-4 h-4" />
              </button>
            )}

            {/* Configure button */}
            {item.config_schema && Object.keys(item.config_schema).length > 0 && (
              <button
                onClick={() => {
                  setEditingItem(item);
                  setEditValues(item.config_values || {});
                }}
                className={`text-xs px-2 py-1 rounded ${
                  hasMissing && item.enabled
                    ? 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400'
                    : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400'
                } hover:opacity-80`}
              >
                Configure
              </button>
            )}

            {/* Delete button - only for team-added MCP servers */}
            {item.type === 'mcp_server' && item.source === 'team' && (
              <button
                onClick={() => deleteMCPServer(item)}
                disabled={saving}
                className="p-1 rounded text-red-600 hover:text-red-700 hover:bg-red-50 dark:hover:bg-red-900/20 disabled:opacity-50 disabled:cursor-not-allowed"
                title="Delete MCP Server"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="h-screen flex flex-col">
      {/* Header */}
      <div className="flex-shrink-0 px-8 py-6 border-b border-gray-200 dark:border-gray-800">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-orange-500 to-amber-500 flex items-center justify-center">
              <Wrench className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-xl font-semibold text-gray-900 dark:text-white">Tools</h1>
              <p className="text-sm text-gray-500">Configure tools and integrations for your AI agents</p>
            </div>
          </div>
          <button
            onClick={() => setShowAddCustomModal(true)}
            className="flex items-center gap-2 px-4 py-2 bg-orange-600 text-white rounded-lg hover:bg-orange-700 text-sm"
          >
            <Plus className="w-4 h-4" />
            Add Custom
          </button>
        </div>


        {message && (
          <div className={`mt-4 p-3 rounded-lg flex items-center gap-2 text-sm ${
            message.type === 'success'
              ? 'bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-400'
              : message.type === 'info'
              ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400'
              : 'bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400'
          }`}>
            {message.type === 'success' ? <CheckCircle className="w-4 h-4" /> : message.type === 'info' ? <AlertTriangle className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
            {message.text}
          </div>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-8 space-y-6">
        {/* Search Bar */}
        <div className="mb-6">
          <input
            type="text"
            placeholder="Search integrations and tools..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full px-4 py-2 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-gray-500"
          />
        </div>

        {/* Integrations Section */}
        {integrations.length > 0 && (() => {
          const filteredIntegrations = integrations.filter(item =>
            item.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
            item.description?.toLowerCase().includes(searchQuery.toLowerCase())
          );
          return (
            <section className="border border-gray-200 dark:border-gray-800 rounded-lg overflow-hidden">
              <button
                onClick={() => {
                  const next = new Set(expandedCategories);
                  next.has('integration') ? next.delete('integration') : next.add('integration');
                  setExpandedCategories(next);
                }}
                className="w-full flex items-center gap-3 px-4 py-3 bg-gray-50 dark:bg-gray-800/50 hover:bg-gray-100 dark:hover:bg-gray-800"
              >
                {expandedCategories.has('integration') ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                <Settings className="w-4 h-4 text-gray-500" />
                <span className="font-medium text-gray-900 dark:text-white">Integrations</span>
                <span className="text-xs text-gray-500">
                  {searchQuery ? `${filteredIntegrations.length} of ${integrations.length}` : `${integrations.length} total`}
                </span>
              </button>
              {expandedCategories.has('integration') && (
                <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-4">
                  {filteredIntegrations.map(renderCard)}
                </div>
              )}
            </section>
          );
        })()}

        {/* Custom Servers Section */}
        {(enabledServers.length > 0 || disabledServers.length > 0) && (() => {
          const filteredServers = [...enabledServers, ...disabledServers].filter(item =>
            item.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
            item.description?.toLowerCase().includes(searchQuery.toLowerCase())
          );
          const filteredEnabled = filteredServers.filter(m => m.enabled).length;
          const filteredDisabled = filteredServers.filter(m => !m.enabled).length;
          return (
            <>
              {/* Separator */}
              <div className="space-y-4">
                <h2 className="text-sm font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide">
                  MCP Servers ({enabledServers.length} enabled, {disabledServers.length} disabled)
                </h2>
              </div>

              <section className="border border-gray-200 dark:border-gray-800 rounded-lg overflow-hidden">
                <button
                  onClick={() => {
                    const next = new Set(expandedCategories);
                    next.has('mcp') ? next.delete('mcp') : next.add('mcp');
                    setExpandedCategories(next);
                  }}
                  className="w-full flex items-center gap-3 px-4 py-3 bg-gray-50 dark:bg-gray-800/50 hover:bg-gray-100 dark:hover:bg-gray-800"
                >
                  {expandedCategories.has('mcp') ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                  <Server className="w-4 h-4 text-cyan-500" />
                  <span className="font-medium text-gray-900 dark:text-white">MCP Servers</span>
                  <span className="text-xs text-gray-500">
                    {searchQuery ? `${filteredEnabled} enabled, ${filteredDisabled} disabled` : `${enabledServers.length} enabled, ${disabledServers.length} disabled`}
                  </span>
                </button>
                {expandedCategories.has('mcp') && (
                  <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-4">
                    {filteredServers.map(renderCard)}
                  </div>
                )}
              </section>
            </>
          );
        })()}

        {/* Tools by Category */}
        <div className="space-y-4">
          <h2 className="text-sm font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide">
            Built-in Tools ({enabledToolCount} enabled, {disabledToolCount} disabled)
          </h2>
          
          {Object.entries(toolsByCategory)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([category, tools]) => {
              const enabled = tools.filter(t => t.enabled);
              const disabled = tools.filter(t => !t.enabled);
              const isExpanded = expandedCategories.has(category);
              
              return (
                <section key={category} className="border border-gray-200 dark:border-gray-800 rounded-lg overflow-hidden">
                  <button
                    onClick={() => {
                      const next = new Set(expandedCategories);
                      next.has(category) ? next.delete(category) : next.add(category);
                      setExpandedCategories(next);
                    }}
                    className="w-full flex items-center gap-3 px-4 py-3 bg-gray-50 dark:bg-gray-800/50 hover:bg-gray-100 dark:hover:bg-gray-800"
                  >
                    {isExpanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                    <span className="text-gray-500">{CATEGORY_ICONS[category] || <Wrench className="w-4 h-4" />}</span>
                    <span className="font-medium text-gray-900 dark:text-white">{CATEGORY_LABELS[category] || category}</span>
                    <span className="text-xs text-gray-500">
                      {enabled.length} enabled{disabled.length > 0 ? `, ${disabled.length} disabled` : ''}
                    </span>
                  </button>
                  {isExpanded && (
                    <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-4">
                      {[...enabled, ...disabled].filter(item =>
                        item.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
                        item.description?.toLowerCase().includes(searchQuery.toLowerCase())
                      ).map(renderCard)}
                    </div>
                  )}
                </section>
              );
            })}
        </div>

        {items.length === 0 && toolsCatalog.length === 0 && (
          <div className="text-center py-12">
            <Server className="w-12 h-12 text-gray-300 mx-auto mb-4" />
            <p className="text-gray-500">No tools configured yet.</p>
          </div>
        )}
      </div>

      {/* Configuration Modal */}
      {editingItem && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
          <div className="bg-white dark:bg-gray-900 rounded-xl shadow-2xl w-full max-w-md">
            <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-800">
              <div>
                <h2 className="font-semibold text-gray-900 dark:text-white">{editingItem.name}</h2>
                <p className="text-xs text-gray-500">{editingItem.description}</p>
              </div>
              <button
                onClick={() => setEditingItem(null)}
                className="p-1 text-gray-400 hover:text-gray-600"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-4 space-y-4 max-h-[60vh] overflow-auto">
              {Object.entries(editingItem.config_schema || {}).map(([fieldName, field]) => (
                <div key={fieldName}>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    {field.display_name || fieldName}
                    {field.required && <span className="text-red-500 ml-1">*</span>}
                  </label>

                  {field.allowed_values ? (
                    <select
                      value={editValues[fieldName] || field.default || ''}
                      onChange={(e) => setEditValues({ ...editValues, [fieldName]: e.target.value })}
                      className="w-full bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg px-3 py-2 text-sm"
                    >
                      {field.allowed_values.map(v => (
                        <option key={v} value={v}>{v}</option>
                      ))}
                    </select>
                  ) : (
                    <div className="relative">
                      <input
                        type={field.type === 'secret' && !showSecrets[fieldName] ? 'password' : 'text'}
                        value={editValues[fieldName] || ''}
                        onChange={(e) => setEditValues({ ...editValues, [fieldName]: e.target.value })}
                        placeholder={field.placeholder || field.default || ''}
                        className="w-full bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg px-3 py-2 text-sm"
                      />
                      {field.type === 'secret' && (
                        <button
                          type="button"
                          onClick={() => setShowSecrets({ ...showSecrets, [fieldName]: !showSecrets[fieldName] })}
                          className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400"
                        >
                          {showSecrets[fieldName] ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                        </button>
                      )}
                    </div>
                  )}

                  {field.description && (
                    <p className="text-xs text-gray-500 mt-1">{field.description}</p>
                  )}
                </div>
              ))}
            </div>

            <div className="p-4 border-t border-gray-200 dark:border-gray-800 flex justify-end gap-3">
              <button
                onClick={() => setEditingItem(null)}
                className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900"
              >
                Cancel
              </button>
              <button
                onClick={saveConfig}
                disabled={saving}
                className="flex items-center gap-2 px-4 py-2 text-sm bg-orange-600 text-white rounded-lg hover:bg-orange-700 disabled:opacity-50"
              >
                <Save className="w-4 h-4" />
                {saving ? 'Saving...' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Tool Filtering Modal */}
      {filteringMcp && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
          <div className="bg-white dark:bg-gray-900 rounded-xl shadow-2xl w-full max-w-2xl">
            <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-800">
              <div>
                <h2 className="font-semibold text-gray-900 dark:text-white">Filter Tools - {filteringMcp.name}</h2>
                <p className="text-xs text-gray-500">Select which tools from this MCP server should be available</p>
              </div>
              <button
                onClick={() => setFilteringMcp(null)}
                className="p-1 text-gray-400 hover:text-gray-600"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-4 space-y-4 max-h-[60vh] overflow-auto">
              {/* Select All / Deselect All */}
              <div className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-800 rounded-lg">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                  {selectedTools.size === (filteringMcp.tools?.length || 0)
                    ? `All ${filteringMcp.tools?.length || 0} tools selected`
                    : `${selectedTools.size} of ${filteringMcp.tools?.length || 0} tools selected`
                  }
                </span>
                <div className="flex gap-2">
                  <button
                    onClick={() => {
                      // Handle both string and object arrays
                      const toolNames = filteringMcp.tools?.map(t =>
                        typeof t === 'string' ? t : (t.name || t.display_name)
                      ) || [];
                      setSelectedTools(new Set(toolNames));
                    }}
                    className="text-xs px-2 py-1 rounded bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 hover:opacity-80"
                  >
                    Select All
                  </button>
                  <button
                    onClick={() => {
                      setSelectedTools(new Set());
                    }}
                    className="text-xs px-2 py-1 rounded bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:opacity-80"
                  >
                    Deselect All
                  </button>
                </div>
              </div>

              {/* Tool List */}
              <div className="space-y-2">
                {filteringMcp.tools?.map((tool: any, idx: number) => {
                  // Handle both string arrays and object arrays
                  const toolName = typeof tool === 'string' ? tool : (tool.name || tool.display_name);
                  const toolDisplayName = typeof tool === 'string' ? tool : (tool.display_name || tool.name);
                  const toolDesc = typeof tool === 'string' ? undefined : tool.description;
                  const toolCategory = typeof tool === 'string' ? undefined : tool.category;

                  return (
                    <label
                      key={toolName || idx}
                      className="flex items-start gap-3 p-3 rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 cursor-pointer"
                    >
                      <input
                        type="checkbox"
                        checked={selectedTools.has(toolName)}
                        onChange={(e) => {
                          const next = new Set(selectedTools);
                          if (e.target.checked) {
                            next.add(toolName);
                          } else {
                            next.delete(toolName);
                          }
                          setSelectedTools(next);
                        }}
                        className="mt-1 w-4 h-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                      />
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium text-gray-900 dark:text-white">
                          {toolDisplayName}
                        </div>
                        {toolDesc && (
                          <div className="text-xs text-gray-500 mt-0.5">
                            {toolDesc}
                          </div>
                        )}
                        {toolCategory && (
                          <div className="mt-1">
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-50 dark:bg-cyan-900/30 text-cyan-700 dark:text-cyan-300">
                              {toolCategory}
                            </span>
                          </div>
                        )}
                      </div>
                    </label>
                  );
                })}
              </div>
            </div>

            <div className="p-4 border-t border-gray-200 dark:border-gray-800 flex justify-end gap-2">
              <button
                onClick={() => setFilteringMcp(null)}
                className="px-4 py-2 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
              >
                Cancel
              </button>
              <button
                onClick={async () => {
                  if (!filteringMcp) return;

                  setSaving(true);
                  try {
                    // Calculate enabled_tools
                    const enabledTools = selectedTools.size === filteringMcp.tools?.length
                      ? ['*']  // All tools selected = wildcard
                      : Array.from(selectedTools);

                    // Debug: Log what we're sending
                    console.log('🔍 Debug - selectedTools Set:', selectedTools);
                    console.log('🔍 Debug - enabledTools array:', enabledTools);
                    console.log('🔍 Debug - enabledTools types:', enabledTools.map(t => typeof t));

                    // IMPORTANT: Only send the specific MCP and field being updated
                    // Don't send the entire mcp_servers dict to avoid overwriting inherited configs
                    const patchRes = await fetch('/api/team/config', {
                      method: 'PATCH',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({
                        mcp_servers: {
                          [filteringMcp.id]: {
                            enabled_tools: enabledTools
                          }
                        }
                      }),
                    });

                    if (!patchRes.ok) {
                      const errorText = await patchRes.text();
                      let errorMsg = 'Failed to update tools filter';
                      try {
                        const errorData = JSON.parse(errorText);
                        errorMsg = errorData.detail || errorData.error || errorMsg;
                      } catch {
                        errorMsg = errorText || errorMsg;
                      }
                      throw new Error(errorMsg);
                    }

                    setMessage({ type: 'success', text: `Tool filter updated for ${filteringMcp.name}` });
                    setFilteringMcp(null);
                    loadItems();
                  } catch (error: any) {
                    console.error('Tool filter save error:', error);
                    setMessage({ type: 'error', text: error.message });
                  } finally {
                    setSaving(false);
                  }
                }}
                disabled={saving}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm"
              >
                {saving ? 'Saving...' : 'Save Filter'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add Custom Server Modal */}
      {showAddCustomModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
          <div className="bg-white dark:bg-gray-900 rounded-xl shadow-2xl w-full max-w-2xl">
            <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-800">
              <div>
                <h2 className="font-semibold text-gray-900 dark:text-white">Add Custom MCP Server</h2>
                <p className="text-xs text-gray-500">Add a custom Model Context Protocol server for your agents</p>
              </div>
              <button
                onClick={() => {
                  setShowAddCustomModal(false);
                  setNewServerForm({
                    name: '',
                    description: '',
                    command: '',
                    args: '',
                    env: '',
                  });
                  setPreviewedTools(null);
                  setMessage(null);
                }}
                className="p-1 text-gray-400 hover:text-gray-600"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-4 space-y-4 max-h-[70vh] overflow-auto">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Name <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  value={newServerForm.name}
                  onChange={(e) => setNewServerForm({ ...newServerForm, name: e.target.value })}
                  placeholder="e.g., Slack MCP"
                  className="w-full bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg px-3 py-2 text-sm"
                />
                <p className="text-xs text-gray-500 mt-1">A friendly name for this MCP server</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Description
                </label>
                <input
                  type="text"
                  value={newServerForm.description}
                  onChange={(e) => setNewServerForm({ ...newServerForm, description: e.target.value })}
                  placeholder="e.g., Provides Slack channel and message management tools"
                  className="w-full bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg px-3 py-2 text-sm"
                />
                <p className="text-xs text-gray-500 mt-1">Brief description of what this MCP provides</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Command <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  value={newServerForm.command}
                  onChange={(e) => setNewServerForm({ ...newServerForm, command: e.target.value })}
                  placeholder="e.g., npx or python or /path/to/executable"
                  className="w-full bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg px-3 py-2 text-sm font-mono"
                />
                <p className="text-xs text-gray-500 mt-1">The executable command to start the MCP server</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Arguments
                </label>
                <textarea
                  value={newServerForm.args}
                  onChange={(e) => setNewServerForm({ ...newServerForm, args: e.target.value })}
                  placeholder="One argument per line, e.g.:&#10;-m&#10;mcp_server_slack"
                  rows={4}
                  className="w-full bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg px-3 py-2 text-sm font-mono"
                />
                <p className="text-xs text-gray-500 mt-1">Command arguments (one per line)</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Environment Variables
                </label>
                <textarea
                  value={newServerForm.env}
                  onChange={(e) => setNewServerForm({ ...newServerForm, env: e.target.value })}
                  placeholder="One variable per line in KEY=VALUE format, e.g.:&#10;SLACK_TOKEN=xoxb-your-token&#10;SLACK_TEAM_ID=T1234567"
                  rows={5}
                  className="w-full bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg px-3 py-2 text-sm font-mono"
                />
                <p className="text-xs text-gray-500 mt-1">Environment variables in KEY=VALUE format (one per line)</p>
              </div>

              <div className="bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-700 rounded-lg p-3">
                <p className="text-xs text-gray-700 dark:text-gray-300">
                  <strong>Tip:</strong> MCP servers are executables that communicate via stdio. Common patterns:
                </p>
                <ul className="text-xs text-gray-600 dark:text-gray-400 mt-2 space-y-1 ml-4 list-disc">
                  <li><code className="bg-gray-100 dark:bg-gray-800 px-1 py-0.5 rounded">npx -y @modelcontextprotocol/server-name</code></li>
                  <li><code className="bg-gray-100 dark:bg-gray-800 px-1 py-0.5 rounded">python -m mcp_server_module</code></li>
                  <li><code className="bg-gray-100 dark:bg-gray-800 px-1 py-0.5 rounded">node /path/to/server.js</code></li>
                </ul>
              </div>

              {/* Preview Tools Section */}
              {previewedTools && previewedTools.success && (
                <div className="border border-gray-200 dark:border-gray-800 rounded-lg overflow-hidden">
                  <div className="bg-gray-50 dark:bg-gray-800/50 px-3 py-2 border-b border-gray-200 dark:border-gray-800">
                    <div className="flex items-center justify-between">
                      <h3 className="text-sm font-medium text-gray-900 dark:text-white">
                        Discovered Tools ({previewedTools.tool_count})
                      </h3>
                      {previewedTools.warnings.length > 0 && (
                        <div className="flex items-center gap-1 text-xs text-yellow-600 dark:text-yellow-400">
                          <AlertTriangle className="w-3 h-3" />
                          {previewedTools.warnings.length} warning{previewedTools.warnings.length !== 1 ? 's' : ''}
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Warnings */}
                  {previewedTools.warnings.length > 0 && (
                    <div className="bg-yellow-50 dark:bg-yellow-900/20 border-b border-yellow-200 dark:border-yellow-800 px-3 py-2">
                      {previewedTools.warnings.map((warning, idx) => (
                        <div key={idx} className="flex items-start gap-2 text-xs text-yellow-800 dark:text-yellow-300">
                          <AlertTriangle className="w-3 h-3 mt-0.5 flex-shrink-0" />
                          <span>{warning}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Tools List */}
                  <div className="max-h-60 overflow-auto p-3 space-y-2">
                    {previewedTools.tools.length === 0 ? (
                      <p className="text-xs text-gray-500 text-center py-4">No tools discovered</p>
                    ) : (
                      (() => {
                        // Group tools by category
                        const toolsByCategory = previewedTools.tools.reduce((acc, tool) => {
                          const cat = tool.category || 'Other';
                          if (!acc[cat]) acc[cat] = [];
                          acc[cat].push(tool);
                          return acc;
                        }, {} as Record<string, typeof previewedTools.tools>);

                        return Object.entries(toolsByCategory).map(([category, tools]) => (
                          <div key={category} className="space-y-1">
                            <h4 className="text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide">
                              {category} ({tools.length})
                            </h4>
                            {tools.map((tool, idx) => (
                              <div
                                key={idx}
                                className="bg-gray-50 dark:bg-gray-800/50 rounded px-2 py-1.5 border border-gray-200 dark:border-gray-700"
                              >
                                <div className="flex items-start justify-between gap-2">
                                  <div className="flex-1 min-w-0">
                                    <p className="text-xs font-mono text-gray-900 dark:text-white truncate">
                                      {tool.display_name}
                                    </p>
                                    {tool.description && (
                                      <p className="text-xs text-gray-500 line-clamp-1 mt-0.5">
                                        {tool.description}
                                      </p>
                                    )}
                                  </div>
                                  <CheckCircle className="w-3 h-3 text-green-500 flex-shrink-0 mt-0.5" />
                                </div>
                              </div>
                            ))}
                          </div>
                        ));
                      })()
                    )}
                  </div>
                </div>
              )}
            </div>

            <div className="p-4 border-t border-gray-200 dark:border-gray-800 flex justify-between gap-3">
              <button
                onClick={previewMCPServer}
                disabled={previewingTools || !newServerForm.command}
                className="flex items-center gap-2 px-4 py-2 text-sm bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Eye className="w-4 h-4" />
                {previewingTools ? 'Previewing...' : 'Preview Tools'}
              </button>
              <div className="flex gap-3">
                <button
                  onClick={() => {
                    setShowAddCustomModal(false);
                    setNewServerForm({
                      name: '',
                      description: '',
                      command: '',
                      args: '',
                      env: '',
                    });
                    setPreviewedTools(null);
                    setMessage(null);
                  }}
                  className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900"
                >
                  Cancel
                </button>
                <button
                  onClick={saveCustomServer}
                  disabled={saving || !newServerForm.name || !newServerForm.command}
                  className="flex items-center gap-2 px-4 py-2 text-sm bg-orange-600 text-white rounded-lg hover:bg-orange-700 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <Plus className="w-4 h-4" />
                  {saving ? 'Adding...' : 'Add MCP Server'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
