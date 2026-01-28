import { NextRequest, NextResponse } from 'next/server';

const RAPTOR_API_URL = process.env.RAPTOR_API_URL || 'http://localhost:8000';

/**
 * GET /api/team/knowledge/tree/cache
 * Returns cache statistics from RAPTOR API
 *
 * Used by the UI to check if a tree is cached before attempting to load it.
 * If a tree is not cached, the UI can show an appropriate message about
 * first-time loading taking longer.
 */
export async function GET(request: NextRequest) {
  const token = request.cookies.get('incidentfox_session_token')?.value;

  if (!token) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  try {
    const res = await fetch(
      `${RAPTOR_API_URL}/api/v1/cache/stats`,
      {
        headers: { 'Accept': 'application/json' },
        cache: 'no-store',
      }
    );

    if (!res.ok) {
      const err = await res.text();
      return NextResponse.json({ error: err }, { status: res.status });
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (e: any) {
    console.error('RAPTOR API cache stats error:', e);
    return NextResponse.json({ error: e?.message || 'Failed to fetch cache stats' }, { status: 500 });
  }
}
