import { NextRequest, NextResponse } from 'next/server';

export async function POST(request: NextRequest) {
  const body = await request.json();
  const password = body.password;

  if (password === process.env.DASHBOARD_PASSWORD) {
    const response = NextResponse.json({ success: true });
    response.cookies.set('dashboard_auth', 'authenticated', {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      maxAge: 60 * 60 * 24 * 7,
      path: '/',
    });
    return response;
  }

  return NextResponse.json(
    { success: false, error: 'Invalid password' },
    { status: 401 }
  );
}
