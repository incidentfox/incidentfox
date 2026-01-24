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

  // Define handleStreamEvent FIRST so it can be used in sendMessage's dependency array
  const handleStreamEvent = useCallback((event: Record<string, unknown>, assistantMsgId: string) => {
    const eventType = event.type as string || (event.agent ? 'agent_started' : 'unknown');
    console.log('[useAgentStream] handleStreamEvent:', eventType, event);

    switch (eventType) {
      case 'agent_started':
        console.log('[useAgentStream] Agent started');
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
        console.log('[useAgentStream] Agent completed, event.output:', event.output, 'type:', typeof event.output);
        // Output can be a string or a structured object with {summary, root_cause, ...}
        let output = '';
        if (typeof event.output === 'string') {
          output = event.output;
          console.log('[useAgentStream] Output is string:', output);
        } else if (event.output && typeof event.output === 'object') {
          // Extract summary from structured output, or stringify the whole thing
          const structured = event.output as Record<string, unknown>;
          console.log('[useAgentStream] Output is object, structured:', structured);
          if (structured.summary && typeof structured.summary === 'string') {
            output = structured.summary;
            console.log('[useAgentStream] Extracted summary:', output);
          } else {
            output = JSON.stringify(event.output, null, 2);
            console.log('[useAgentStream] Stringified output:', output);
          }
        } else {
          console.log('[useAgentStream] Output is neither string nor object:', event.output);
        }

        const lastResponseId = event.last_response_id as string;
        if (lastResponseId) {
          lastResponseIdRef.current = lastResponseId;
        }

        console.log('[useAgentStream] Setting message content to:', output);
        setMessages(prev => prev.map(m =>
          m.id === assistantMsgId
            ? { ...m, content: output || m.content, isStreaming: false }
            : m
        ));

        if (event.success) {
          console.log('[useAgentStream] Calling onComplete');
          onComplete?.(output);
        } else if (event.error) {
          console.log('[useAgentStream] Setting error:', event.error);
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

  const sendMessage = useCallback(async (userMessage: string) => {
    console.log('[useAgentStream] sendMessage called:', userMessage);
    if (isStreaming) {
      console.log('[useAgentStream] Already streaming, returning');
      return;
    }

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
      console.log('[useAgentStream] Fetching /api/team/agent/stream...');
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

      console.log('[useAgentStream] Response status:', response.status, response.ok);

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || `HTTP ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error('No response body');

      const decoder = new TextDecoder();
      let buffer = '';
      let chunkCount = 0;

      console.log('[useAgentStream] Starting to read stream...');

      let currentEventType = '';  // Track the event type from "event:" line

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          console.log('[useAgentStream] Stream done, total chunks:', chunkCount);
          break;
        }

        chunkCount++;
        const chunk = decoder.decode(value, { stream: true });
        console.log('[useAgentStream] Chunk', chunkCount, ':', chunk.substring(0, 200));
        buffer += chunk;

        // Parse SSE events
        const lines = buffer.split('\n');
        buffer = lines.pop() || ''; // Keep incomplete line in buffer

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            // Capture the event type for the next data line
            currentEventType = line.slice(7).trim();
            console.log('[useAgentStream] Event type:', currentEventType);
          } else if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              // Inject the event type from the "event:" line into the data
              const eventWithType = { ...data, type: currentEventType || data.type };
              console.log('[useAgentStream] Parsed data with type:', eventWithType);
              handleStreamEvent(eventWithType, assistantMsgId);
              currentEventType = ''; // Reset after use
            } catch (e) {
              console.log('[useAgentStream] Parse error for line:', line, e);
            }
          }
        }
      }

    } catch (err) {
      console.log('[useAgentStream] Caught error:', err);
      if ((err as Error).name === 'AbortError') {
        console.log('[useAgentStream] User cancelled');
        setMessages(prev => prev.map(m =>
          m.id === assistantMsgId
            ? { ...m, content: m.content || 'Cancelled', isStreaming: false }
            : m
        ));
      } else {
        const errorMessage = (err as Error).message || 'Failed to run agent';
        console.log('[useAgentStream] Error message:', errorMessage);
        setError(errorMessage);
        setMessages(prev => prev.map(m =>
          m.id === assistantMsgId
            ? { ...m, content: `Error: ${errorMessage}`, isStreaming: false }
            : m
        ));
        onError?.(errorMessage);
      }
    } finally {
      console.log('[useAgentStream] Finally block - setting isStreaming=false');
      setIsStreaming(false);
      abortControllerRef.current = null;
    }
  }, [isStreaming, agentName, onError, handleStreamEvent]);

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
