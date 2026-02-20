import { NextResponse } from "next/server";

import { backendFetch } from "@/lib/backend";

export async function POST() {
  const response = await backendFetch("/collector/run", { method: "POST" });
  const payload = await response.text();
  return new NextResponse(payload, {
    status: response.status,
    headers: { "Content-Type": "application/json" },
  });
}
