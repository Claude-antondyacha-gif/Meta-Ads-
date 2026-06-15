"use client";

import { useEffect, useState, useCallback } from "react";

interface AdAccount {
  id: string;
  name: string;
  account_status: number;
  currency: string;
  timezone_name: string;
}

interface Campaign {
  id: string;
  name: string;
  status: string;
  objective: string;
}

interface AccountInsights {
  spend: string;
  impressions: string;
  clicks: string;
  ctr: string;
  cpc: string;
  actions?: Array<{ action_type: string; value: string }>;
}

function StatCard({
  label,
  value,
  prefix,
  suffix,
  color,
}: {
  label: string;
  value: string | number;
  prefix?: string;
  suffix?: string;
  color: string;
}) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">{label}</p>
      <p className={`text-2xl font-bold ${color}`}>
        {prefix}
        {value}
        {suffix}
      </p>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    ACTIVE: "bg-green-100 text-green-700",
    PAUSED: "bg-yellow-100 text-yellow-700",
    DELETED: "bg-red-100 text-red-700",
    ARCHIVED: "bg-slate-100 text-slate-600",
  };
  const cls = map[status] ?? "bg-slate-100 text-slate-600";
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${cls}`}>
      {status}
    </span>
  );
}

function formatObjective(obj: string): string {
  return obj.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
}

function getRoas(actions?: Array<{ action_type: string; value: string }>, spend?: string): string {
  if (!actions || !spend || parseFloat(spend) === 0) return "N/A";
  const purchase = actions.find((a) => a.action_type === "offsite_conversion.fb_pixel_purchase");
  if (!purchase) return "N/A";
  const roas = parseFloat(purchase.value) / parseFloat(spend);
  return roas.toFixed(2) + "x";
}

export default function Home() {
  const [accounts, setAccounts] = useState<AdAccount[]>([]);
  const [selectedAccount, setSelectedAccount] = useState<string>("");
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [insights, setInsights] = useState<AccountInsights | null>(null);
  const [loadingAccounts, setLoadingAccounts] = useState(true);
  const [loadingData, setLoadingData] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoadingAccounts(true);
    fetch("/api/meta/accounts")
      .then((r) => r.json())
      .then((data) => {
        if (data.error) throw new Error(data.error);
        setAccounts(data.accounts ?? []);
        if (data.accounts?.length > 0) {
          setSelectedAccount(data.accounts[0].id);
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoadingAccounts(false));
  }, []);

  const loadAccountData = useCallback((accountId: string) => {
    if (!accountId) return;
    setLoadingData(true);
    setError(null);
    fetch(`/api/meta/campaigns?account_id=${encodeURIComponent(accountId)}`)
      .then((r) => r.json())
      .then((data) => {
        if (data.error) throw new Error(data.error);
        setCampaigns(data.campaigns ?? []);
        setInsights(data.insights ?? null);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoadingData(false));
  }, []);

  useEffect(() => {
    if (selectedAccount) loadAccountData(selectedAccount);
  }, [selectedAccount, loadAccountData]);

  const currentAccount = accounts.find((a) => a.id === selectedAccount);

  return (
    <div className="space-y-8">
      {/* Page header + account selector */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-slate-900">Campaign Overview</h2>
          <p className="text-sm text-slate-500 mt-1">Last 30 days · Meta Marketing API v19.0</p>
        </div>
        {loadingAccounts ? (
          <div className="h-10 w-56 bg-slate-200 animate-pulse rounded-lg" />
        ) : accounts.length > 1 ? (
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-slate-500 uppercase tracking-wide">Ad Account</label>
            <select
              className="border border-slate-300 rounded-lg px-3 py-2 text-sm bg-white shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={selectedAccount}
              onChange={(e) => setSelectedAccount(e.target.value)}
            >
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} ({a.currency})
                </option>
              ))}
            </select>
          </div>
        ) : currentAccount ? (
          <div className="text-sm text-slate-600 bg-white border border-slate-200 rounded-lg px-4 py-2">
            <span className="font-medium">{currentAccount.name}</span>
            <span className="text-slate-400 ml-2">{currentAccount.currency} · {currentAccount.timezone_name}</span>
          </div>
        ) : null}
      </div>

      {/* Error state */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 flex items-start gap-3">
          <svg className="w-5 h-5 text-red-500 mt-0.5 shrink-0" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
          </svg>
          <div>
            <p className="text-sm font-semibold text-red-700">API Error</p>
            <p className="text-sm text-red-600 mt-0.5">{error}</p>
          </div>
        </div>
      )}

      {/* Summary cards */}
      {loadingData ? (
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="bg-white rounded-xl border border-slate-200 p-5 h-20 animate-pulse">
              <div className="h-3 bg-slate-200 rounded w-2/3 mb-3" />
              <div className="h-6 bg-slate-200 rounded w-1/2" />
            </div>
          ))}
        </div>
      ) : insights ? (
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
          <StatCard label="Total Spend" value={parseFloat(insights.spend).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} prefix={currentAccount?.currency === "USD" ? "$" : ""} suffix={currentAccount?.currency !== "USD" ? ` ${currentAccount?.currency}` : ""} color="text-blue-600" />
          <StatCard label="Impressions" value={parseInt(insights.impressions).toLocaleString()} color="text-violet-600" />
          <StatCard label="Clicks" value={parseInt(insights.clicks).toLocaleString()} color="text-emerald-600" />
          <StatCard label="CTR" value={parseFloat(insights.ctr).toFixed(2)} suffix="%" color="text-amber-600" />
          <StatCard label="CPC" value={parseFloat(insights.cpc).toFixed(2)} prefix="$" color="text-rose-600" />
        </div>
      ) : !error && !loadingAccounts ? (
        <div className="bg-white rounded-xl border border-slate-200 p-8 text-center text-slate-500">
          <p className="text-sm">No insights data available for this account in the last 30 days.</p>
        </div>
      ) : null}

      {/* ROAS card if available */}
      {insights && getRoas(insights.actions, insights.spend) !== "N/A" && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <StatCard label="ROAS (Purchase)" value={getRoas(insights.actions, insights.spend)} color="text-teal-600" />
        </div>
      )}

      {/* Campaigns table */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
          <h3 className="font-semibold text-slate-800">Campaigns</h3>
          {campaigns.length > 0 && (
            <span className="text-xs text-slate-500 bg-slate-100 rounded-full px-2.5 py-1 font-medium">
              {campaigns.length} total
            </span>
          )}
        </div>

        {loadingData ? (
          <div className="p-6 space-y-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="h-10 bg-slate-100 animate-pulse rounded-lg" />
            ))}
          </div>
        ) : campaigns.length === 0 && !error ? (
          <div className="px-6 py-12 text-center text-slate-500">
            <svg className="w-10 h-10 mx-auto text-slate-300 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
            <p className="text-sm">No campaigns found for this account.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-50 text-slate-500 text-xs uppercase tracking-wider">
                  <th className="text-left px-6 py-3 font-semibold">Campaign Name</th>
                  <th className="text-left px-6 py-3 font-semibold">Status</th>
                  <th className="text-left px-6 py-3 font-semibold">Objective</th>
                  <th className="text-left px-6 py-3 font-semibold">ID</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {campaigns.map((campaign) => (
                  <tr key={campaign.id} className="hover:bg-slate-50 transition-colors">
                    <td className="px-6 py-4 font-medium text-slate-800 max-w-xs truncate">
                      {campaign.name}
                    </td>
                    <td className="px-6 py-4">
                      <StatusBadge status={campaign.status} />
                    </td>
                    <td className="px-6 py-4 text-slate-600">
                      {formatObjective(campaign.objective)}
                    </td>
                    <td className="px-6 py-4 text-slate-400 font-mono text-xs">
                      {campaign.id}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Footer note */}
      <p className="text-xs text-center text-slate-400 pb-4">
        Data sourced from Meta Marketing API v19.0 · Refreshes every 5 minutes
      </p>
    </div>
  );
}
