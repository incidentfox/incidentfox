'use client';

import { useState, useEffect } from 'react';
import { apiFetch } from '@/lib/apiClient';
import {
  ChevronDown,
  ChevronRight,
  Wrench,
  Bot,
  CheckCircle,
  XCircle,
  Loader2,
  Clock,
  Code,
} from 'lucide-react';

interface ToolCall {
  id: string;
  toolName: string;
  agentName?: string;
  parentAgent?: string;
  toolInput?: Record<string, any>;
  toolOutput?: string;
  startedAt: string;
  durationMs?: number;
  status: string;
  errorMessage?: string;
  sequenceNumber: number;
}

interface TraceData {
  runId: string;
  toolCalls: ToolCall[];
  total: number;
}

interface TraceViewerProps {
  runId: string;
  correlationId: string;
}

const getStatusIcon = (status: string) => {
  switch (status) {
    case 'success':
      return <CheckCircle className="w-3.5 h-3.5 text-green-500" />;
    case 'error':
      return <XCircle className="w-3.5 h-3.5 text-red-500" />;
    case 'running':
      return <Loader2 className="w-3.5 h-3.5 text-blue-500 animate-spin" />;
    default:
      return <Clock className="w-3.5 h-3.5 text-gray-400" />;
  }
};

const formatDuration = (ms?: number) => {
  if (!ms) return '-';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
};

const AGENT_COLORS: Record<string, string> = {
  planner: 'border-l-purple-500',
  investigation_agent: 'border-l-blue-500',
  k8s_agent: 'border-l-cyan-500',
  aws_agent: 'border-l-orange-500',
  metrics_agent: 'border-l-green-500',
  coding_agent: 'border-l-pink-500',
  log_analysis_agent: 'border-l-yellow-500',
  github_agent: 'border-l-gray-500',
};

export function TraceViewer({ runId, correlationId }: TraceViewerProps) {
  const [trace, setTrace] = useState<TraceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedCalls, setExpandedCalls] = useState<Set<string>>(new Set());

  useEffect(() => {
    async function loadTrace() {
      setLoading(true);
      setError(null);
      try {
        const res = await apiFetch(`/api/team/agent-runs/${runId}/trace`);
        if (res.ok) {
          const data = await res.json();
          setTrace(data);
        } else {
          const errData = await res.json().catch(() => ({}));
          setError(errData.error || `Failed to load trace (${res.status})`);
        }
      } catch (e: any) {
        setError(e?.message || 'Failed to load trace');
      } finally {
        setLoading(false);
      }
    }
    loadTrace();
  }, [runId]);

  const toggleCall = (callId: string) => {
    setExpandedCalls((prev) => {
      const next = new Set(prev);
      if (next.has(callId)) {
        next.delete(callId);
      } else {
        next.add(callId);
      }
      return next;
    });
  };

  // Group tool calls by agent
  const groupedByAgent = (trace?.toolCalls || []).reduce((acc, tc) => {
    const agent = tc.agentName || 'unknown';
    if (!acc[agent]) acc[agent] = [];
    acc[agent].push(tc);
    return acc;
  }, {} as Record<string, ToolCall[]>);

  if (loading) {
    return (
      <div className="py-4 flex items-center justify-center text-gray-400">
        <Loader2 className="w-5 h-5 animate-spin mr-2" />
        Loading trace...
      </div>
    );
  }

  if (error) {
    return (
      <div className="py-4 text-center text-gray-500">
        <p className="text-sm">{error}</p>
      </div>
    );
  }

  if (!trace || trace.toolCalls.length === 0) {
    return (
      <div className="py-4 text-center text-gray-500">
        <Wrench className="w-8 h-8 mx-auto mb-2 text-gray-300" />
        <p className="text-sm">No tool calls recorded for this run.</p>
        <p className="text-xs text-gray-400 mt-1">
          Trace data may not be available for older runs.
        </p>
      </div>
    );
  }

  return (
    <div className="mt-4">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 flex items-center gap-2">
          <Wrench className="w-4 h-4" />
          Execution Trace ({trace.total} tool calls)
        </h4>
        <a
          href={`https://platform.openai.com/traces?trace_id=${correlationId}`}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-blue-600 hover:text-blue-700 dark:text-blue-400 hover:underline"
        >
          View in OpenAI Dashboard
        </a>
      </div>

      <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
        {/* Render by agent groups if multiple agents */}
        {Object.keys(groupedByAgent).length > 1 ? (
          Object.entries(groupedByAgent).map(([agentName, calls]) => (
            <div key={agentName}>
              <div className="px-3 py-2 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 flex items-center gap-2">
                <Bot className="w-4 h-4 text-gray-500" />
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                  {agentName.replace(/_/g, ' ')}
                </span>
                <span className="text-xs text-gray-400">({calls.length} calls)</span>
              </div>
              {calls.map((tc) => (
                <ToolCallRow
                  key={tc.id}
                  call={tc}
                  isExpanded={expandedCalls.has(tc.id)}
                  onToggle={() => toggleCall(tc.id)}
                  indent={tc.parentAgent ? 1 : 0}
                />
              ))}
            </div>
          ))
        ) : (
          // Single agent - just render calls
          trace.toolCalls.map((tc) => (
            <ToolCallRow
              key={tc.id}
              call={tc}
              isExpanded={expandedCalls.has(tc.id)}
              onToggle={() => toggleCall(tc.id)}
              indent={0}
            />
          ))
        )}
      </div>
    </div>
  );
}

