import { api, ApiEnvelope } from "./api";

export interface MAFBRunPayload {
  fund_code: string;
  user_birth?: string | null;
  user_mbti?: string | null;
  layout_facing?: string | null;
  use_saved_profile?: boolean;
}

export interface MAFBRunData {
  final_report: Record<string, unknown>;
  state_snapshot: Record<string, unknown>;
}

export interface AgentProfilePayload {
  user_birth: string;
  user_mbti: string;
  layout_facing?: string | null;
  risk_preference?: number | null;
}

export async function runMafb(payload: MAFBRunPayload) {
  const response = await api.post<ApiEnvelope<MAFBRunData>>("/agent/run", payload);
  return response.data.data;
}

export async function saveAgentProfile(payload: AgentProfilePayload) {
  const response = await api.post<ApiEnvelope<Record<string, unknown>>>("/agent/profile", payload);
  return response.data.data;
}

export async function getAgentProfile() {
  const response = await api.get<ApiEnvelope<Record<string, unknown>>>("/agent/profile");
  return response.data.data;
}

export async function listAgentFunds() {
  const response = await api.get<ApiEnvelope<Record<string, unknown>[]>>("/agent/funds");
  return response.data.data;
}

export async function ocrBirth(file: File) {
  const formData = new FormData();
  formData.append("file", file);
  const response = await api.post<ApiEnvelope<{ user_birth: string | null; hint: string }>>(
    "/agent/ocr-birth",
    formData,
    { headers: { "Content-Type": "multipart/form-data" } }
  );
  return response.data.data;
}

export async function ocrFundCode(file: File) {
  const formData = new FormData();
  formData.append("file", file);
  const response = await api.post<ApiEnvelope<{ codes: string[]; primary_code: string | null; hint: string }>>(
    "/ocr/fund-code",
    formData,
    { headers: { "Content-Type": "multipart/form-data" } }
  );
  return response.data.data;
}

export interface SimilarFundRow {
  code: string;
  name: string;
  track: string;
  similarity: number;
  rationale: string;
}

export async function fetchSimilarFunds(code: string, topK = 5) {
  const response = await api.get<ApiEnvelope<{ reference_code: string; similar: SimilarFundRow[] }>>(
    "/agent/funds/similar",
    { params: { code, top_k: topK } }
  );
  return response.data.data;
}
