import { NextRequest } from 'next/server';

export const runtime = 'nodejs';

const AGENT_SERVICE_URL = process.env.AGENT_SERVICE_URL || process.env.ORCHESTRATOR_URL || 'http://localhost:8081';
const CONFIG_SERVICE_URL = process.env.CONFIG_SERVICE_URL || 'http://localhost:8080';

/**
 * Fetch the team's entrance_agent from config service.
 * Falls back to 'planner' if config fetch fails.
 */
async function getEntranceAgent(token: string): Promise<string> {
  try {
    const res = await fetch(`${CONFIG_SERVICE_URL}/api/v1/config/me`, {
      headers: {
        'Authorization': `Bearer ${token}`,
      },
      cache: 'no-store',
    });

    if (res.ok) {
      const data = await res.json();
      // v2 API returns {effective_config: {...}}, extract if present
      const config = data.effective_config || data;
      return config.entrance_agent || 'planner';
    }
  } catch (e) {
    // Silently fall back to default
  }
  return 'planner';
}

export async function POST(request: NextRequest) {
  const token = request.cookies.get('incidentfox_session_token')?.value;

  if (!token) {
    return new Response(JSON.stringify({ error: 'Not authenticated' }), {
      status: 401,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  try {
    const body = await request.json();

    // Get entrance_agent from team config if agent_name not explicitly provided
    const defaultAgent = body.agent_name ? body.agent_name : await getEntranceAgent(token);
    const { message, previous_response_id, max_turns = 20, timeout = 300 } = body;
    const agent_name = defaultAgent;

    if (!message) {
      return new Response(JSON.stringify({ error: 'Missing message' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // Forward to agent service streaming endpoint
    const upstreamUrl = `${AGENT_SERVICE_URL}/agents/${agent_name}/run/stream`;

    const upstreamRes = await fetch(upstreamUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-IncidentFox-Team-Token': token,
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify({
        message,
        previous_response_id,
        max_turns,
        timeout,
        context: {
          metadata: {
            trigger: 'web_ui',
            source: 'onboarding',
          },
        },
      }),
    });

    if (!upstreamRes.ok) {
      const errorText = await upstreamRes.text();
      return new Response(JSON.stringify({ error: errorText || `Upstream error: ${upstreamRes.status}` }), {
        status: upstreamRes.status,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // Stream the SSE response through
    const { readable, writable } = new TransformStream();
    const writer = writable.getWriter();
    const encoder = new TextEncoder();

    // Pipe the upstream response to client
    (async () => {
      const reader = upstreamRes.body?.getReader();
      if (!reader) {
        await writer.close();
        return;
      }

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          await writer.write(value);
        }
      } catch (e) {
        // Connection closed
      } finally {
        await writer.close();
      }
    })();

    return new Response(readable, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no',
      },
    });
  } catch (e: unknown) {
    const errorMessage = e instanceof Error ? e.message : 'Failed to stream agent';
    return new Response(JSON.stringify({ error: errorMessage }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}
