import { NextResponse } from "next/server";
import { fetchCampaigns, fetchAccountInsights } from "@/lib/meta";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const accountId = searchParams.get("account_id");

  if (!accountId) {
    return NextResponse.json({ error: "account_id is required" }, { status: 400 });
  }

  try {
    const [campaigns, insights] = await Promise.all([
      fetchCampaigns(accountId),
      fetchAccountInsights(accountId),
    ]);
    return NextResponse.json({ campaigns, insights });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
