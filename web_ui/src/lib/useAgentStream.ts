'use client';

import { useState, useCallback, useRef } from 'react';

export interface AgentMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
  toolCalls?: ToolCall[];
  isStreaming?: boolean;
}

export interface ToolCall {
  id: string;
  name: string;
  status: 'running' | 'completed' | 'error';
  input?: Record<string, unknown>;
  output?: string;
  startedAt: Date;
  completedAt?: Date;
}

export interface StreamEvent {
  type: string;
  data: Record<string, unknown>;
}

interface UseAgentStreamOptions {
  /** Agent name to use. If not provided, uses team's configured entrance_agent from config. */
  agentName?: string;
  onComplete?: (output: string) => void;
  onError?: (error: string) => void;
}

export function useAgentStream(options: UseAgentStreamOptions = {}) {
  // Note: If agentName is undefined, the API route will fetch the team's entrance_agent from config
  const { agentName, onComplete, onError } = options;

  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [currentToolCalls, setCurrentToolCalls] = useState<ToolCall[]>([]);
  const abortControllerRef = useRef<AbortController | null>(null);
  const lastResponseIdRef = useRef<string | null>(null);

  const sendMessage = useCallback(async (userMessage: string) => {
    if (isStreaming) return;

    setError(null);
    setIsStreaming(true);

    // Add user message
    const userMsgId = `user-${Date.now()}`;
    const userMsg: AgentMessage = {
      id: userMsgId,
      role: 'user',
      content: userMessage,
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, userMsg]);

    // Add placeholder assistant message
    const assistantMsgId = `assistant-${Date.now()}`;
    const assistantMsg: AgentMessage = {
      id: assistantMsgId,
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      toolCalls: [],
      isStreaming: true,
    };
    setMessages(prev => [...prev, assistantMsg]);
    setCurrentToolCalls([]);

    // Create abort controller
    abortControllerRef.current = new AbortController();

    try {
      const response = await fetch('/api/team/agent/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: userMessage,
          // Only include agent_name if explicitly provided; otherwise API uses team's entrance_agent
          ...(agentName && { agent_name: agentName }),
          previous_response_id: lastResponseIdRef.current,
        }),
        signal: abortControllerRef.current.signal,
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || `HTTP ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error('No response body');

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Parse SSE events
        const lines = buffer.split('\n');
        buffer = lines.pop() || ''; // Keep incomplete line in buffer

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            // Event type line - handled with data line
          } else if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              handleStreamEvent(data, assistantMsgId);
            } catch (e) {
              // Ignore parse errors
            }
          }
        }
      }

    } catch (err) {
      if ((err as Error).name === 'AbortError') {
        // User cancelled
        setMessages(prev => prev.map(m =>
          m.id === assistantMsgId
            ? { ...m, content: m.content || 'Cancelled', isStreaming: false }
            : m
        ));
      } else {
        const errorMessage = (err as Error).message || 'Failed to run agent';
        setError(errorMessage);
        setMessages(prev => prev.map(m =>
          m.id === assistantMsgId
            ? { ...m, content: `Error: ${errorMessage}`, isStreaming: false }
            : m
        ));
        onError?.(errorMessage);
      }
    } finally {
      setIsStreaming(false);
      abortControllerRef.current = null;
    }
  }, [isStreaming, agentName, onError]);

  const handleStreamEvent = useCallback((event: Record<string, unknown>, assistantMsgId: string) => {
    const eventType = event.type as string || (event.agent ? 'agent_started' : 'unknown');

    switch (eventType) {
      case 'agent_started':
        // Agent started - no action needed
        break;

      case 'tool_started': {
        const toolCall: ToolCall = {
          id: `tool-${Date.now()}-${event.sequence}`,
          name: event.tool as string || 'unknown',
          status: 'running',
          input: event.input as Record<string, unknown>,
          startedAt: new Date(),
        };
        setCurrentToolCalls(prev => [...prev, toolCall]);
        setMessages(prev => prev.map(m =>
          m.id === assistantMsgId
            ? { ...m, toolCalls: [...(m.toolCalls || []), toolCall] }
            : m
        ));
        break;
      }

      case 'tool_completed': {
        const sequence = event.sequence as number;
        setCurrentToolCalls(prev => prev.map((tc, idx) =>
          idx === sequence - 1
            ? { ...tc, status: 'completed', output: event.output_preview as string, completedAt: new Date() }
            : tc
        ));
        setMessages(prev => prev.map(m => {
          if (m.id !== assistantMsgId) return m;
          const updatedToolCalls = (m.toolCalls || []).map((tc, idx) =>
            idx === sequence - 1
              ? { ...tc, status: 'completed' as const, output: event.output_preview as string, completedAt: new Date() }
              : tc
          );
          return { ...m, toolCalls: updatedToolCalls };
        }));
        break;
      }

      case 'message':
      case 'text_delta': {
        const content = event.content_preview as string || event.content as string || '';
        setMessages(prev => prev.map(m =>
          m.id === assistantMsgId
            ? { ...m, content: m.content + content }
            : m
        ));
        break;
      }

      case 'agent_completed': {
        const output = event.output as string || '';
        const lastResponseId = event.last_response_id as string;
        if (lastResponseId) {
          lastResponseIdRef.current = lastResponseId;
        }

        setMessages(prev => prev.map(m =>
          m.id === assistantMsgId
            ? { ...m, content: output || m.content, isStreaming: false }
            : m
        ));

        if (event.success) {
          onComplete?.(output);
        } else if (event.error) {
          setError(event.error as string);
          onError?.(event.error as string);
        }
        break;
      }

      case 'subagent_started':
      case 'subagent_completed':
        // Sub-agent events - could show nested progress
        break;
    }
  }, [onComplete, onError]);

  const cancel = useCallback(() => {
    abortControllerRef.current?.abort();
  }, []);

  const reset = useCallback(() => {
    setMessages([]);
    setError(null);
    setCurrentToolCalls([]);
    lastResponseIdRef.current = null;
  }, []);

  return {
    messages,
    isStreaming,
    error,
    currentToolCalls,
    sendMessage,
    cancel,
    reset,
  };
}
