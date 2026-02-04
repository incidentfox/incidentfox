import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

/**
 * GitHub App OAuth callback proxy.
 *
 * GitHub redirects here after a user installs the app.
 * We proxy the request to config-service which processes the installation
 * and redirects to the setup page.
 */
export async function GET(request: NextRequest) {
  const configServiceUrl = process.env.CONFIG_SERVICE_URL;
  if (!configServiceUrl) {
    console.error("CONFIG_SERVICE_URL not set");
    return NextResponse.json(
      { error: "Internal configuration error" },
      { status: 500 }
    );
  }

  // Forward the full URL with query params to config-service
  const url = new URL(request.url);
  const targetUrl = `${configServiceUrl}/github/callback${url.search}`;

  console.log(`Proxying GitHub callback to: ${targetUrl}`);

  try {
    const response = await fetch(targetUrl, {
      method: "GET",
      headers: {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      },
      redirect: "manual", // Don't follow redirects, return them to the client
    });

    // If config-service returns a redirect, pass it through
    if (response.status >= 300 && response.status < 400) {
      const location = response.headers.get("location");
      if (location) {
        return NextResponse.redirect(location, response.status);
      }
    }

    // For other responses, proxy the body and status
    const body = await response.text();
    return new NextResponse(body, {
      status: response.status,
      headers: {
        "Content-Type": response.headers.get("content-type") || "text/plain",
      },
    });
  } catch (error) {
    console.error("GitHub callback proxy error:", error);
    return NextResponse.json(
      { error: "Failed to process GitHub callback" },
      { status: 502 }
    );
  }
}
