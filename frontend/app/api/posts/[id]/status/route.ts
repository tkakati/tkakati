import { NextRequest, NextResponse } from "next/server";

import { backendFetch } from "@/lib/backend";

export async function PATCH(
  request: NextRequest,
  { params }: { params: { id: string } },
) {
  const body = await request.text();
  const response = await backendFetch(`/posts/${params.id}/status`, {
    method: "PATCH",
    body,
  });

  const payload = await response.text();
  return new NextResponse(payload, {
    status: response.status,
    headers: { "Content-Type": "application/json" },
  });
}
