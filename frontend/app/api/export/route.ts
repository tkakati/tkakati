import { NextRequest, NextResponse } from "next/server";

import { backendFetch } from "@/lib/backend";

export async function GET(request: NextRequest) {
  const response = await backendFetch(`/export.csv?${request.nextUrl.searchParams.toString()}`);
  const payload = await response.text();
  return new NextResponse(payload, {
    status: response.status,
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": "attachment; filename=posts.csv",
    },
  });
}
