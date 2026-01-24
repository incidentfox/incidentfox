'use client';

import { useEffect, useState, useCallback } from 'react';
import { RequireRole } from '@/components/RequireRole';
import { apiFetch } from '@/lib/apiClient';
import { useIdentity } from '@/lib/useIdentity';
import {
  Settings2,
  MessageSquareText,
  Server,
  Save,
  CheckCircle,
  XCircle,
  Loader2,
  ChevronDown,
  ChevronRight,
  Bot,
  Plus,
  Trash2,
  Edit3,
  AlertTriangle,
  Building,
} from 'lucide-react';

// Agent configurations
const AGENT_CONFIGS: Record<string, { displayName: string; description: string; color: string }> = {
  planner: {
    displayName: 'Planner Agent',
    description: 'Orchestrates complex tasks across multiple agents',
    color: 'bg-gray-100 dark:bg-gray-800 text-gray-600',
  },
  investigation_agent: {
    displayName: 'Investigation Agent',
    description: 'Full troubleshooting toolkit for incident investigation',
    color: 'bg-gray-100 dark:bg-gray-800 text-gray-600',
  },
  k8s_agent: {
    displayName: 'Kubernetes Agent',
    description: 'Kubernetes troubleshooting and diagnostics',
    color: 'bg-gray-100 dark:bg-gray-800 text-gray-600',
  },
  aws_agent: {
    displayName: 'AWS Agent',
    description: 'AWS resource debugging and monitoring',
    color: 'bg-gray-100 dark:bg-gray-800 text-gray-600',
  },
  coding_agent: {
    displayName: 'Coding Agent',
    description: 'Code analysis and fix suggestions',
    color: 'bg-gray-100 dark:bg-gray-800 text-gray-600',
  },
  metrics_agent: {
    displayName: 'Metrics Agent',
    description: 'Anomaly detection and metrics analysis',
    color: 'bg-gray-100 dark:bg-gray-800 text-gray-600',
  },
};

interface MCPServer {
  name: string;
  type: string;
  transport: string;
  url?: string;
  command?: string;
  args?: string[];
  enabled: boolean;
}

interface AgentPrompt {
  agent: string;
  prompt: string;
}

