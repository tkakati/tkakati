import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";

import ReviewQueue from "@/components/review-queue";

export default async function ReviewPage() {
  const { userId } = await auth();
  if (!userId) {
    redirect("/sign-in");
  }
  return <ReviewQueue />;
}