interface ToolCallRowProps {
  call: ToolCall;
  isExpanded: boolean;
  onToggle: () => void;
  indent: number;
}

function ToolCallRow({ call, isExpanded, onToggle, indent }: ToolCallRowProps) {
  const agentColor = AGENT_COLORS[call.agentName || ''] || 'border-l-gray-400';

  return (
    <div
      className={`border-b border-gray-100 dark:border-gray-800 last:border-b-0 border-l-2 ${agentColor}`}
      style={{ marginLeft: indent * 16 }}
    >
      <div
        className="px-3 py-2 flex items-center gap-3 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800/50"
        onClick={onToggle}
      >
        <div className="flex-shrink-0">
          {isExpanded ? (
            <ChevronDown className="w-4 h-4 text-gray-400" />
          ) : (
            <ChevronRight className="w-4 h-4 text-gray-400" />
          )}
        </div>
        <div className="flex-shrink-0">{getStatusIcon(call.status)}</div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm text-gray-900 dark:text-white">
              {call.toolName}
            </span>
            {call.agentName && (
              <span className="text-xs text-gray-400">via {call.agentName}</span>
            )}
          </div>
        </div>
        <div className="flex-shrink-0 text-xs text-gray-400">
          {formatDuration(call.durationMs)}
        </div>
      </div>

      {isExpanded && (
        <div className="px-3 pb-3 pt-1 bg-gray-50 dark:bg-gray-950 border-t border-gray-100 dark:border-gray-800">
          {call.toolInput && Object.keys(call.toolInput).length > 0 && (
            <div className="mb-3">
              <div className="text-xs font-medium text-gray-500 mb-1 flex items-center gap-1">
                <Code className="w-3 h-3" />
                Input
              </div>
              <pre className="text-xs bg-gray-100 dark:bg-gray-900 p-2 rounded overflow-x-auto max-h-32 overflow-y-auto font-mono text-gray-700 dark:text-gray-300">
                {JSON.stringify(call.toolInput, null, 2)}
              </pre>
            </div>
          )}

          {call.toolOutput && (
            <div className="mb-3">
              <div className="text-xs font-medium text-gray-500 mb-1 flex items-center gap-1">
                <Code className="w-3 h-3" />
                Output
              </div>
              <pre className="text-xs bg-gray-100 dark:bg-gray-900 p-2 rounded overflow-x-auto max-h-48 overflow-y-auto font-mono text-gray-700 dark:text-gray-300 whitespace-pre-wrap">
                {call.toolOutput}
              </pre>
            </div>
          )}

          {call.errorMessage && (
            <div className="mb-3">
              <div className="text-xs font-medium text-red-500 mb-1">Error</div>
              <pre className="text-xs bg-red-50 dark:bg-red-900/20 p-2 rounded text-red-700 dark:text-red-400 whitespace-pre-wrap">
                {call.errorMessage}
              </pre>
            </div>
          )}

          <div className="text-xs text-gray-400 flex items-center gap-3">
            <span>#{call.sequenceNumber}</span>
            <span>{new Date(call.startedAt).toLocaleTimeString()}</span>
            {call.durationMs && <span>{formatDuration(call.durationMs)}</span>}
          </div>
        </div>
      )}
    </div>
  );
}

export default TraceViewer;
