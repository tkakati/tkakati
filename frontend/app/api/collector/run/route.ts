import { NextRequest, NextResponse } from "next/server";

import { backendFetch } from "@/lib/backend";

export async function POST(request: NextRequest) {
  const body = await request.text();
  const response = await backendFetch("/collector/run", {
    method: "POST",
    body: body || undefined,
    headers: body ? { "Content-Type": "application/json" } : undefined,
  });
  const payload = await response.text();
  return new NextResponse(payload, {
    status: response.status,
    headers: { "Content-Type": "application/json" },
  });
}
