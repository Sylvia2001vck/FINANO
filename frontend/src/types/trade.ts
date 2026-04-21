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
