import { NextRequest, NextResponse } from 'next/server';
import { getConfigServiceBaseUrl, getUpstreamAuthHeaders } from '@/app/api/_utils/upstream';

/**
 * GET /api/team/preferences
 *
 * Get the preferences for the current team (stored in team config under `preferences`).
 */
export async function GET(req: NextRequest) {
  try {
    const baseUrl = getConfigServiceBaseUrl();
    const upstreamUrl = new URL('/api/v1/config/me', baseUrl);
    const authHeaders = getUpstreamAuthHeaders(req);

    const res = await fetch(upstreamUrl, {
      method: 'GET',
      headers: authHeaders,
      cache: 'no-store',
    });

    if (!res.ok) {
      return NextResponse.json({ error: 'Failed to fetch config' }, { status: res.status });
    }

    const config = await res.json();
    const preferences = config?.effective_config?.preferences || {};

    return NextResponse.json(preferences);
  } catch (err: unknown) {
    const errorMessage = err instanceof Error ? err.message : String(err);
    return NextResponse.json(
      { error: 'Failed to get preferences', details: errorMessage },
      { status: 502 },
    );
  }
}

/**
 * PATCH /api/team/preferences
 *
 * Update preferences (merged into team config under `preferences`).
 *
 * Example body:
 * {
 *   "onboarding": {
 *     "welcomeModalSeen": true,
 *     "firstAgentRunCompleted": true
 *   }
 * }
 */
export async function PATCH(req: NextRequest) {
  try {
    const baseUrl = getConfigServiceBaseUrl();
    const upstreamUrl = new URL('/api/v1/config/me', baseUrl);
    const authHeaders = getUpstreamAuthHeaders(req);

    const preferences = await req.json();

    // Wrap in preferences key for the config update
    const payload = {
      config: {
        preferences,
      },
    };

    const res = await fetch(upstreamUrl, {
      method: 'PATCH',
      headers: {
        ...authHeaders,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const errorText = await res.text();
      return NextResponse.json({ error: errorText || 'Failed to update preferences' }, { status: res.status });
    }

    const result = await res.json();
    return NextResponse.json(result?.config?.preferences || preferences);
  } catch (err: unknown) {
    const errorMessage = err instanceof Error ? err.message : String(err);
    return NextResponse.json(
      { error: 'Failed to update preferences', details: errorMessage },
      { status: 502 },
    );
  }
}
