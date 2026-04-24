import { api, ApiEnvelope } from "./api";
import {
  AiAnalysisResult,
  HotNewsSnapshot,
  NoteItem,
  PostItem,
  ReplayAnalysisResult,
  Trade,
  TradeCurve,
  TradeStats
} from "../types/trade";

export async function fetchTrades() {
  const response = await api.get<ApiEnvelope<Trade[]>>("/trades");
  return response.data.data;
}

export interface SecuritySearchHit {
  code: string;
  name: string;
}

/** 新版「买入/卖出窗口」创建体；旧版 OCR 仍为单笔 trade_date 结构 */
export type TradeCreatePayload = Record<string, unknown>;

export interface CreateTradeResult {
  trade: Trade;
  dedup_hit: boolean;
}

export async function createTrade(payload: TradeCreatePayload) {
  const response = await api.post<ApiEnvelope<CreateTradeResult>>("/trades", payload);
  return response.data.data;
}

export async function deleteTrade(tradeId: number) {
  const response = await api.delete<ApiEnvelope<{ id: number }>>(`/trades/${tradeId}`);
  return response.data.data;
}

export async function searchTradeSecurities(q: string, limit = 40) {
  const qs = new URLSearchParams({ q, limit: String(limit) });
  const response = await api.get<ApiEnvelope<{ items: SecuritySearchHit[]; total: number }>>(
    `/trades/securities/search?${qs.toString()}`
  );
  return response.data.data;
}

export async function lookupTradeSecurity(code: string) {
  const c = encodeURIComponent(code.trim());
  const response = await api.get<ApiEnvelope<{ code: string; name: string }>>(`/trades/securities/lookup/${c}`);
  return response.data.data;
}

export async function importTradeByOcr(file: File) {
  const formData = new FormData();
  formData.append("file", file);
  const response = await api.post<ApiEnvelope<Trade[]>>("/trades/import/ocr", formData, {
    headers: { "Content-Type": "multipart/form-data" }
  });
  return response.data.data;
}

export async function fetchTradeStats() {
  const response = await api.get<ApiEnvelope<TradeStats>>("/trades/stats/summary");
  return response.data.data;
}

export async function fetchTradeCurve(symbol: string) {
  const code = encodeURIComponent(String(symbol || "").trim());
  const response = await api.get<ApiEnvelope<TradeCurve>>(`/trades/curve/${code}`);
  return response.data.data;
}

export async function fetchNotes() {
  const response = await api.get<ApiEnvelope<NoteItem[]>>("/notes");
  return response.data.data;
}

export async function createNote(payload: { trade_id?: number; title: string; content: string; tags?: string }) {
  const response = await api.post<ApiEnvelope<NoteItem>>("/notes", payload);
  return response.data.data;
}

export async function analyzeTrade(tradeId: number) {
  const response = await api.post<ApiEnvelope<AiAnalysisResult>>(`/ai/analyze/${tradeId}`, undefined, {
    skipGlobalLoading: true,
    timeout: 120_000
  });
  return response.data.data;
}

export async function analyzeReplayByTrade(tradeId: number) {
  const response = await api.post<ApiEnvelope<ReplayAnalysisResult>>(`/replay/analyze/trade/${tradeId}`, undefined, {
    skipGlobalLoading: true,
    timeout: 120_000
  });
  return response.data.data;
}

export async function analyzeReplayByNote(payload: { note_id?: number; title?: string; content?: string }) {
  const response = await api.post<ApiEnvelope<ReplayAnalysisResult>>("/replay/analyze/note", payload, {
    skipGlobalLoading: true,
    timeout: 120_000
  });
  return response.data.data;
}

export async function fetchHotNews() {
  const response = await api.get<ApiEnvelope<HotNewsSnapshot>>("/hot");
  return response.data.data;
}

export async function fetchPosts() {
  const response = await api.get<ApiEnvelope<PostItem[]>>("/community/posts");
  return response.data.data;
}

export async function createPost(payload: { title: string; content: string }) {
  const response = await api.post<ApiEnvelope<PostItem>>("/community/posts", payload);
  return response.data.data;
}

export async function likePost(postId: number) {
  const response = await api.post<ApiEnvelope<PostItem>>(`/community/posts/${postId}/like`);
  return response.data.data;
}
