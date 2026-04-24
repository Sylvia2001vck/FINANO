export type TradeDirection = "buy" | "sell";

export interface Trade {
  id: number;
  user_id: number;
  trade_date: string;
  /** 买入日（新版表单）；旧数据可能为 null */
  buy_date?: string | null;
  /** 卖出日；null 常表示仍持仓 */
  sell_date?: string | null;
  /** 卖出成交额（毛），已了结时有值 */
  sell_amount?: number | null;
  symbol: string;
  name: string;
  direction: TradeDirection;
  quantity: number;
  price: number;
  amount: number;
  fee: number;
  profit: number;
  platform: string;
  notes?: string | null;
  created_at: string;
  updated_at: string;
}

export interface TradeStats {
  total_trades: number;
  win_rate: number;
  profit_factor: number;
  max_drawdown: number;
  total_profit: number;
  avg_profit: number;
  daily_pnl_series?: TradeDailyPnlPoint[];
}

export interface TradeDailyPnlPoint {
  date: string;
  daily_pnl: number;
  cumulative_pnl: number;
}

export interface TradeCurvePoint {
  date: string;
  nav: number;
}

export interface TradeCurveMarker {
  trade_id: number;
  date: string;
  action: "buy" | "sell";
  amount?: number | null;
  quantity: number;
  nav?: number | null;
  label: string;
}

export interface TradeCurve {
  symbol: string;
  name: string;
  points: TradeCurvePoint[];
  markers: TradeCurveMarker[];
}

export interface NoteItem {
  id: number;
  user_id: number;
  trade_id?: number | null;
  title: string;
  content: string;
  tags?: string | null;
  created_at: string;
  updated_at: string;
}

export interface HotNewsItem {
  id?: number | null;
  news_id: string;
  rank: number;
  title: string;
  summary: string;
  source: string;
  batch_time: string;
  publish_time: string;
  sentiment_score?: number | null;
  created_at: string;
}

export interface HotNewsSnapshot {
  items: HotNewsItem[];
  batch_time: string;
  updated_at: string;
}

export interface PostItem {
  id: number;
  user_id: number;
  title: string;
  content: string;
  likes: number;
  comments: number;
  created_at: string;
  updated_at: string;
}

export interface AiAnalysisResult {
  strengths: string[];
  problems: string[];
  suggestions: string[];
}

export type ReplayIntent = "trade" | "note";
export type ReplayRoute = "history_compare" | "native_analysis";
export type ReplaySource = "sql" | "faiss" | "mixed" | "none";

export interface ReplayMatchedTrade {
  trade_id: number;
  symbol: string;
  name: string;
  trade_date: string;
  amount: number;
  profit: number;
  similarity: number;
  notes: string[];
}

export interface ReplayMatchedNote {
  note_id: number;
  title: string;
  content_preview: string;
  created_at: string;
  similarity: number;
  trade_id?: number | null;
  trade_symbol?: string | null;
  trade_profit?: number | null;
}

export interface ReplayAnalysisResult {
  intent: ReplayIntent;
  route: ReplayRoute;
  retrieval_source: ReplaySource;
  top_score: number;
  similarity_threshold: number;
  has_match: boolean;
  analysis: string;
  suggestions: string[];
  matched_trades: ReplayMatchedTrade[];
  matched_notes: ReplayMatchedNote[];
  trace: string[];
}
