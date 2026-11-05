import { NextResponse, type NextRequest } from "next/server";

const SESSION_COOKIE = "aigx_session";

/**
 * Route guard (UX only): unauthenticated visitors are sent to /login before any protected page renders.
 * The cookie is opaque here; the API validates the session on every request, which is the real control.
 */
export function proxy(request: NextRequest) {
  if (!request.cookies.has(SESSION_COOKIE)) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.search = `?next=${encodeURIComponent(request.nextUrl.pathname)}`;
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/dashboard/:path*", "/projects/:path*", "/settings/:path*"],
};
