import { NextRequest, NextResponse } from 'next/server';

const CONFIG_SERVICE_URL = process.env.CONFIG_SERVICE_URL || 'http://localhost:8080';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ runId: string }> }
) {
  const { runId } = await params;
  const token = request.cookies.get('incidentfox_session_token')?.value;
  
  if (!token) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  try {
    const res = await fetch(
      `${CONFIG_SERVICE_URL}/api/v1/team/agent-runs/${runId}`,
      {
        headers: { 'Authorization': `Bearer ${token}` },
      }
    );

    const text = await res.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch {
      // Backend returned non-JSON response (e.g., "Internal Server Error")
      return NextResponse.json(
        { error: text || `Request failed with status ${res.status}` },
        { status: res.status >= 400 ? res.status : 500 }
      );
    }
    return NextResponse.json(data, { status: res.status });
  } catch (e: any) {
    return NextResponse.json({ error: e?.message || 'Failed to fetch' }, { status: 500 });
  }
}

