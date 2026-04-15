import { api, ApiEnvelope } from "./api";
import { User } from "../types/user";

export interface FbtiArchetype {
  code: string;
  name: string;
  wuxing: string;
  tags?: string[];
  blurb?: string;
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

export async function postFbtiTest(answers: string[], birth_date?: string) {
  const response = await api.post<ApiEnvelope<FbtiTestResponse>>("/user/fbti/test", {
    answers,
    birth_date: birth_date || undefined
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

export interface FbtiSelectResponse {
  reason: string;
  funds: Array<{
    code: string;
    name: string;
    wuxing_tag: string;
    change_hint: string;
  }>;
}

export async function postFbtiAiSelect() {
  const response = await api.post<ApiEnvelope<FbtiSelectResponse>>("/agent/ai/fbti-select", {});
  return response.data.data;
}
