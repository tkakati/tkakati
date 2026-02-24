import { NextRequest, NextResponse } from "next/server";

import { backendFetch } from "@/lib/backend";

type Params = { params: { id: string } };

export async function PATCH(request: NextRequest, { params }: Params) {
  const body = await request.text();
  const response = await backendFetch(`/signals/${params.id}/review`, {
    method: "PATCH",
    body: body || undefined,
    headers: body ? { "Content-Type": "application/json" } : undefined,
  });
  const payload = await response.text();
  return new NextResponse(payload, {
    status: response.status,
    headers: { "Content-Type": "application/json" },
  });
}
