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

export interface MAFBTaskSubmitData {
  task_id: string;
  status: "queued" | "running" | "completed" | "failed";
}

export interface MAFBTaskStatusData {
  task_id: string;
  status: "queued" | "running" | "completed" | "failed";
  stage_node?: string | null;
  stage_label?: string | null;
  error?: string | null;
  created_at?: number;
  updated_at?: number;
  done: boolean;
  trace_events?: Array<{ ts?: number; kind?: string; message?: string; node?: string }>;
  next_cursor?: number;
  data?: MAFBRunData;
}

export interface LLMProbePayload {
  model?: string;
  prompt: string;
  timeout_sec?: number;
}

export interface LLMProbeData {
  ok: boolean;
  channel: string;
  model: string;
  elapsed_sec: number;
  status_code?: number | null;
  code?: string | null;
  message?: string | null;
  raw?: string | null;
}

export interface AgentProfilePayload {
  user_birth: string;
  birth_time_slot?: string;
  user_mbti: string;
  risk_preference?: number | null;
}

export async function runMafb(payload: MAFBRunPayload) {
  const response = await api.post<ApiEnvelope<MAFBRunData>>("/agent/run", payload);
  return response.data.data;
}

/** 异步提交 MAFB：立即返回 task_id，后续轮询 status 接口 */
export async function runMafbAsync(payload: MAFBRunPayload) {
  const response = await api.post<ApiEnvelope<MAFBTaskSubmitData>>("/agent/run/async", payload, {
    skipGlobalLoading: true
  });
  return response.data.data;
}

export async function getMafbTaskStatus(taskId: string, since = 0) {
  const response = await api.get<ApiEnvelope<MAFBTaskStatusData>>(`/agent/status/${taskId}`, {
    params: { since },
    skipGlobalLoading: true
  });
  return response.data.data;
}

export async function postLlmProbe(payload: LLMProbePayload) {
  const response = await api.post<ApiEnvelope<LLMProbeData>>("/agent/llm-probe", payload, {
    skipGlobalLoading: true
  });
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

export interface KlineShadowPoint {
  date: string;
  nav: number;
}

export interface KlineShadowSegment {
  code: string;
  start_date: string;
  end_date: string;
  similarity: number;
  fwd_return_5d?: number | null;
  fwd_return_10d?: number | null;
  fwd_return_20d?: number | null;
  points: KlineShadowPoint[];
}

export interface KlineShadowResponse {
  reference_code: string;
  ok: boolean;
  error?: string | null;
  query?: Record<string, unknown> | null;
  match_dates: Array<{ code: string; start_date: string; end_date: string; similarity: number }>;
  segments: KlineShadowSegment[];
  data_version?: Record<string, unknown>;
}

export interface MAFBAssetItem {
  id: number;
  title: string;
  fund_code: string;
  include_fbti: boolean;
  weighted_total?: number | null;
  verdict?: string | null;
  created_at?: string | null;
  is_pinned?: boolean;
}

export interface MAFBAssetDetail {
  id: number;
  title: string;
  fund_code: string;
  include_fbti: boolean;
  created_at?: string | null;
  final_report: Record<string, unknown>;
}

export async function saveMafbReportAsset(payload: {
  fund_code: string;
  include_fbti?: boolean;
  title?: string;
  final_report: Record<string, unknown>;
}) {
  const response = await api.post<ApiEnvelope<{ id: number; title: string; fund_code: string; created_at?: string | null }>>(
    "/agent/reports/save",
    payload,
    { skipGlobalLoading: true, timeout: 30_000 }
  );
  return response.data.data;
}

export async function listMafbReportAssets(params?: {
  limit?: number;
  fund_code?: string;
  date_from?: string;
  date_to?: string;
}) {
  const response = await api.get<ApiEnvelope<{ items: MAFBAssetItem[]; total: number }>>("/agent/reports", {
    params: {
      limit: params?.limit ?? 30,
      fund_code: params?.fund_code || undefined,
      date_from: params?.date_from || undefined,
      date_to: params?.date_to || undefined
    },
    skipGlobalLoading: true,
    timeout: 20_000
  });
  return response.data.data;
}

export async function getMafbReportAsset(reportId: number) {
  const response = await api.get<ApiEnvelope<MAFBAssetDetail>>(`/agent/reports/${reportId}`, {
    skipGlobalLoading: true,
    timeout: 20_000
  });
  return response.data.data;
}

export async function updateMafbReportAsset(
  reportId: number,
  payload: {
    title?: string;
    is_pinned?: boolean;
  }
) {
  const response = await api.patch<ApiEnvelope<{ id: number }>>(`/agent/reports/${reportId}`, payload, {
    skipGlobalLoading: true,
    timeout: 20_000
  });
  return response.data.data;
}

export async function deleteMafbReportAsset(reportId: number) {
  const response = await api.delete<ApiEnvelope<{ id: number }>>(`/agent/reports/${reportId}`, {
    skipGlobalLoading: true,
    timeout: 20_000
  });
  return response.data.data;
}

export async function fetchKlineShadowSegments(
  code: string,
  topK = 5,
  signal?: AbortSignal
): Promise<KlineShadowResponse> {
  const baseURL = import.meta.env.VITE_API_BASE_URL || "/api/v1";
  const token = useUserStore.getState().token;
  const qs = new URLSearchParams({ code: code.trim(), top_k: String(topK) });
  const res = await fetch(`${baseURL}/agent/funds/kline-shadow?${qs.toString()}`, {
    method: "GET",
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    },
    signal
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  const body = (await res.json()) as ApiEnvelope<KlineShadowResponse>;
  return body.data;
}
