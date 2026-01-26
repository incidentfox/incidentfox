import { NextRequest, NextResponse } from "next/server";
import { getOrchestratorBaseUrl, getUpstreamAuthHeaders, requireAdminSession } from "@/app/api/_utils/upstream";

export const runtime = "nodejs";

/**
 * GET /api/agents/prompts/defaults
 *
 * Returns default system prompts for all agents from the agent service code.
 * Used by the config UI to show placeholders when config has empty prompt.
 */
export async function GET(req: NextRequest) {
  try {
    await requireAdminSession(req);
  } catch (e: any) {
    const status = e?.status || (String(e?.message || "").includes("missing_auth") ? 401 : 403);
    return NextResponse.json({ error: "Admin session required" }, { status });
  }

  try {
    const upstream = `${getOrchestratorBaseUrl()}/agents/prompts/defaults`;
    const res = await fetch(upstream, {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
        ...getUpstreamAuthHeaders(req),
      },
    });

    if (!res.ok) {
      console.error(`Failed to fetch default prompts: ${res.status}`);
      return NextResponse.json(
        { error: "Failed to fetch default prompts", status: res.status },
        { status: res.status }
      );
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (e: any) {
    console.error("Error fetching default prompts:", e);
    return NextResponse.json(
      { error: "Failed to connect to agent service" },
      { status: 503 }
    );
  }
}