export default function OrgDefaultsPage() {
  const { identity } = useIdentity();
  const [activeTab, setActiveTab] = useState<'prompts' | 'mcps'>('prompts');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Prompts state
  const [prompts, setPrompts] = useState<Record<string, string>>({});
  const [expandedAgent, setExpandedAgent] = useState<string | null>(null);
  const [editingAgent, setEditingAgent] = useState<string | null>(null);
  const [editedPrompt, setEditedPrompt] = useState('');

  // MCPs state
  const [mcpServers, setMcpServers] = useState<MCPServer[]>([]);
  const [showAddMcp, setShowAddMcp] = useState(false);
  const [newMcp, setNewMcp] = useState<MCPServer>({
    name: '',
    type: 'custom',
    transport: 'stdio',
    enabled: true,
  });

  const orgId = identity?.org_id || 'org1';

  // Load org-level config
  const loadOrgConfig = useCallback(async () => {
    setLoading(true);
    try {
      // Get the org root node's config
      const res = await apiFetch(`/api/admin/orgs/${orgId}/nodes/${orgId}/config`);
      if (res.ok) {
        const config = await res.json();
        setPrompts(config.agent_prompts || {});
        setMcpServers(config.mcp_servers || []);
      }
    } catch (e) {
      console.error('Failed to load org config', e);
    } finally {
      setLoading(false);
    }
  }, [orgId]);

  useEffect(() => {
    loadOrgConfig();
  }, [loadOrgConfig]);

  // Save prompts
  const handleSavePrompt = async (agent: string) => {
    setSaving(true);
    setMessage(null);
    try {
      const updatedPrompts = { ...prompts, [agent]: editedPrompt };
      const res = await apiFetch(`/api/admin/orgs/${orgId}/nodes/${orgId}/config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_prompts: updatedPrompts }),
      });

      if (res.ok) {
        setPrompts(updatedPrompts);
        setEditingAgent(null);
        setMessage({ type: 'success', text: `${AGENT_CONFIGS[agent]?.displayName || agent} prompt saved!` });
      } else {
        const err = await res.json();
        setMessage({ type: 'error', text: err.detail || 'Failed to save' });
      }
    } catch (e: any) {
      setMessage({ type: 'error', text: e?.message || 'Failed to save' });
    } finally {
      setSaving(false);
    }
  };

  // Delete prompt (reset to empty)
  const handleDeletePrompt = async (agent: string) => {
    if (!confirm(`Remove default prompt for ${AGENT_CONFIGS[agent]?.displayName || agent}?`)) return;
    
    setSaving(true);
    try {
      const updatedPrompts = { ...prompts };
      delete updatedPrompts[agent];

      const res = await apiFetch(`/api/admin/orgs/${orgId}/nodes/${orgId}/config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_prompts: updatedPrompts }),
      });

      if (res.ok) {
        setPrompts(updatedPrompts);
        setMessage({ type: 'success', text: 'Prompt removed' });
      }
    } catch (e: any) {
      setMessage({ type: 'error', text: e?.message || 'Failed to remove' });
    } finally {
      setSaving(false);
    }
  };

  // Add MCP
  const handleAddMcp = async () => {
    if (!newMcp.name.trim()) {
      setMessage({ type: 'error', text: 'MCP name is required' });
      return;
    }

    setSaving(true);
    try {
      const updatedMcps = [...mcpServers, newMcp];
      const res = await apiFetch(`/api/admin/orgs/${orgId}/nodes/${orgId}/config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mcp_servers: updatedMcps }),
      });

      if (res.ok) {
        setMcpServers(updatedMcps);
        setShowAddMcp(false);
        setNewMcp({ name: '', type: 'custom', transport: 'stdio', enabled: true });
        setMessage({ type: 'success', text: 'MCP server added!' });
      } else {
        const err = await res.json();
        setMessage({ type: 'error', text: err.detail || 'Failed to add' });
      }
    } catch (e: any) {
      setMessage({ type: 'error', text: e?.message || 'Failed to add' });
    } finally {
      setSaving(false);
    }
  };

  // Delete MCP
  const handleDeleteMcp = async (index: number) => {
    const mcp = mcpServers[index];
    if (!confirm(`Remove MCP server "${mcp.name}"?`)) return;

    setSaving(true);
    try {
      const updatedMcps = mcpServers.filter((_, i) => i !== index);
      const res = await apiFetch(`/api/admin/orgs/${orgId}/nodes/${orgId}/config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mcp_servers: updatedMcps }),
      });

      if (res.ok) {
        setMcpServers(updatedMcps);
        setMessage({ type: 'success', text: 'MCP server removed' });
      }
    } catch (e: any) {
      setMessage({ type: 'error', text: e?.message || 'Failed to remove' });
    } finally {
      setSaving(false);
    }
  };

  // Toggle MCP enabled
  const handleToggleMcp = async (index: number) => {
    const updatedMcps = mcpServers.map((m, i) =>
      i === index ? { ...m, enabled: !m.enabled } : m
    );

    try {
      const res = await apiFetch(`/api/admin/orgs/${orgId}/nodes/${orgId}/config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mcp_servers: updatedMcps }),
      });

      if (res.ok) {
        setMcpServers(updatedMcps);
      }
    } catch (e) {
      console.error(e);
    }
  };

  if (loading) {
    return (
      <RequireRole role="admin">
        <div className="p-8 flex items-center justify-center">
          <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
        </div>
      </RequireRole>
    );
  }

  return (
    <RequireRole role="admin">
      <div className="p-8 max-w-5xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900 dark:text-white flex items-center gap-3">
              <Building className="w-7 h-7 text-gray-500" />
              Organization Defaults
            </h1>
            <p className="text-sm text-gray-500 mt-1">
              Set org-wide default prompts and MCP servers. Teams inherit these but can override.
            </p>
          </div>
        </div>

        {/* Message */}
        {message && (
          <div
            className={`mb-6 p-4 rounded-xl flex items-center gap-3 ${
              message.type === 'success'
                ? 'bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 text-green-700 dark:text-green-400'
                : 'bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-400'
            }`}
          >
            {message.type === 'success' ? <CheckCircle className="w-5 h-5" /> : <XCircle className="w-5 h-5" />}
            {message.text}
          </div>
        )}

        {/* Tabs */}
        <div className="flex items-center gap-4 mb-6 border-b border-gray-200 dark:border-gray-800">
          <button
            onClick={() => setActiveTab('prompts')}
            className={`pb-3 px-1 text-sm font-medium border-b-2 transition-colors flex items-center gap-2 ${
              activeTab === 'prompts'
                ? 'border-emerald-500 text-emerald-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
            }`}
          >
            <MessageSquareText className="w-4 h-4" />
            Default Prompts ({Object.keys(prompts).length})
          </button>
          <button
            onClick={() => setActiveTab('mcps')}
            className={`pb-3 px-1 text-sm font-medium border-b-2 transition-colors flex items-center gap-2 ${
              activeTab === 'mcps'
                ? 'border-emerald-500 text-emerald-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
            }`}
          >
            <Server className="w-4 h-4" />
            Default MCPs ({mcpServers.length})
          </button>
        </div>

        {/* Prompts Tab */}
        {activeTab === 'prompts' && (
          <div className="space-y-4">
            {Object.keys(AGENT_CONFIGS).map((agent) => {
              const config = AGENT_CONFIGS[agent];
              const hasPrompt = !!prompts[agent];
              const isExpanded = expandedAgent === agent;
              const isEditing = editingAgent === agent;

              return (
                <div
                  key={agent}
                  className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl overflow-hidden"
                >
                  <div
                    className="p-4 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800/50"
                    onClick={() => setExpandedAgent(isExpanded ? null : agent)}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${config.color}`}>
                          <Bot className="w-5 h-5" />
                        </div>
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-gray-900 dark:text-white">
                              {config.displayName}
                            </span>
                            {hasPrompt ? (
                              <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400">
                                Configured
                              </span>
                            ) : (
                              <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-500">
                                Not Set
                              </span>
                            )}
                          </div>
                          <p className="text-sm text-gray-500">{config.description}</p>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        {isExpanded ? (
                          <ChevronDown className="w-5 h-5 text-gray-400" />
                        ) : (
                          <ChevronRight className="w-5 h-5 text-gray-400" />
                        )}
                      </div>
                    </div>
                  </div>

                  {isExpanded && (
                    <div className="border-t border-gray-200 dark:border-gray-800 p-4 bg-gray-50 dark:bg-gray-950">
                      {isEditing ? (
                        <div className="space-y-4">
                          <div>
                            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                              Default System Prompt
                            </label>
                            <textarea
                              value={editedPrompt}
                              onChange={(e) => setEditedPrompt(e.target.value)}
                              rows={10}
                              className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 font-mono text-sm"
                              placeholder="Enter default system prompt for all teams..."
                            />
                          </div>
                          <div className="flex items-center justify-between">
                            <button
                              onClick={() => setEditingAgent(null)}
                              className="px-4 py-2 text-sm text-gray-600 dark:text-gray-400"
                            >
                              Cancel
                            </button>
                            <button
                              onClick={() => handleSavePrompt(agent)}
                              disabled={saving}
                              className="flex items-center gap-2 px-4 py-2 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50"
                            >
                              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                              Save Default
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="space-y-4">
                          <div>
                            <div className="flex items-center justify-between mb-2">
                              <label className="text-sm font-medium text-gray-700 dark:text-gray-300">
                                Default System Prompt
                              </label>
                              <div className="flex items-center gap-2">
                                {hasPrompt && (
                                  <button
                                    onClick={() => handleDeletePrompt(agent)}
                                    className="flex items-center gap-1 px-3 py-1 text-xs text-red-600 hover:text-red-700"
                                  >
                                    <Trash2 className="w-3 h-3" />
                                    Remove
                                  </button>
                                )}
                                <button
                                  onClick={() => {
                                    setEditingAgent(agent);
                                    setEditedPrompt(prompts[agent] || '');
                                  }}
                                  className="flex items-center gap-1 px-3 py-1 text-xs bg-gray-100 dark:bg-gray-800 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700"
                                >
                                  <Edit3 className="w-3 h-3" />
                                  {hasPrompt ? 'Edit' : 'Add'}
                                </button>
                              </div>
                            </div>
                            <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg p-3 font-mono text-sm text-gray-700 dark:text-gray-300 max-h-64 overflow-y-auto">
                              {prompts[agent] || (
                                <span className="text-gray-400 italic">No default prompt configured</span>
                              )}
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* MCPs Tab */}
        {activeTab === 'mcps' && (
          <div className="space-y-4">
            {/* Add MCP Button */}
            <button
              onClick={() => setShowAddMcp(true)}
              className="w-full p-4 border-2 border-dashed border-gray-300 dark:border-gray-700 rounded-xl text-gray-500 hover:border-emerald-500 hover:text-emerald-600 transition-colors flex items-center justify-center gap-2"
            >
              <Plus className="w-5 h-5" />
              Add Default MCP Server
            </button>

            {/* MCP List */}
            {mcpServers.length === 0 ? (
              <div className="bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-12 text-center">
                <Server className="w-12 h-12 mx-auto text-cyan-300 dark:text-cyan-600 mb-4" />
                <p className="text-gray-500">No default MCP servers configured.</p>
                <p className="text-xs text-gray-400 mt-2">
                  Add MCP servers that all teams will inherit by default.
                </p>
              </div>
            ) : (
              mcpServers.map((mcp, index) => (
                <div
                  key={index}
                  className={`bg-white dark:bg-gray-900 border rounded-xl p-4 ${
                    mcp.enabled
                      ? 'border-gray-200 dark:border-gray-800'
                      : 'border-gray-200 dark:border-gray-800 opacity-60'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-lg bg-cyan-100 dark:bg-cyan-900/30 flex items-center justify-center">
                        <Server className="w-5 h-5 text-cyan-600" />
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-gray-900 dark:text-white">{mcp.name}</span>
                          <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-500">
                            {mcp.type}
                          </span>
                        </div>
                        <p className="text-sm text-gray-500">
                          {mcp.transport === 'http' ? mcp.url : mcp.command || 'stdio'}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={mcp.enabled}
                          onChange={() => handleToggleMcp(index)}
                          className="rounded"
                        />
                        <span className="text-xs text-gray-500">Enabled</span>
                      </label>
                      <button
                        onClick={() => handleDeleteMcp(index)}
                        className="p-2 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                </div>
              ))
            )}

            {/* Add MCP Modal */}
            {showAddMcp && (
              <div className="fixed inset-0 z-50 flex items-center justify-center">
                <div className="absolute inset-0 bg-black/50" onClick={() => setShowAddMcp(false)} />
                <div className="relative bg-white dark:bg-gray-900 rounded-xl shadow-2xl max-w-lg w-full mx-4 p-6">
                  <h3 className="text-lg font-semibold mb-4">Add Default MCP Server</h3>
                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm text-gray-600 dark:text-gray-400 mb-1">Name</label>
                      <input
                        value={newMcp.name}
                        onChange={(e) => setNewMcp({ ...newMcp, name: e.target.value })}
                        placeholder="e.g. Slack, Datadog"
                        className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
                      />
                    </div>
                    <div>
                      <label className="block text-sm text-gray-600 dark:text-gray-400 mb-1">Type</label>
                      <select
                        value={newMcp.type}
                        onChange={(e) => setNewMcp({ ...newMcp, type: e.target.value })}
                        className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
                      >
                        <option value="slack">Slack</option>
                        <option value="datadog">Datadog</option>
                        <option value="github">GitHub</option>
                        <option value="kubernetes">Kubernetes</option>
                        <option value="custom">Custom</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-sm text-gray-600 dark:text-gray-400 mb-1">Transport</label>
                      <select
                        value={newMcp.transport}
                        onChange={(e) => setNewMcp({ ...newMcp, transport: e.target.value })}
                        className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
                      >
                        <option value="stdio">stdio</option>
                        <option value="http">HTTP</option>
                      </select>
                    </div>
                    {newMcp.transport === 'http' && (
                      <div>
                        <label className="block text-sm text-gray-600 dark:text-gray-400 mb-1">URL</label>
                        <input
                          value={newMcp.url || ''}
                          onChange={(e) => setNewMcp({ ...newMcp, url: e.target.value })}
                          placeholder="https://mcp.example.com"
                          className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
                        />
                      </div>
                    )}
                    {newMcp.transport === 'stdio' && (
                      <div>
                        <label className="block text-sm text-gray-600 dark:text-gray-400 mb-1">Command</label>
                        <input
                          value={newMcp.command || ''}
                          onChange={(e) => setNewMcp({ ...newMcp, command: e.target.value })}
                          placeholder="e.g. npx mcp-server-slack"
                          className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
                        />
                      </div>
                    )}
                  </div>
                  <div className="flex justify-end gap-2 mt-6">
                    <button
                      onClick={() => setShowAddMcp(false)}
                      className="px-4 py-2 text-sm bg-gray-100 dark:bg-gray-800 rounded-lg"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={handleAddMcp}
                      disabled={saving}
                      className="px-4 py-2 text-sm bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50"
                    >
                      {saving ? 'Adding...' : 'Add MCP'}
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Info */}
        <div className="mt-8 p-4 bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl">
          <div className="flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-gray-500 mt-0.5 flex-shrink-0" />
            <div>
              <p className="text-sm text-gray-800 dark:text-gray-200 font-medium">
                About Organization Defaults
              </p>
              <p className="text-sm text-gray-600 dark:text-gray-300 mt-1">
                These are org-wide defaults that all teams inherit automatically. Teams can override 
                these in their own settings. Changes here will propagate to teams that haven&apos;t 
                customized their own values.
              </p>
            </div>
          </div>
        </div>
      </div>
    </RequireRole>
  );
}

