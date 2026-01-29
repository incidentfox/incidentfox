import { NextRequest, NextResponse } from "next/server";
import { getConfigServiceBaseUrl, getUpstreamAuthHeaders } from "@/app/api/_utils/upstream";

export const runtime = "nodejs";

/**
 * POST /api/visitor/end-session
 *
 * End the current visitor session (logout).
 * Proxies to config_service POST /api/v1/visitor/end-session
 *
 * Response:
 *   { status: "ended" | "not_found" }
 *
 * Always clears session cookies.
 */
export async function POST(req: NextRequest) {
  try {
    const baseUrl = getConfigServiceBaseUrl();
    const upstreamUrl = new URL("/api/v1/visitor/end-session", baseUrl);

    // Get auth headers
    let authHeaders = getUpstreamAuthHeaders(req);

    // Also check for visitor-specific token
    if (!authHeaders.Authorization) {
      const visitorToken = req.cookies.get("incidentfox_visitor_token")?.value;
      if (visitorToken) {
        authHeaders = { Authorization: `Bearer ${visitorToken}` };
      }
    }

    if (authHeaders.Authorization) {
      // Call upstream to end session
      await fetch(upstreamUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...authHeaders,
        },
        cache: "no-store",
      });
    }

    // Always clear cookies regardless of upstream response
    const response = NextResponse.json({ status: "ended" }, { status: 200 });
    response.cookies.delete("incidentfox_session_token");
    response.cookies.delete("incidentfox_visitor_token");

    return response;
  } catch (err: any) {
    console.error("Visitor end-session error:", err);
    // Still clear cookies even on error
    const response = NextResponse.json({ status: "ended" }, { status: 200 });
    response.cookies.delete("incidentfox_session_token");
    response.cookies.delete("incidentfox_visitor_token");
    return response;
  }
}
