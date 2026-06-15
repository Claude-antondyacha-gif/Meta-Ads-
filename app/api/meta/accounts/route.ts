import { NextResponse } from "next/server";
import { fetchAdAccounts } from "@/lib/meta";

export async function GET() {
  try {
    const accounts = await fetchAdAccounts();
    return NextResponse.json({ accounts });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
