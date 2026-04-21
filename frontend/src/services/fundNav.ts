import { LSJZ_IDB_MAX_AGE_MS, lsjzCacheKey, readLsjzFromIdb, writeLsjzToIdb } from "../utils/fundNavIdb";
import { api, ApiEnvelope } from "./api";

export interface LsjzPoint {
  date: string;
  dwjz: number;
  jzzzl?: string | number | null;
}

export interface LsjzJsonPayload {
  ok: boolean;
  fund_code: string;
  points_desc: LsjzPoint[];
  points_asc: LsjzPoint[];
  total_count?: number | null;
  error?: string | null;
  source?: string;
  pages_fetched?: number;
  range_truncated?: boolean;
}

/** 按日期区间拉取历史净值（后端自动翻页；IndexedDB 热读秒开） */
export async function fetchFundLsjzJson(fundCode: string, range: { startDate: string; endDate: string }) {
  const key = lsjzCacheKey(fundCode.trim(), range.startDate, range.endDate);
  const local = await readLsjzFromIdb(key);
  if (
    local &&
    typeof local.savedAt === "number" &&
    Date.now() - local.savedAt < LSJZ_IDB_MAX_AGE_MS &&
    local.payload &&
    typeof local.payload === "object" &&
    (local.payload as LsjzJsonPayload).ok === true
  ) {
    return local.payload as LsjzJsonPayload;
  }

  const response = await api.get<ApiEnvelope<LsjzJsonPayload>>("/funds/lsjz-json", {
    params: {
      fund_code: fundCode.trim(),
      start_date: range.startDate,
      end_date: range.endDate
    },
    skipGlobalLoading: true
  });
  const data = response.data.data;
  if (data?.ok) {
    void writeLsjzToIdb(key, data);
  }
  return data;
}
