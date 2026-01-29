import { NextRequest, NextResponse } from "next/server";
import { getConfigServiceBaseUrl, getUpstreamAuthHeaders } from "@/app/api/_utils/upstream";

export const runtime = "nodejs";

/**
 * POST /api/visitor/heartbeat
 *
 * Send heartbeat to keep visitor session alive and get current status.
 * Proxies to config_service POST /api/v1/visitor/heartbeat
 *
 * Response:
 *   {
 *     status: "active" | "warned" | "queued" | "expired",
 *     queue_position?: number,
 *     warning_seconds_remaining?: number,
 *     estimated_wait_seconds?: number,
 *     reason?: string
 *   }
 *
 * If status becomes "active" (promoted from queue), updates the session cookie.
 */
export async function POST(req: NextRequest) {
  try {
    const baseUrl = getConfigServiceBaseUrl();
    const upstreamUrl = new URL("/api/v1/visitor/heartbeat", baseUrl);

    // Get auth headers (will use session cookie)
    let authHeaders = getUpstreamAuthHeaders(req);

    // Also check for visitor-specific token (for queued users)
    if (!authHeaders.Authorization) {
      const visitorToken = req.cookies.get("incidentfox_visitor_token")?.value;
      if (visitorToken) {
        authHeaders = { Authorization: `Bearer ${visitorToken}` };
      }
    }

    if (!authHeaders.Authorization) {
      return NextResponse.json(
        { status: "expired", reason: "no_token" },
        { status: 200 }
      );
    }

    const res = await fetch(upstreamUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...authHeaders,
      },
      cache: "no-store",
    });

    const data = await res.json();

    if (!res.ok) {
      return NextResponse.json(data, { status: res.status });
    }

    const response = NextResponse.json(data, { status: 200 });

    // If user was promoted from queue to active, update the main session cookie
    if (data.status === "active") {
      // The visitor token cookie can now be used as the session token
      const visitorToken = req.cookies.get("incidentfox_visitor_token")?.value;
      const sessionToken = req.cookies.get("incidentfox_session_token")?.value;

      // If they have a visitor token but no session token, promote it
      if (visitorToken && !sessionToken) {
        response.cookies.set("incidentfox_session_token", visitorToken, {
          httpOnly: true,
          secure: process.env.NODE_ENV === "production",
          sameSite: "lax",
          maxAge: 60 * 30, // 30 minutes
          path: "/",
        });
      }
    }

    // If session expired, clear cookies
    if (data.status === "expired") {
      response.cookies.delete("incidentfox_session_token");
      response.cookies.delete("incidentfox_visitor_token");
    }

    return response;
  } catch (err: any) {
    console.error("Visitor heartbeat error:", err);
    return NextResponse.json(
      { error: "Failed to send heartbeat", details: err?.message || String(err) },
      { status: 500 }
    );
  }
}
