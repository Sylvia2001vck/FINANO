import { api, ApiEnvelope } from "./api";
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
}

export async function postFbtiAiSelect() {
  const response = await api.post<ApiEnvelope<FbtiSelectResponse>>("/agent/ai/fbti-select", {});
  return response.data.data;
}
