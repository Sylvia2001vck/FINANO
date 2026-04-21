import { api, ApiEnvelope } from "./api";
import { useUserStore } from "../store/userStore";

export interface MAFBRunPayload {
  fund_code: string;
  /** 是否将账户已保存的 FBTI 纳入画像与后续推理 */
  include_fbti?: boolean;
}

export interface MAFBRunData {
  final_report: Record<string, unknown>;
  state_snapshot: Record<string, unknown>;
}

export interface AgentProfilePayload {
  user_birth: string;
  user_mbti: string;
  risk_preference?: number | null;
}

export async function runMafb(payload: MAFBRunPayload) {
  const response = await api.post<ApiEnvelope<MAFBRunData>>("/agent/run", payload);
  return response.data.data;
}

/** SSE：执行过程中回调当前节点中文名；返回与 `runMafb` 相同结构（不走 axios 全局 loading） */
export async function runMafbStream(
  payload: MAFBRunPayload,
  handlers: { onStage?: (node: string, label: string) => void }
): Promise<MAFBRunData> {
  const baseURL = import.meta.env.VITE_API_BASE_URL || "/api/v1";
  const token = useUserStore.getState().token;
  const res = await fetch(`${baseURL}/agent/run/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    },
    body: JSON.stringify(payload)
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const j = (await res.json()) as { message?: string };
      if (j?.message) detail = j.message;
    } catch {
      try {
        const t = await res.text();
        if (t) detail = t.slice(0, 200);
      } catch {
        /* ignore */
      }
    }
    throw new Error(detail);
  }
  const reader = res.body?.getReader();
  if (!reader) throw new Error("无法读取响应流");
  const decoder = new TextDecoder();
  let buffer = "";
  let result: MAFBRunData | null = null;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() ?? "";
    for (const block of chunks) {
      for (const line of block.split("\n")) {
        if (!line.startsWith("data: ")) continue;
        const raw = line.slice(6).trim();
        if (!raw) continue;
        const msg = JSON.parse(raw) as {
          event?: string;
          node?: string;
          label?: string;
          data?: MAFBRunData;
          message?: string;
        };
        if (msg.event === "stage" && msg.node && msg.label) {
          handlers.onStage?.(msg.node, msg.label);
        }
        if (msg.event === "result" && msg.data) {
          result = msg.data;
        }
        if (msg.event === "error") {
          throw new Error(msg.message || "MAFB 流式执行失败");
        }
      }
    }
  }
  if (!result) throw new Error("未收到完整 MAFB 结果");
  return result;
}

export async function saveAgentProfile(payload: AgentProfilePayload) {
  const response = await api.post<ApiEnvelope<Record<string, unknown>>>("/agent/profile", payload);
  return response.data.data;
}

export async function getAgentProfile() {
  const response = await api.get<ApiEnvelope<Record<string, unknown>>>("/agent/profile");
  return response.data.data;
}

export interface AgentFundsListResponse {
  items: Record<string, unknown>[];
  total: number;
  catalog_mode: string;
  limit: number;
  offset: number;
  view?: string;
  sample_seed?: number | null;
  filter_total?: number | null;
}

export interface ListAgentFundsParams {
  limit?: number;
  offset?: number;
  q?: string;
  /** catalog=顺序分页+搜索 | random=规则筛选后随机抽样 | my_pool=我的自选 */
  view?: "catalog" | "random" | "my_pool";
  seed?: number;
  track?: string;
  fundType?: string;
  etfOnly?: boolean;
  riskMin?: number;
  riskMax?: number;
}

export async function listAgentFunds(params?: ListAgentFundsParams) {
  const search = new URLSearchParams();
  if (params?.limit != null) search.set("limit", String(params.limit));
  if (params?.offset != null) search.set("offset", String(params.offset));
  if (params?.q) search.set("q", params.q);
  if (params?.view) search.set("view", params.view);
  if (params?.seed != null) search.set("seed", String(params.seed));
  if (params?.track) search.set("track", params.track);
  if (params?.fundType) search.set("fund_type", params.fundType);
  if (params?.etfOnly) search.set("etf_only", "true");
  if (params?.riskMin != null) search.set("risk_min", String(params.riskMin));
  if (params?.riskMax != null) search.set("risk_max", String(params.riskMax));
  const qs = search.toString();
  const path = qs ? `/agent/funds?${qs}` : "/agent/funds";
  const response = await api.get<ApiEnvelope<AgentFundsListResponse>>(path, {
    skipGlobalLoading: true,
    timeout: 180_000
  });
  return response.data.data;
}

export async function addMyAgentFunds(codes: string[]) {
  const response = await api.post<ApiEnvelope<{ added: number; items: Record<string, unknown>[]; total: number }>>(
    "/agent/funds/my-pool",
    { codes },
    { skipGlobalLoading: true, timeout: 60_000 }
  );
  return response.data.data;
}

export async function removeMyAgentFund(fundCode: string) {
  const response = await api.delete<ApiEnvelope<{ items: Record<string, unknown>[]; total: number }>>(
    `/agent/funds/my-pool/${fundCode}`,
    { skipGlobalLoading: true, timeout: 30_000 }
  );
  return response.data.data;
}

export interface FundCatalogStatus {
  catalog_mode: string;
  cached: boolean;
  count: number;
  busy: boolean;
  error: string | null;
}

/** 查询全市场基金索引是否已在内存就绪（可轮询） */
export async function getFundCatalogStatus() {
  const response = await api.get<ApiEnvelope<FundCatalogStatus>>("/agent/funds/catalog-status", {
    skipGlobalLoading: true,
    timeout: 20_000
  });
  return response.data.data;
}

/** 登录后调用：后台开始拉取天天基金全量列表（与 MAFB 首次打开共享单飞加载） */
export async function postWarmFundCatalog() {
  const response = await api.post<ApiEnvelope<{ status: string; catalog_mode?: string }>>(
    "/agent/funds/warm-catalog",
    {},
    { skipGlobalLoading: true, timeout: 20_000 }
  );
  return response.data.data;
}

export interface OcrFundCodeData {
  codes: string[];
  primary_code: string | null;
  matched_name: string | null;
  hint: string;
  ocr_lines: string[];
}

export async function ocrFundCode(file: File): Promise<OcrFundCodeData> {
  const formData = new FormData();
  formData.append("file", file);
  const response = await api.post<ApiEnvelope<OcrFundCodeData>>("/ocr/fund-code", formData, {
    headers: { "Content-Type": "multipart/form-data" }
  });
  return response.data.data;
}

export interface SimilarFundRow {
  code: string;
  name: string;
  track: string;
  similarity: number;
  rationale: string;
}

export async function fetchSimilarFunds(code: string, topK = 10) {
  const response = await api.get<ApiEnvelope<{ reference_code: string; similar: SimilarFundRow[] }>>(
    "/agent/funds/similar",
    { params: { code, top_k: topK } }
  );
  return response.data.data;
}

export interface KlineSimilarFundRow {
  code: string;
  name: string;
  track: string;
  similarity: number;
  method: string;
  /** tiered 粗排（PAA+归一内积），有则展示 */
  coarse_similarity?: number;
  pipeline?: string;
  window_days?: number;
  aligned_points?: number;
  nav_series?: string;
  rationale: string;
}

export async function fetchKlineSimilarFunds(
  code: string,
  topK = 10,
  days = 60,
  method: "tiered" | "cosine" | "dtw" = "tiered"
) {
  const response = await api.get<
    ApiEnvelope<{ reference_code: string; days: number; method: string; similar: KlineSimilarFundRow[] }>
  >("/agent/funds/kline-similar", {
    params: { code, top_k: topK, days, method },
    skipGlobalLoading: true,
    timeout: 120_000
  });
  return response.data.data;
}
