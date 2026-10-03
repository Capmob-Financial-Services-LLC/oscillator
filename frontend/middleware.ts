import { NextRequest, NextResponse } from "next/server";

// On AWS the app runs on a Lambda function URL behind CloudFront, which asks
// for the dashboard login and then adds X-Origin-Verify. The function URL is
// itself reachable from the internet, so without this check anyone with that
// URL could skip the login. Only active when ORIGIN_VERIFY_SECRET is set
// (the Lambda), so Vercel and local dev are unaffected.
const SECRET = process.env.ORIGIN_VERIFY_SECRET;

export function middleware(req: NextRequest) {
  if (SECRET && req.headers.get("x-origin-verify") !== SECRET) {
    return new NextResponse("Forbidden", { status: 403 });
  }
  return NextResponse.next();
}

export const config = {
  matcher: "/((?!_next/static|favicon.ico).*)",
};
