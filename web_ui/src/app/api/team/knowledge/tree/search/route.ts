import { NextRequest, NextResponse } from 'next/server';

const RAPTOR_API_URL = process.env.RAPTOR_API_URL || 'http://localhost:8000';

// Extended timeout for first-time tree loads
export const maxDuration = 300;

/**
 * POST /api/team/knowledge/tree/search
 * Search for nodes in the tree (for highlighting in visualization)
 */
export async function POST(request: NextRequest) {
  const token = request.cookies.get('incidentfox_session_token')?.value;

  if (!token) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  // Extended timeout for the upstream request
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 300000);

  try {
    const body = await request.json();
    const { query, tree = 'mega_ultra_v2', limit = 50 } = body;

    if (!query) {
      return NextResponse.json({ error: 'Query is required' }, { status: 400 });
    }

    const res = await fetch(`${RAPTOR_API_URL}/api/v1/tree/search-nodes`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify({ query, tree, limit }),
      signal: controller.signal,
    });
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
      return NextResponse.json(
        { error: 'Search timed out. Tree may still be loading - please try again.' },
        { status: 504 }
      );
    }
    console.error('RAPTOR API error:', e);
    return NextResponse.json({ error: e?.message || 'Search failed' }, { status: 500 });
  }
}

