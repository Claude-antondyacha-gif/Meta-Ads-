const GRAPH_BASE = "https://graph.facebook.com/v19.0";

function getToken(): string {
  const token = process.env.META_ACCESS_TOKEN;
  if (!token) throw new Error("META_ACCESS_TOKEN is not set");
  return token;
}

export interface AdAccount {
  id: string;
  name: string;
  account_status: number;
  currency: string;
  timezone_name: string;
}

export interface Campaign {
  id: string;
  name: string;
  status: string;
  objective: string;
}

export interface AccountInsights {
  spend: string;
  impressions: string;
  clicks: string;
  ctr: string;
  cpc: string;
  actions?: Array<{ action_type: string; value: string }>;
}

export async function fetchAdAccounts(): Promise<AdAccount[]> {
  const token = getToken();
  const url = `${GRAPH_BASE}/me/adaccounts?fields=id,name,account_status,currency,timezone_name&access_token=${token}`;
  const res = await fetch(url, { next: { revalidate: 300 } });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err?.error?.message ?? `HTTP ${res.status}`);
  }
  const json = await res.json();
  return json.data as AdAccount[];
}

export async function fetchCampaigns(accountId: string): Promise<Campaign[]> {
  const token = getToken();
  const url = `${GRAPH_BASE}/${accountId}/campaigns?fields=id,name,status,objective&date_preset=last_30d&access_token=${token}`;
  const res = await fetch(url, { next: { revalidate: 300 } });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err?.error?.message ?? `HTTP ${res.status}`);
  }
  const json = await res.json();
  return json.data as Campaign[];
}

export async function fetchAccountInsights(accountId: string): Promise<AccountInsights | null> {
  const token = getToken();
  const url = `${GRAPH_BASE}/${accountId}/insights?fields=spend,impressions,clicks,ctr,cpc,actions&date_preset=last_30d&level=account&access_token=${token}`;
  const res = await fetch(url, { next: { revalidate: 300 } });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err?.error?.message ?? `HTTP ${res.status}`);
  }
  const json = await res.json();
  if (!json.data || json.data.length === 0) return null;
  return json.data[0] as AccountInsights;
}
