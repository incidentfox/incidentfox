import { NextRequest, NextResponse } from 'next/server';

const CONFIG_SERVICE_URL = process.env.CONFIG_SERVICE_URL || 'http://localhost:8080';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ runId: string }> }
) {
  const token = request.cookies.get('incidentfox_session_token')?.value;

  if (!token) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  try {
    const { runId } = await params;
    const res = await fetch(
      `${CONFIG_SERVICE_URL}/api/v1/team/agent-runs/${runId}/trace`,
      {
        headers: { 'Authorization': `Bearer ${token}` },
      }
    );

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (e: any) {
    return NextResponse.json({ error: e?.message || 'Failed to fetch trace' }, { status: 500 });
  }
}
