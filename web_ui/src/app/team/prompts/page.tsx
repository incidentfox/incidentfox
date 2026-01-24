'use client';

import { useEffect, useState, useCallback } from 'react';
import { useIdentity } from '@/lib/useIdentity';
import { apiFetch } from '@/lib/apiClient';
import {
  MessageSquareText,
  Save,
  CheckCircle,
  XCircle,
  Loader2,
  Sparkles,
  Edit3,
  RotateCcw,
  ChevronDown,
  ChevronRight,
  Bot,
  AlertTriangle,
} from 'lucide-react';

interface AgentPrompt {
  agent: string;
  displayName: string;
  description: string;
  systemPrompt: string;
  isCustom: boolean;
  inheritedFrom?: string; // 'org' | 'group' | null
  orgDefault?: string;
}

interface ProposedPromptChange {
  id: string;
  agent: string;
  currentPrompt?: string;
  proposedPrompt: string;
  reason: string;
  learnedFrom?: string;
  proposedAt: string;
  status: 'pending' | 'approved' | 'rejected';
}

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

export default function TeamPromptsPage() {
  const { identity } = useIdentity();
  const [prompts, setPrompts] = useState<AgentPrompt[]>([]);
  const [proposedChanges, setProposedChanges] = useState<ProposedPromptChange[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'prompts' | 'proposed'>('prompts');
  const [editingAgent, setEditingAgent] = useState<string | null>(null);
  const [editedPrompt, setEditedPrompt] = useState('');
  const [expandedAgent, setExpandedAgent] = useState<string | null>(null);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const teamId = identity?.team_node_id;

  const loadData = useCallback(async () => {
    if (!teamId) return;
    setLoading(true);
    try {
      // Load both effective and raw config to understand inheritance
      const [effectiveRes, rawRes] = await Promise.all([
        apiFetch('/api/config/me/effective'),
        apiFetch('/api/config/me/raw'),
      ]);
      
      let effectivePrompts: Record<string, string> = {};
      let teamPrompts: Record<string, string> = {};
      let orgPrompts: Record<string, string> = {};
      
      if (effectiveRes.ok) {
        const config = await effectiveRes.json();
        effectivePrompts = config.agent_prompts || {};
      }
      
      if (rawRes.ok) {
        const rawData = await rawRes.json();
        // Extract team-level overrides and org-level defaults from raw config
        const configs = rawData.configs || {};
        const lineage = rawData.lineage || [];
        
        // Find org node (first in lineage, type 'org')
        const orgNode = lineage.find((n: any) => n.node_type === 'org');
        const teamNode = lineage.find((n: any) => n.node_type === 'team');
        
        if (orgNode && configs[orgNode.node_id]) {
          orgPrompts = configs[orgNode.node_id].agent_prompts || {};
        }
        if (teamNode && configs[teamNode.node_id]) {
          teamPrompts = configs[teamNode.node_id].agent_prompts || {};
        }
      }
      
      // Build prompts list with inheritance info
      const promptsList: AgentPrompt[] = Object.keys(AGENT_CONFIGS).map((agent) => {
        const hasTeamOverride = !!teamPrompts[agent];
        const hasOrgDefault = !!orgPrompts[agent];
        
        return {
          agent,
          displayName: AGENT_CONFIGS[agent].displayName,
          description: AGENT_CONFIGS[agent].description,
          systemPrompt: effectivePrompts[agent] || '',
          isCustom: hasTeamOverride,
          inheritedFrom: !hasTeamOverride && hasOrgDefault ? 'org' : undefined,
          orgDefault: orgPrompts[agent],
        };
      });
      setPrompts(promptsList);

      // Load proposed prompt changes
      const changesRes = await apiFetch('/api/team/pending-changes');
      if (changesRes.ok) {
        const changes = await changesRes.json();
        // Filter to only prompt-type changes
        const promptChanges = changes
          .filter((c: any) => c.changeType === 'prompt')
          .map((c: any) => ({
            id: c.id,
            agent: c.diff?.after?.agent || 'unknown',
            currentPrompt: c.diff?.before?.prompt,
            proposedPrompt: c.diff?.after?.prompt || c.diff?.after?.content || '',
            reason: c.description || 'AI Pipeline learned improvement',
            learnedFrom: c.diff?.after?.learned_from,
            proposedAt: c.proposedAt,
            status: c.status,
          }));
        setProposedChanges(promptChanges.filter((c: ProposedPromptChange) => c.status === 'pending'));
      }
    } catch (e) {
      console.error('Failed to load prompts', e);
    } finally {
      setLoading(false);
    }
  }, [teamId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleEdit = (agent: string, currentPrompt: string) => {
    setEditingAgent(agent);
    setEditedPrompt(currentPrompt);
  };

  const handleSave = async (agent: string) => {
    setSaving(agent);
    setMessage(null);
    try {
      const res = await apiFetch('/api/config/me', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          custom_prompts: {
            [agent]: editedPrompt,
          },
        }),
      });

      if (res.ok) {
        setPrompts((prev) =>
          prev.map((p) =>
            p.agent === agent
              ? { ...p, systemPrompt: editedPrompt, isCustom: true }
              : p
          )
        );
        setEditingAgent(null);
        setMessage({ type: 'success', text: 'Prompt saved!' });
      } else {
        const err = await res.json();
        setMessage({ type: 'error', text: err.detail || 'Failed to save' });
      }
    } catch (e: any) {
      setMessage({ type: 'error', text: e?.message || 'Failed to save' });
    } finally {
      setSaving(null);
    }
  };

  const handleReset = async (agent: string) => {
    setSaving(agent);
    setMessage(null);
    try {
      const res = await apiFetch('/api/config/me', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          custom_prompts: {
            [agent]: null, // null to remove override
          },
        }),
      });

      if (res.ok) {
        const prompt = prompts.find((p) => p.agent === agent);
        setPrompts((prev) =>
          prev.map((p) =>
            p.agent === agent
              ? { ...p, systemPrompt: '', isCustom: false }
              : p
          )
        );
        setMessage({ type: 'success', text: 'Prompt reset to default' });
      } else {
        const err = await res.json();
        setMessage({ type: 'error', text: err.detail || 'Failed to reset' });
      }
    } catch (e: any) {
      setMessage({ type: 'error', text: e?.message || 'Failed to reset' });
    } finally {
      setSaving(null);
    }
  };

  const handleApprove = async (changeId: string) => {
    try {
      const res = await apiFetch(`/api/team/pending-changes/${changeId}/approve`, {
        method: 'POST',
      });
      if (res.ok) {
        setProposedChanges((prev) => prev.filter((c) => c.id !== changeId));
        setMessage({ type: 'success', text: 'Prompt change approved!' });
        loadData(); // Reload to get updated prompts
      } else {
        const err = await res.json();
        setMessage({ type: 'error', text: err.detail || 'Failed to approve' });
      }
    } catch (e: any) {
      setMessage({ type: 'error', text: e?.message || 'Failed to approve' });
    }
  };

  const handleReject = async (changeId: string) => {
    try {
      const res = await apiFetch(`/api/team/pending-changes/${changeId}/reject`, {
        method: 'POST',
      });
      if (res.ok) {
        setProposedChanges((prev) => prev.filter((c) => c.id !== changeId));
        setMessage({ type: 'success', text: 'Prompt change rejected' });
      } else {
        const err = await res.json();
        setMessage({ type: 'error', text: err.detail || 'Failed to reject' });
      }
    } catch (e: any) {
      setMessage({ type: 'error', text: e?.message || 'Failed to reject' });
    }
  };

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
      </div>
    );
  }

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-orange-500 to-amber-500 flex items-center justify-center">
            <MessageSquareText className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold text-gray-900 dark:text-white">
              Agent Prompts
            </h1>
            <p className="text-sm text-gray-500">
              Customize system prompts for your team's AI agents.
            </p>
          </div>
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
          className={`pb-3 px-1 text-sm font-medium border-b-2 transition-colors ${
            activeTab === 'prompts'
              ? 'border-gray-900 dark:border-white text-gray-900 dark:text-white'
              : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
          }`}
        >
          Current Prompts ({prompts.length})
        </button>
        <button
          onClick={() => setActiveTab('proposed')}
          className={`pb-3 px-1 text-sm font-medium border-b-2 transition-colors flex items-center gap-2 ${
            activeTab === 'proposed'
              ? 'border-gray-900 dark:border-white text-gray-900 dark:text-white'
              : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
          }`}
        >
          <Sparkles className="w-4 h-4" />
          AI Proposed ({proposedChanges.length})
          {proposedChanges.length > 0 && (
            <span className="w-2 h-2 rounded-full bg-gray-500 animate-pulse" />
          )}
        </button>
      </div>

      {activeTab === 'prompts' && (
        <div className="space-y-4">
          {prompts.map((prompt) => {
            const config = AGENT_CONFIGS[prompt.agent];
            const isExpanded = expandedAgent === prompt.agent;
            const isEditing = editingAgent === prompt.agent;

            return (
              <div
                key={prompt.agent}
                className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl overflow-hidden"
              >
                <div
                  className="p-4 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800/50"
                  onClick={() => setExpandedAgent(isExpanded ? null : prompt.agent)}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${config?.color || 'bg-gray-100 dark:bg-gray-800 text-gray-600'}`}>
                        <Bot className="w-5 h-5" />
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-gray-900 dark:text-white">
                            {prompt.displayName}
                          </span>
                          {prompt.isCustom ? (
                            <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400">
                              Customized
                            </span>
                          ) : prompt.inheritedFrom === 'org' ? (
                            <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400">
                              Inherited from Org
                            </span>
                          ) : prompt.systemPrompt ? (
                            <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-500">
                              Default
                            </span>
                          ) : null}
                        </div>
                        <p className="text-sm text-gray-500">{prompt.description}</p>
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
                            System Prompt
                          </label>
                          <textarea
                            value={editedPrompt}
                            onChange={(e) => setEditedPrompt(e.target.value)}
                            rows={10}
                            className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 font-mono text-sm"
                            placeholder="Enter custom system prompt..."
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
                            onClick={() => handleSave(prompt.agent)}
                            disabled={saving === prompt.agent}
                            className="flex items-center gap-2 px-4 py-2 bg-orange-600 text-white rounded-lg hover:bg-orange-700 disabled:opacity-50"
                          >
                            {saving === prompt.agent ? (
                              <Loader2 className="w-4 h-4 animate-spin" />
                            ) : (
                              <Save className="w-4 h-4" />
                            )}
                            Save Prompt
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="space-y-4">
                        <div>
                          <div className="flex items-center justify-between mb-2">
                            <label className="text-sm font-medium text-gray-700 dark:text-gray-300">
                              System Prompt
                            </label>
                            <div className="flex items-center gap-2">
                              {prompt.isCustom && (
                                <button
                                  onClick={() => handleReset(prompt.agent)}
                                  disabled={saving === prompt.agent}
                                  className="flex items-center gap-1 px-3 py-1 text-xs text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
                                >
                                  <RotateCcw className="w-3 h-3" />
                                  Reset to Default
                                </button>
                              )}
                              <button
                                onClick={() => handleEdit(prompt.agent, prompt.systemPrompt)}
                                className="flex items-center gap-1 px-3 py-1 text-xs bg-gray-100 dark:bg-gray-800 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700"
                              >
                                <Edit3 className="w-3 h-3" />
                                Edit
                              </button>
                            </div>
                          </div>
                          <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg p-3 font-mono text-sm text-gray-700 dark:text-gray-300 max-h-64 overflow-y-auto">
                            {prompt.systemPrompt || (
                              <span className="text-gray-400 italic">No prompt configured</span>
                            )}
                          </div>
                          {prompt.inheritedFrom === 'org' && !prompt.isCustom && (
                            <div className="mt-2 p-2 bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded-lg">
                              <p className="text-xs text-emerald-600 dark:text-emerald-400">
                                ✓ Using org-level default. Customize this prompt to override for your team only.
                              </p>
                            </div>
                          )}
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

      {activeTab === 'proposed' && (
        <div className="space-y-4">
          {proposedChanges.length === 0 ? (
            <div className="bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-12 text-center">
              <Sparkles className="w-12 h-12 mx-auto text-gray-300 dark:text-gray-600 mb-4" />
              <p className="text-gray-500">No pending AI-proposed prompt changes.</p>
              <p className="text-xs text-gray-400 mt-2">
                The AI Pipeline will propose prompt improvements based on incident patterns.
              </p>
            </div>
          ) : (
            proposedChanges.map((change) => {
              const config = AGENT_CONFIGS[change.agent];
              return (
                <div
                  key={change.id}
                  className="bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-700 rounded-xl p-5"
                >
                  <div className="flex items-start justify-between mb-4">
                    <div className="flex items-center gap-3">
                      <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${config?.color || 'bg-gray-100 dark:bg-gray-800 text-gray-600'}`}>
                        <Sparkles className="w-5 h-5" />
                      </div>
                      <div>
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400">
                            Prompt Update
                          </span>
                          <span className="font-medium text-gray-900 dark:text-white">
                            {config?.displayName || change.agent}
                          </span>
                        </div>
                        <p className="text-sm text-gray-600 dark:text-gray-400">{change.reason}</p>
                        {change.learnedFrom && (
                          <p className="text-xs text-gray-500 mt-1">
                            Learned from: {change.learnedFrom}
                          </p>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => handleReject(change.id)}
                        className="px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800"
                      >
                        Reject
                      </button>
                      <button
                        onClick={() => handleApprove(change.id)}
                        className="px-3 py-1.5 text-sm bg-green-600 text-white rounded-lg hover:bg-green-700"
                      >
                        Approve
                      </button>
                    </div>
                  </div>

                  {/* Diff View */}
                  <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
                    {change.currentPrompt && (
                      <div className="p-3 border-b border-gray-200 dark:border-gray-700 bg-red-50 dark:bg-red-900/10">
                        <div className="text-xs text-red-600 mb-1">- Current</div>
                        <pre className="text-xs text-gray-700 dark:text-gray-300 whitespace-pre-wrap font-mono max-h-32 overflow-y-auto">
                          {change.currentPrompt.slice(0, 500)}
                          {change.currentPrompt.length > 500 && '...'}
                        </pre>
                      </div>
                    )}
                    <div className="p-3 bg-green-50 dark:bg-green-900/10">
                      <div className="text-xs text-green-600 mb-1">+ Proposed</div>
                      <pre className="text-xs text-gray-700 dark:text-gray-300 whitespace-pre-wrap font-mono max-h-32 overflow-y-auto">
                        {change.proposedPrompt.slice(0, 500)}
                        {change.proposedPrompt.length > 500 && '...'}
                      </pre>
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>
      )}

      {/* Info */}
      <div className="mt-8 p-4 bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-700 rounded-xl">
        <div className="flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-gray-500 mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-sm text-gray-800 dark:text-gray-200 font-medium">
              About Custom Prompts
            </p>
            <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
              Custom prompts override the default system prompts for your team's agents. 
              AI Pipeline may suggest improvements based on patterns learned from your incidents.
              Use "Reset to Default" to revert to org-level defaults.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

