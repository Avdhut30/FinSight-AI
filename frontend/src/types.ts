export type PricePoint = {
  date: string;
  close: number;
};

export type NewsItem = {
  title: string;
  summary?: string | null;
  publisher?: string | null;
  link?: string | null;
  published_at?: string | null;
  sentiment_label?: string | null;
  sentiment_score?: number | null;
};

export type StockSnapshot = {
  ticker: string;
  company_name: string;
  currency?: string | null;
  exchange?: string | null;
  sector?: string | null;
  current_price: number;
  previous_close?: number | null;
  day_change_percent?: number | null;
  market_cap?: number | null;
  pe_ratio?: number | null;
  volume?: number | null;
  average_volume?: number | null;
  fifty_two_week_high?: number | null;
  fifty_two_week_low?: number | null;
  one_month_return_percent?: number | null;
  six_month_return_percent?: number | null;
  rsi_14?: number | null;
  support_level?: number | null;
  resistance_level?: number | null;
  risk_score?: number | null;
  trend_signal: string;
  valuation_signal: string;
  summary: string;
  ai_summary?: string | null;
  price_history: PricePoint[];
};

export type SentimentSummary = {
  overall_label: string;
  score: number;
  confidence: number;
  positive_count: number;
  negative_count: number;
  neutral_count: number;
  summary: string;
};

export type AnalyzeResponse = {
  analysis_id: string;
  created_at: string;
  query: string;
  recommendation: string;
  confidence: number;
  answer: string;
  generation_mode: string;
  stock: StockSnapshot;
  sentiment: SentimentSummary;
  news: NewsItem[];
  thesis_points: string[];
  risk_factors: string[];
  data_sources: string[];
  decision?: DecisionPayload | null;
  specialists: SpecialistSignal[];
  chart_insight?: ChartInsight | null;
  historical_context?: HistoricalContext | null;
  memory_context: MemoryInsight[];
};

export type WatchlistResponse = {
  generated_at: string;
  items: StockSnapshot[];
};

export type DecisionPayload = {
  decision: "BUY" | "HOLD" | "SELL";
  confidence: number;
  reasons: string[];
  risks: string[];
};

export type SpecialistSignal = {
  agent_name: string;
  stance: "bullish" | "neutral" | "bearish";
  confidence: number;
  score: number;
  reasons: string[];
};

export type ChartInsight = {
  momentum: string;
  support_level?: number | null;
  resistance_level?: number | null;
  rsi_14?: number | null;
  summary: string;
};

export type HistoricalContext = {
  period: string;
  return_percent?: number | null;
  sentiment_shift: string;
  key_events: string[];
  summary: string;
};

export type MemoryInsight = {
  analysis_id: string;
  ticker: string;
  query: string;
  recommendation: string;
  summary: string;
};

export type PortfolioHoldingInput = {
  ticker: string;
  weight?: number | null;
};

export type PortfolioHoldingAnalysis = {
  ticker: string;
  company_name: string;
  weight: number;
  risk_score: number;
  trend_signal: string;
  sentiment_label: string;
  recommendation: string;
  summary: string;
};

export type PortfolioAnalysisResponse = {
  generated_at: string;
  risk_level: string;
  diversification_score: number;
  concentration_score: number;
  overexposed_tickers: string[];
  suggestions: string[];
  holdings: PortfolioHoldingAnalysis[];
};

export type AlertResponse = {
  id: string;
  ticker: string;
  alert_type: string;
  threshold_value: number;
  active: boolean;
  triggered: boolean;
  current_price?: number | null;
  message: string;
  created_at: string;
};

export type UserProfile = {
  id: string;
  email: string;
  name: string;
  created_at: string;
};

export type AuthResponse = {
  token: string;
  user: UserProfile;
};

export type WatchlistItem = {
  ticker: string;
  created_at: string;
};

export type SavedWatchlistResponse = {
  items: WatchlistItem[];
};

export type UserHistoryItem = {
  analysis_id: string;
  created_at: string;
  query: string;
  ticker: string;
  recommendation: string;
  confidence: number;
  answer: string;
};

export type UserHistoryResponse = {
  items: UserHistoryItem[];
};
