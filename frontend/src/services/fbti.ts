import { api, ApiEnvelope } from "./api";
import { useUserStore } from "../store/userStore";
import { User } from "../types/user";

export interface FbtiArchetype {
  code: string;
  name: string;
  wuxing: string;
  tags?: string[];
  /** 与 description 相同，兼容旧前端 */
  blurb?: string;
  description?: string;
  risk_level?: string;
  fund_preference?: string;
  style_tags?: string[];
  nearest_archetype?: boolean;
  matched_code?: string;
}

export interface FbtiTestResponse {
  fbti_code: string;
  fbti_profile: string;
  archetype: FbtiArchetype;
  bazi_wuxing_hint: string;
  user_wuxing: string;
  user: User;
}

export async function postFbtiTest(answers: string[]) {
  const response = await api.post<ApiEnvelope<FbtiTestResponse>>("/user/fbti/test", {
    answers
  });
  return response.data.data;
}

export async function getFbtiProfile() {
  const response = await api.get<
    ApiEnvelope<{
      fbti_profile: string | null;
      user_wuxing: string | null;
      birth_date: string | null;
      archetype: FbtiArchetype | null;
    }>
  >("/user/fbti/profile");
  return response.data.data;
}

export interface FbtiPersonalizedTop5Row {
  rank: number;
  code: string;
  name: string;
  track: string;
  composite_score: number;
  reason_mingli_structured: string;
  reason_finance: string;
  is_anchor?: boolean;
}

export interface FbtiSelectResponse {
  reason: string;
  funds: Array<{
    code: string;
    name: string;
    wuxing_tag: string;
    change_hint: string;
  }>;
  /** 五行/流年 + 统计的趣味 TOP5（与 MAFB 专业流水线解耦） */
  personalized_top5?: FbtiPersonalizedTop5Row[];
  intent?: Record<string, unknown>;
  strategy_bundle?: Record<string, unknown>;
}

export interface FbtiAiSelectPayload {
  natural_intent?: string;
  mood?: string;
  auto_confirm?: boolean;
}

export interface FbtiIntentPreview {
  intent: Record<string, unknown>;
  strategy_bundle: Record<string, unknown>;
  need_confirm: boolean;
}

export async function postFbtiAiSelect(payload: FbtiAiSelectPayload = {}) {
  const response = await api.post<ApiEnvelope<FbtiSelectResponse>>("/agent/ai/fbti-select", payload, {
    skipGlobalLoading: true,
    timeout: 600_000
  });
  return response.data.data;
}

export async function postFbtiAiIntentPreview(payload: FbtiAiSelectPayload = {}) {
  const response = await api.post<ApiEnvelope<FbtiIntentPreview>>("/agent/ai/fbti-select/intent", payload, {
    skipGlobalLoading: true,
    timeout: 120_000,
  });
  return response.data.data;
}

/** SSE：阶段文案 + 最终结果（与 postFbtiAiSelect 返回结构一致） */
export async function postFbtiAiSelectStream(
  handlers: { onStage?: (node: string, label: string) => void; onIntent?: (payload: Record<string, unknown>) => void; onStrategy?: (payload: Record<string, unknown>) => void },
  payload: FbtiAiSelectPayload = {},
) {
  const baseURL = import.meta.env.VITE_API_BASE_URL || "/api/v1";
  const token = useUserStore.getState().token;
  const res = await fetch(`${baseURL}/agent/ai/fbti-select/stream`, {
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
  let result: FbtiSelectResponse | null = null;
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
          data?: FbtiSelectResponse;
          data_obj?: Record<string, unknown>;
          message?: string;
        };
        if (msg.event === "stage" && msg.node && msg.label) {
          handlers.onStage?.(msg.node, msg.label);
        }
        if (msg.event === "intent" && msg.data && typeof msg.data === "object") {
          handlers.onIntent?.(msg.data as unknown as Record<string, unknown>);
        }
        if (msg.event === "strategy" && msg.data && typeof msg.data === "object") {
          handlers.onStrategy?.(msg.data as unknown as Record<string, unknown>);
        }
        if (msg.event === "result" && msg.data) {
          result = msg.data;
        }
        if (msg.event === "error") {
          throw new Error(msg.message || "FBTI 选股流式失败");
        }
      }
    }
  }
  if (!result) throw new Error("未收到完整选股结果");
  return result;
}
