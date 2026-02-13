import { NextRequest, NextResponse } from 'next/server';

export function middleware(request: NextRequest) {
  if (!request.nextUrl.pathname.startsWith('/dashboard')) {
    return NextResponse.next();
  }

  if (request.nextUrl.pathname === '/dashboard/login') {
    return NextResponse.next();
  }

  const authCookie = request.cookies.get('dashboard_auth');
  if (authCookie?.value === 'authenticated') {
    return NextResponse.next();
  }

  const loginUrl = new URL('/dashboard/login', request.url);
  loginUrl.searchParams.set('redirect', request.nextUrl.pathname);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ['/dashboard/:path*'],
};
