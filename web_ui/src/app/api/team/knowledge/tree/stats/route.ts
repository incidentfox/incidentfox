import { NextRequest, NextResponse } from 'next/server';

const RAPTOR_API_URL = process.env.RAPTOR_API_URL || 'http://localhost:8000';

// Extended timeout for first-time tree loads that may require S3 download
// This can take 1-2 minutes for large trees (~1.5GB)
export const maxDuration = 300; // 5 minutes

/**
 * GET /api/team/knowledge/tree/stats
 * Returns tree statistics (node counts, layers, etc.)
 *
 * Note: This endpoint may trigger lazy loading of trees from S3 on first access.
 * The extended timeout (maxDuration) accommodates large tree downloads.
 */
export async function GET(request: NextRequest) {
  const token = request.cookies.get('incidentfox_session_token')?.value;

  if (!token) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  const { searchParams } = new URL(request.url);
  const tree = searchParams.get('tree') || 'mega_ultra_v2';

  // Extended timeout for the upstream request (5 minutes for S3 downloads)
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 300000);

  try {
    const res = await fetch(
      `${RAPTOR_API_URL}/api/v1/tree/stats?tree=${encodeURIComponent(tree)}`,
      {
        headers: { 'Accept': 'application/json' },
        cache: 'no-store',
        signal: controller.signal,
      }
    );
    clearTimeout(timeoutId);

    if (!res.ok) {
      const err = await res.text();
      return NextResponse.json({ error: err }, { status: res.status });
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (e: any) {
    clearTimeout(timeoutId);
    if (e.name === 'AbortError') {
      console.error('RAPTOR API timeout - tree may be downloading from S3');
      return NextResponse.json(
        { error: 'Request timed out. Tree may still be downloading - please try again in a few minutes.' },
        { status: 504 }
      );
    }
    console.error('RAPTOR API error:', e);
    return NextResponse.json({ error: e?.message || 'Failed to fetch tree stats' }, { status: 500 });
  }
}

