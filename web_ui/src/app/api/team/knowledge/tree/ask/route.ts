import { NextRequest, NextResponse } from 'next/server';

const RAPTOR_API_URL = process.env.RAPTOR_API_URL || 'http://localhost:8000';

// Extended timeout - Q&A can take longer due to LLM inference + potential tree loading
export const maxDuration = 300;

/**
 * POST /api/team/knowledge/tree/ask
 * Ask a question and get an answer from the knowledge base with citations
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
    const { question, tree = 'mega_ultra_v2', top_k = 5 } = body;

    if (!question) {
      return NextResponse.json({ error: 'Question is required' }, { status: 400 });
    }

    const res = await fetch(`${RAPTOR_API_URL}/api/v1/answer`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify({ question, tree, top_k }),
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
        { error: 'Request timed out. Tree may still be loading - please try again.' },
        { status: 504 }
      );
    }
    console.error('RAPTOR API error:', e);
    return NextResponse.json({ error: e?.message || 'Failed to answer question' }, { status: 500 });
  }
}

