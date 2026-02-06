import { NextRequest, NextResponse } from "next/server";
import { getOrchestratorBaseUrl } from "@/app/api/_utils/upstream";

export const runtime = "nodejs";

/**
 * A2A (Agent-to-Agent) Protocol Proxy
 *
 * Proxies A2A requests to the orchestrator service which handles:
 * - Task persistence (DB-backed, survives restarts)
 * - Scaling across replicas
 * - Background agent execution
 *
 * Based on Google's A2A specification for inter-agent communication.
 * https://github.com/google/A2A
 */

export async function POST(req: NextRequest) {
  const orchestratorUrl = getOrchestratorBaseUrl();

  try {
    const body = await req.text();

    const response = await fetch(`${orchestratorUrl}/api/v1/a2a`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: req.headers.get("authorization") || "",
      },
      body,
    });

    const responseText = await response.text();

    return new NextResponse(responseText, {
      status: response.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (error) {
    console.error("[A2A] Proxy error:", error);
    return NextResponse.json(
      {
        jsonrpc: "2.0",
        error: {
          code: -32603,
          message: "Internal error: failed to reach orchestrator",
        },
      },
      { status: 502 }
    );
  }
}

export async function GET() {
  const orchestratorUrl = getOrchestratorBaseUrl();

  try {
    const response = await fetch(`${orchestratorUrl}/api/v1/a2a`);
    const responseText = await response.text();

    return new NextResponse(responseText, {
      status: response.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (error) {
    console.error("[A2A] Proxy error:", error);
    return NextResponse.json(
      { error: "Failed to reach orchestrator" },
      { status: 502 }
    );
  }
}
