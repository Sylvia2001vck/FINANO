import { api, ApiEnvelope } from "./api";
import { AiAnalysisResult, HotNewsItem, NoteItem, PostItem, Trade, TradeStats } from "../types/trade";

export async function fetchTrades() {
  const response = await api.get<ApiEnvelope<Trade[]>>("/trades");
  return response.data.data;
}

export async function createTrade(payload: Omit<Trade, "id" | "user_id" | "created_at" | "updated_at">) {
  const response = await api.post<ApiEnvelope<Trade>>("/trades", payload);
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

export async function fetchNotes() {
  const response = await api.get<ApiEnvelope<NoteItem[]>>("/notes");
  return response.data.data;
}

export async function createNote(payload: { trade_id?: number; title: string; content: string; tags?: string }) {
  const response = await api.post<ApiEnvelope<NoteItem>>("/notes", payload);
  return response.data.data;
}

export async function analyzeTrade(tradeId: number) {
  const response = await api.post<ApiEnvelope<AiAnalysisResult>>(`/ai/analyze/${tradeId}`);
  return response.data.data;
}

export async function fetchHotNews() {
  const response = await api.get<ApiEnvelope<HotNewsItem[]>>("/hot");
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
