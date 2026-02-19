import { NextRequest, NextResponse } from "next/server";
import { getConfigServiceBaseUrl, getUpstreamAuthHeaders } from "../../_utils/upstream";

export const runtime = "nodejs";

export async function GET(request: NextRequest) {
  const authHeaders = getUpstreamAuthHeaders(request);
  if (!Object.keys(authHeaders).length) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const baseUrl = getConfigServiceBaseUrl();
    const orgId = process.env.ORG_ID || "org1";

    const upstreamUrl = new URL(`/api/v1/admin/orgs/${orgId}/nodes`, baseUrl);
    const res = await fetch(upstreamUrl, {
      headers: authHeaders,
      cache: "no-store",
    });

    const contentType = res.headers.get("content-type") || "application/json";
    const body = await res.text();

    return new NextResponse(body, {
      status: res.status,
      headers: {
        "content-type": contentType,
      },
    });
  } catch (err: any) {
    return NextResponse.json(
      {
        error: "Failed to fetch topology nodes",
        details: err?.message || String(err),
      },
      { status: 502 },
    );
  }
}


