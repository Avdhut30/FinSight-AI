import type {
  AlertResponse,
  AnalyzeResponse,
  AuthResponse,
  PortfolioAnalysisResponse,
  SavedWatchlistResponse,
  UserHistoryResponse,
  UserProfile,
  WatchlistResponse
} from "../types";

const API_URL = import.meta.env.VITE_API_URL ?? import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const REQUEST_ID_HEADER = "X-Request-ID";

type AnalysisStreamStatus = {
  stage: string;
  message: string;
};

type AnalysisStreamDelta = {
  delta: string;
};

type AnalyzeStockStreamHandlers = {
  onStatus?: (event: AnalysisStreamStatus) => void;
  onAnswerDelta?: (event: AnalysisStreamDelta) => void;
  onComplete?: (analysis: AnalyzeResponse) => void;
};

type RequestOptions = RequestInit & {
  token?: string | null;
};

type StreamEvent = {
  event: string;
  data: unknown;
};

function buildJsonInit(init?: RequestOptions): RequestInit {
  const headers = new Headers(init?.headers);
  headers.set("Content-Type", "application/json");
  if (init?.token) {
    headers.set("Authorization", `Bearer ${init.token}`);
  }

  return {
    headers,
    ...init
  };
}

async function createRequestError(response: Response): Promise<Error> {
  const requestId = response.headers.get(REQUEST_ID_HEADER);
  const payload = await response.json().catch(() => ({ detail: "Request failed." }));
  const message = payload.detail ?? "Request failed.";
  const error = new Error(requestId ? `${message} Request ID: ${requestId}` : message);
  (error as any).status = response.status;
  (error as any).requestId = requestId;
  return error;
}

function parseStreamBlock(block: string): StreamEvent | null {
  const trimmed = block.trim();
  if (!trimmed) {
    return null;
  }

  let event = "message";
  const dataLines: string[] = [];

  for (const line of trimmed.split(/\r?\n/)) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
      continue;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }

  if (!dataLines.length) {
    return null;
  }

  return {
    event,
    data: JSON.parse(dataLines.join("\n"))
  };
}

function handleStreamEvent(
  streamEvent: StreamEvent,
  handlers: AnalyzeStockStreamHandlers,
  requestId: string | null
): AnalyzeResponse | null {
  if (streamEvent.event === "status") {
    handlers.onStatus?.(streamEvent.data as AnalysisStreamStatus);
    return null;
  }

  if (streamEvent.event === "answer_delta") {
    handlers.onAnswerDelta?.(streamEvent.data as AnalysisStreamDelta);
    return null;
  }

  if (streamEvent.event === "complete") {
    const analysis = streamEvent.data as AnalyzeResponse;
    handlers.onComplete?.(analysis);
    return analysis;
  }

  if (streamEvent.event === "error") {
    const detail =
      typeof streamEvent.data === "object" && streamEvent.data && "detail" in streamEvent.data
        ? String((streamEvent.data as { detail: string }).detail)
        : "Streaming request failed.";
    throw new Error(requestId ? `${detail} Request ID: ${requestId}` : detail);
  }

  return null;
}

async function request<T>(path: string, init?: RequestOptions): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, buildJsonInit(init));

  if (!response.ok) {
    throw await createRequestError(response);
  }
  return response.json() as Promise<T>;
}

export function fetchWatchlist(): Promise<WatchlistResponse> {
  return request<WatchlistResponse>("/api/v1/watchlist");
}

export function analyzeStock(query: string): Promise<AnalyzeResponse> {
  return request<AnalyzeResponse>("/api/v1/analyze", {
    method: "POST",
    body: JSON.stringify({ query, use_llm: false })
  });
}

export async function analyzeStockStream(
  query: string,
  handlers: AnalyzeStockStreamHandlers = {},
  token?: string | null
): Promise<AnalyzeResponse> {
  const response = await fetch(
    `${API_URL}/api/v1/analyze/stream`,
    buildJsonInit({
      method: "POST",
      body: JSON.stringify({ query, use_llm: false }),
      token
    })
  );

  if (!response.ok) {
    throw await createRequestError(response);
  }

  if (!response.body) {
    const fallback = await analyzeStock(query);
    handlers.onComplete?.(fallback);
    return fallback;
  }

  const requestId = response.headers.get(REQUEST_ID_HEADER);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completedAnalysis: AnalyzeResponse | null = null;

  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });

      const blocks = buffer.split("\n\n");
      buffer = blocks.pop() ?? "";

      for (const block of blocks) {
        const streamEvent = parseStreamBlock(block);
        if (!streamEvent) {
          continue;
        }

        const maybeAnalysis = handleStreamEvent(streamEvent, handlers, requestId);
        if (maybeAnalysis) {
          completedAnalysis = maybeAnalysis;
        }
      }

      if (done) {
        break;
      }
    }

    if (buffer.trim()) {
      const streamEvent = parseStreamBlock(buffer);
      if (streamEvent) {
        const maybeAnalysis = handleStreamEvent(streamEvent, handlers, requestId);
        if (maybeAnalysis) {
          completedAnalysis = maybeAnalysis;
        }
      }
    }
  } finally {
    reader.releaseLock();
  }

  if (!completedAnalysis) {
    throw new Error(requestId ? `Stream ended unexpectedly. Request ID: ${requestId}` : "Stream ended unexpectedly.");
  }

  return completedAnalysis;
}

export function analyzePortfolio(tickers: string[]): Promise<PortfolioAnalysisResponse> {
  return request<PortfolioAnalysisResponse>("/api/v1/portfolio/analyze", {
    method: "POST",
    body: JSON.stringify({
      holdings: tickers.filter(Boolean).map((ticker) => ({ ticker }))
    })
  });
}

export function registerUser(name: string, email: string, password: string): Promise<AuthResponse> {
  return request<AuthResponse>("/api/v1/auth/register", {
    method: "POST",
    body: JSON.stringify({ name, email, password })
  });
}

export function loginUser(email: string, password: string): Promise<AuthResponse> {
  return request<AuthResponse>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password })
  });
}

export function fetchCurrentUser(token: string): Promise<UserProfile> {
  return request<UserProfile>("/api/v1/auth/me", { token });
}

export function fetchUserHistory(token: string): Promise<UserHistoryResponse> {
  return request<UserHistoryResponse>("/api/v1/me/history", { token });
}

export function fetchSavedWatchlist(token: string): Promise<SavedWatchlistResponse> {
  return request<SavedWatchlistResponse>("/api/v1/me/watchlist", { token });
}

export function saveTickerToWatchlist(token: string, ticker: string): Promise<SavedWatchlistResponse> {
  return request<SavedWatchlistResponse>("/api/v1/me/watchlist", {
    method: "POST",
    body: JSON.stringify({ ticker }),
    token
  });
}

export function createAlert(
  token: string,
  ticker: string,
  alertType: "price_above" | "price_below" | "percent_drop",
  thresholdValue: number
): Promise<AlertResponse> {
  return request<AlertResponse>("/api/v1/alerts", {
    method: "POST",
    body: JSON.stringify({ ticker, alert_type: alertType, threshold_value: thresholdValue }),
    token
  });
}

export function fetchAlerts(token: string): Promise<AlertResponse[]> {
  return request<AlertResponse[]>("/api/v1/alerts", { token });
}

export function healthCheck(): Promise<{ status: string }> {
  return request<{ status: string }>("/api/v1/health");
}
