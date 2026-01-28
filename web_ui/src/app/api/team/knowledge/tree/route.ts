import { NextRequest, NextResponse } from 'next/server';

const RAPTOR_API_URL = process.env.RAPTOR_API_URL || 'http://localhost:8000';

// Extended timeout for first-time tree loads that may require S3 download
export const maxDuration = 300; // 5 minutes

/**
 * GET /api/team/knowledge/tree
 * Returns tree structure for visualization (top layers)
 *
 * Note: This endpoint may trigger lazy loading of trees from S3 on first access.
 */
export async function GET(request: NextRequest) {
  const token = request.cookies.get('incidentfox_session_token')?.value;

  if (!token) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  const { searchParams } = new URL(request.url);
  const tree = searchParams.get('tree') || 'mega_ultra_v2';
  const maxLayers = searchParams.get('maxLayers') || '3';
  const maxNodesPerLayer = searchParams.get('maxNodesPerLayer') || '200';

  // Extended timeout for the upstream request
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 300000);

  try {
    const res = await fetch(
      `${RAPTOR_API_URL}/api/v1/tree/structure?tree=${encodeURIComponent(tree)}&max_layers=${maxLayers}&max_nodes_per_layer=${maxNodesPerLayer}`,
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
      return NextResponse.json(
        { error: 'Request timed out. Tree may still be downloading - please try again.' },
        { status: 504 }
      );
    }
    console.error('RAPTOR API error:', e);
    return NextResponse.json({ error: e?.message || 'Failed to fetch tree structure' }, { status: 500 });
  }
}

