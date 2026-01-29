import { NextRequest, NextResponse } from "next/server";
import { getConfigServiceBaseUrl } from "@/app/api/_utils/upstream";

export const runtime = "nodejs";

/**
 * POST /api/visitor/login
 *
 * Login as a visitor to the public playground.
 * Proxies to config_service POST /api/v1/visitor/login
 *
 * Request body:
 *   { email: string, source?: string }
 *
 * Response:
 *   { session_id: string, status: "active" | "queued", queue_position?: number, token?: string }
 *
 * If status is "active", sets the token as a session cookie.
 */
export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const { email, source } = body;

    if (!email || typeof email !== "string") {
      return NextResponse.json({ error: "Email is required" }, { status: 400 });
    }

    const baseUrl = getConfigServiceBaseUrl();
    const upstreamUrl = new URL("/api/v1/visitor/login", baseUrl);

    const res = await fetch(upstreamUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, source }),
      cache: "no-store",
    });

    const data = await res.json();

    if (!res.ok) {
      return NextResponse.json(data, { status: res.status });
    }

    // Create response
    const response = NextResponse.json(data, { status: 200 });

    // If the visitor got active access, set the session cookie
    if (data.status === "active" && data.token) {
      response.cookies.set("incidentfox_session_token", data.token, {
        httpOnly: true,
        secure: process.env.NODE_ENV === "production",
        sameSite: "lax",
        maxAge: 60 * 30, // 30 minutes (matches visitor token TTL)
        path: "/",
      });
    }

    // Also set cookie for queued users (they'll need it when promoted)
    if (data.status === "queued" && data.token) {
      response.cookies.set("incidentfox_visitor_token", data.token, {
        httpOnly: true,
        secure: process.env.NODE_ENV === "production",
        sameSite: "lax",
        maxAge: 60 * 60, // 1 hour (to cover queue wait time)
        path: "/",
      });
    }

    return response;
  } catch (err: any) {
    console.error("Visitor login error:", err);
    return NextResponse.json(
      { error: "Failed to login as visitor", details: err?.message || String(err) },
      { status: 500 }
    );
  }
}
