import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const CONFIG_SERVICE_URL = process.env.CONFIG_SERVICE_URL || 'http://localhost:8080';

export async function GET(request: NextRequest) {
  const cookieStore = await cookies();
  const token = cookieStore.get('incidentfox_session_token')?.value;

  if (!token) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  try {
    // Get skills catalog from config service
    const res = await fetch(`${CONFIG_SERVICE_URL}/api/v1/team/skills/catalog`, {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });

    if (!res.ok) {
      const text = await res.text();
      console.error('Config service error:', res.status, text);
      return NextResponse.json({ error: text }, { status: res.status });
    }

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (error) {
    console.error('Failed to fetch skills catalog:', error);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}
