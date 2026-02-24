import { NextRequest, NextResponse } from "next/server";

import { backendFetch } from "@/lib/backend";

export async function GET(request: NextRequest) {
  const response = await backendFetch(`/signals/review-queue?${request.nextUrl.searchParams.toString()}`);
  const payload = await response.text();
  return new NextResponse(payload, {
    status: response.status,
    headers: { "Content-Type": "application/json" },
  });
}
