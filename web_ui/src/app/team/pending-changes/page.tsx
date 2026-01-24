'use client';

import { useEffect, useState, useCallback } from 'react';
import { useIdentity } from '@/lib/useIdentity';
import { apiFetch } from '@/lib/apiClient';
import {
  Clock,
  CheckCircle,
  XCircle,
  Loader2,
  GitPullRequest,
  Sparkles,
  FileCode,
  Server,
  BookOpen,
  ChevronDown,
  ChevronRight,
  Eye,
} from 'lucide-react';

interface Evidence {
  source_type: string;  // 'slack_thread', 'confluence_doc', 'agent_trace', etc.
  source_id: string;
  quote: string;
  link_hint?: string;  // channel name, doc title, or context for creating links
  link?: string;       // full URL if available
}

interface PendingChange {
  id: string;
  changeType: 'prompt' | 'mcp' | 'knowledge' | 'tool';
  status: 'pending' | 'approved' | 'rejected';
  title: string;
  description: string;
  proposedBy: string;
  proposedAt: string;
  source: 'ai_pipeline' | 'manual';
  confidence?: number;  // 0.0-1.0, from AI pipeline proposals
  evidence?: Evidence[];  // supporting evidence from AI pipeline
  diff?: {
    before?: any;
    after?: any;
  };
  reviewedBy?: string;
  reviewedAt?: string;
  reviewComment?: string;
}

const getTypeIcon = (type: string) => {
  switch (type) {
    case 'prompt':
      return <FileCode className="w-4 h-4" />;
    case 'mcp':
      return <Server className="w-4 h-4" />;
    case 'knowledge':
      return <BookOpen className="w-4 h-4" />;
    case 'tool':
      return <Server className="w-4 h-4" />;
    default:
      return <GitPullRequest className="w-4 h-4" />;
  }
};

const getTypeLabel = (type: string) => {
  switch (type) {
    case 'prompt':
      return 'Agent Prompt';
    case 'mcp':
      return 'MCP Server';
    case 'knowledge':
      return 'Knowledge Base';
    case 'tool':
      return 'Tool / Integration';
    default:
      return type;
  }
};

const getConfidenceBadge = (confidence?: number) => {
  if (confidence === undefined) return null;
  const pct = Math.round(confidence * 100);
  const isHigh = confidence >= 0.8;
  return (
    <span
      className={`text-xs px-2 py-0.5 rounded-full ${
        isHigh
          ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400'
          : 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400'
      }`}
    >
      {pct}% confidence
    </span>
  );
};

const getSourceTypeLabel = (sourceType: string) => {
  switch (sourceType) {
    case 'slack_thread':
      return 'Slack';
    case 'confluence_doc':
      return 'Confluence';
    case 'agent_trace':
      return 'Agent Run';
    case 'gdoc':
      return 'Google Doc';
    default:
      return sourceType.replace(/_/g, ' ');
  }
};

export default function TeamPendingChangesPage() {
  const { identity } = useIdentity();
  const [changes, setChanges] = useState<PendingChange[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [processing, setProcessing] = useState<string | null>(null);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [filter, setFilter] = useState<'all' | 'pending' | 'reviewed'>('pending');
  
  const teamId = identity?.team_node_id;

  const loadChanges = useCallback(async () => {
    if (!teamId) return;
    setLoading(true);
    try {
      const res = await apiFetch(`/api/team/pending-changes`);
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data)) {
          setChanges(data);
        }
      }
    } catch (e) {
      console.error('Failed to load pending changes', e);
    } finally {
      setLoading(false);
    }
  }, [teamId]);

  useEffect(() => {
    loadChanges();
  }, [loadChanges]);

  const handleApprove = async (changeId: string) => {
    setProcessing(changeId);
    try {
      const res = await apiFetch(`/api/team/pending-changes/${changeId}/approve`, {
        method: 'POST',
      });
      
      if (res.ok) {
        setChanges((prev) =>
          prev.map((c) =>
            c.id === changeId
              ? {
                  ...c,
                  status: 'approved' as const,
                  reviewedBy: 'user',
                  reviewedAt: new Date().toISOString(),
                }
              : c
          )
        );
        setMessage({ type: 'success', text: 'Change approved!' });
      } else {
        const err = await res.json();
        setMessage({ type: 'error', text: err.detail || 'Failed to approve' });
      }
    } catch (e: any) {
      setMessage({ type: 'error', text: e?.message || 'Failed to approve' });
    } finally {
      setProcessing(null);
    }
  };

  const handleReject = async (changeId: string) => {
    setProcessing(changeId);
    try {
      const res = await apiFetch(`/api/team/pending-changes/${changeId}/reject`, {
        method: 'POST',
      });
      
      if (res.ok) {
        setChanges((prev) =>
          prev.map((c) =>
            c.id === changeId
              ? {
                  ...c,
                  status: 'rejected' as const,
                  reviewedBy: 'user',
                  reviewedAt: new Date().toISOString(),
                }
              : c
          )
        );
        setMessage({ type: 'success', text: 'Change rejected' });
      } else {
        const err = await res.json();
        setMessage({ type: 'error', text: err.detail || 'Failed to reject' });
      }
    } catch (e: any) {
      setMessage({ type: 'error', text: e?.message || 'Failed to reject' });
    } finally {
      setProcessing(null);
    }
  };

  const filteredChanges = changes.filter((c) => {
    if (filter === 'pending') return c.status === 'pending';
    if (filter === 'reviewed') return c.status !== 'pending';
    return true;
  });

  const pendingCount = changes.filter((c) => c.status === 'pending').length;

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
      </div>
    );
  }

  return (
    <div className="h-[calc(100vh-48px)] flex flex-col p-6 max-w-4xl mx-auto">
      {/* Header - Fixed */}
      <div className="flex items-center justify-between mb-6 flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-orange-500 to-amber-500 flex items-center justify-center">
            <GitPullRequest className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold text-gray-900 dark:text-white">
              Proposed Changes
            </h1>
            <p className="text-sm text-gray-500">
              Review and approve AI-proposed changes to your team's configuration.
            </p>
          </div>
        </div>
        {pendingCount > 0 && (
          <div className="flex items-center gap-2 px-3 py-1.5 bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-400 rounded-full text-sm font-medium">
            <Clock className="w-4 h-4" />
            {pendingCount} pending
          </div>
        )}
      </div>

      {/* Message - Fixed */}
      {message && (
        <div
          className={`mb-6 p-4 rounded-xl flex items-center gap-3 flex-shrink-0 ${
            message.type === 'success'
              ? 'bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 text-green-700 dark:text-green-400'
              : 'bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-400'
          }`}
        >
          {message.type === 'success' ? <CheckCircle className="w-5 h-5" /> : <XCircle className="w-5 h-5" />}
          {message.text}
        </div>
      )}

      {/* Filter Tabs - Fixed */}
      <div className="flex items-center gap-2 mb-6 flex-shrink-0">
        {(['pending', 'reviewed', 'all'] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-4 py-2 text-sm rounded-lg transition-colors ${
              filter === f
                ? 'bg-gray-200 dark:bg-gray-700 text-gray-900 dark:text-white'
                : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700'
            }`}
          >
            {f === 'pending' ? 'Pending' : f === 'reviewed' ? 'Reviewed' : 'All'}
          </button>
        ))}
      </div>

      {/* Changes List - Scrollable */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {filteredChanges.length === 0 ? (
          <div className="bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-12 text-center">
            <GitPullRequest className="w-12 h-12 mx-auto text-gray-300 dark:text-gray-600 mb-4" />
            <p className="text-gray-500">
              {filter === 'pending' ? 'No pending changes to review.' : 'No changes found.'}
            </p>
          </div>
        ) : (
          <div className="space-y-4 pb-4">
            {filteredChanges.map((change) => (
            <div
              key={change.id}
              className={`bg-white dark:bg-gray-900 border rounded-xl overflow-hidden ${
                change.status === 'pending'
                  ? 'border-orange-200 dark:border-orange-800'
                  : 'border-gray-200 dark:border-gray-800'
              }`}
            >
              <div
                className="p-4 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800/50"
                onClick={() => setExpandedId(expandedId === change.id ? null : change.id)}
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-start gap-3">
                    <div
                      className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 ${
                        change.source === 'ai_pipeline'
                          ? 'bg-gray-100 dark:bg-gray-800 text-gray-600'
                          : 'bg-gray-100 dark:bg-gray-800 text-gray-600'
                      }`}
                    >
                      {change.source === 'ai_pipeline' ? (
                        <Sparkles className="w-5 h-5" />
                      ) : (
                        getTypeIcon(change.changeType)
                      )}
                    </div>
                    <div>
                      <div className="flex items-center gap-2 mb-1">
                        <span
                          className={`text-xs px-2 py-0.5 rounded-full ${
                            change.status === 'pending'
                              ? 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-400'
                              : change.status === 'approved'
                              ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400'
                              : 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400'
                          }`}
                        >
                          {change.status}
                        </span>
                        <span className="text-xs text-gray-500 flex items-center gap-1">
                          {getTypeIcon(change.changeType)}
                          {getTypeLabel(change.changeType)}
                        </span>
                        {getConfidenceBadge(change.confidence)}
                      </div>
                      <h3 className="font-medium text-gray-900 dark:text-white">{change.title}</h3>
                      <p className="text-sm text-gray-500 mt-1">{change.description}</p>
                      <div className="flex items-center gap-3 mt-2 text-xs text-gray-400">
                        <span>by {change.proposedBy}</span>
                        <span>{new Date(change.proposedAt).toLocaleString()}</span>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {expandedId === change.id ? (
                      <ChevronDown className="w-5 h-5 text-gray-400" />
                    ) : (
                      <ChevronRight className="w-5 h-5 text-gray-400" />
                    )}
                  </div>
                </div>
              </div>

              {/* Expanded Content */}
              {expandedId === change.id && (
                <div className="border-t border-gray-200 dark:border-gray-800 p-4 bg-gray-50 dark:bg-gray-950">
                  {/* Diff View */}
                  {change.diff && (
                    <div className="mb-4">
                      <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Changes</h4>
                      <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
                        {change.diff.before && (
                          <div className="p-3 border-b border-gray-200 dark:border-gray-700 bg-red-50 dark:bg-red-900/10">
                            <div className="text-xs text-red-600 mb-1">- Before</div>
                            <pre className="text-xs text-gray-700 dark:text-gray-300 whitespace-pre-wrap">
                              {typeof change.diff.before === 'string'
                                ? change.diff.before
                                : JSON.stringify(change.diff.before, null, 2)}
                            </pre>
                          </div>
                        )}
                        {change.diff.after && (
                          <div className="p-3 bg-green-50 dark:bg-green-900/10">
                            <div className="text-xs text-green-600 mb-1">+ After</div>
                            <pre className="text-xs text-gray-700 dark:text-gray-300 whitespace-pre-wrap">
                              {typeof change.diff.after === 'string'
                                ? change.diff.after
                                : JSON.stringify(change.diff.after, null, 2)}
                            </pre>
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Evidence Section */}
                  {change.evidence && change.evidence.length > 0 && (
                    <div className="mb-4">
                      <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2">
                        <Eye className="w-4 h-4" />
                        Supporting Evidence ({change.evidence.length})
                      </h4>
                      <div className="space-y-2">
                        {change.evidence.map((ev, idx) => (
                          <div
                            key={idx}
                            className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg p-3"
                          >
                            <div className="flex items-center gap-2 mb-2">
                              <span className="text-xs px-2 py-0.5 rounded-full bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400">
                                {getSourceTypeLabel(ev.source_type)}
                              </span>
                              {ev.link_hint && (
                                <span className="text-xs text-gray-500">
                                  {ev.link_hint}
                                </span>
                              )}
                            </div>
                            <blockquote className="text-sm text-gray-600 dark:text-gray-400 italic border-l-2 border-gray-300 dark:border-gray-600 pl-3">
                              &ldquo;{ev.quote}&rdquo;
                            </blockquote>
                            {ev.link && (
                              <a
                                href={ev.link}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-xs text-blue-600 dark:text-blue-400 hover:underline mt-2 inline-block"
                              >
                                View source →
                              </a>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Review Info */}
                  {change.reviewedBy && (
                    <div className="mb-4 p-3 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg">
                      <p className="text-sm text-gray-600 dark:text-gray-400">
                        <span className="font-medium">Reviewed by:</span> {change.reviewedBy}
                      </p>
                      <p className="text-sm text-gray-600 dark:text-gray-400">
                        <span className="font-medium">Date:</span>{' '}
                        {new Date(change.reviewedAt!).toLocaleString()}
                      </p>
                      {change.reviewComment && (
                        <p className="text-sm text-gray-600 dark:text-gray-400 mt-2">
                          <span className="font-medium">Comment:</span> {change.reviewComment}
                        </p>
                      )}
                    </div>
                  )}

                  {/* Actions */}
                  {change.status === 'pending' && (
                    <div className="flex items-center justify-end gap-3">
                      <button
                        onClick={() => handleReject(change.id)}
                        disabled={processing === change.id}
                        className="px-4 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-50"
                      >
                        Reject
                      </button>
                      <button
                        onClick={() => handleApprove(change.id)}
                        disabled={processing === change.id}
                        className="flex items-center gap-2 px-4 py-2 text-sm bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50"
                      >
                        {processing === change.id ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                          <CheckCircle className="w-4 h-4" />
                        )}
                        Approve
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

