import { FormEvent, useEffect, useState } from "react";
import { Sparkline } from "./components/Sparkline";
import {
  analyzePortfolio,
  analyzeStockStream,
  createAlert,
  fetchAlerts,
  fetchCurrentUser,
  fetchSavedWatchlist,
  fetchUserHistory,
  loginUser,
  healthCheck,
  registerUser,
  saveTickerToWatchlist
} from "./lib/api";
import type { AlertResponse, AnalyzeResponse, PortfolioAnalysisResponse, StockSnapshot, UserProfile, WatchlistItem } from "./types";

type ChatMessage = { id: string; role: "assistant" | "user"; content: string; analysis?: AnalyzeResponse };
type NotebookEntry = { id: string; created_at: string; analysis: AnalyzeResponse };
type AuthFieldErrors = { name?: string; email?: string; password?: string };

const TOKEN_STORAGE_KEY = "finsight-auth-token";
const NOTEBOOK_STORAGE_KEY = "finsight-notebook";
const MIN_PASSWORD_LENGTH = 8;
const MIN_EMAIL_LENGTH = 5;
const quickPrompts = [
  "Should I buy Infosys now?",
  "Why did TCS move today?",
  "What does recent news suggest for HDFC Bank?",
  "What was the trend of SBIN over the last 6 months?"
];
const personaOptions = [
  { id: "intraday", label: "Intraday", prompt: "Prioritize same-day momentum, volume spikes, VWAP, and tight risk." },
  { id: "swing", label: "Swing", prompt: "Emphasize 1-3 week trend, breakouts, support/resistance, and catalysts." },
  { id: "investor", label: "Long-term", prompt: "Focus on fundamentals, moat, earnings trajectory, and valuation." }
];
const horizonOptions = [
  { id: "today", label: "Today", prompt: "Actionable within the current session." },
  { id: "1m", label: "1 month", prompt: "Position for the next 30 days." },
  { id: "6m", label: "6 months", prompt: "Mid-term view with cyclical context." }
];
const focusOptions = [
  { id: "technical", label: "Technical", prompt: "Chart structure, momentum, RSI, and levels." },
  { id: "fundamental", label: "Fundamental", prompt: "Earnings quality, margins, balance sheet, valuation." },
  { id: "sentiment", label: "Sentiment", prompt: "News tone, flows, and positioning shifts." }
];
const inrFormatter = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 });

function getStoredToken() {
  return typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_STORAGE_KEY);
}
function formatSignedPercent(value?: number | null) {
  return value === undefined || value === null ? "N/A" : `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}
function formatCurrency(value?: number | null) {
  return value === undefined || value === null ? "N/A" : inrFormatter.format(value);
}
function titleCase(value: string) {
  return value.split(/[-_\s]+/).map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");
}

export default function App() {
  const [query, setQuery] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [streamStatus, setStreamStatus] = useState("Ready");
  const [statusLog, setStatusLog] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([
    { id: "welcome", role: "assistant", content: "Ask about a stock, a chart setup, or a portfolio and I'll return a structured investment decision." }
  ]);
  const [analysis, setAnalysis] = useState<AnalyzeResponse | null>(null);
  const [trackedStocks, setTrackedStocks] = useState<StockSnapshot[]>([]);
  const [persona, setPersona] = useState<string>("swing");
  const [focusAreas, setFocusAreas] = useState<string[]>(["technical", "sentiment"]);
  const [horizon, setHorizon] = useState<string>("1m");
  const [health, setHealth] = useState<"checking" | "ok" | "down">("checking");
  const [lastLatencyMs, setLastLatencyMs] = useState<number | null>(null);
  const [notebook, setNotebook] = useState<NotebookEntry[]>(() => {
    if (typeof window === "undefined") return [];
    try {
      const raw = window.localStorage.getItem(NOTEBOOK_STORAGE_KEY);
      return raw ? (JSON.parse(raw) as NotebookEntry[]) : [];
    } catch {
      return [];
    }
  });

  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [authToken, setAuthToken] = useState<string | null>(() => getStoredToken());
  const [authBusy, setAuthBusy] = useState(false);
  const [authChecking, setAuthChecking] = useState(false);
  const [user, setUser] = useState<UserProfile | null>(null);
  const [authFieldErrors, setAuthFieldErrors] = useState<AuthFieldErrors>({});
  const [authName, setAuthName] = useState("");
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [savedWatchlist, setSavedWatchlist] = useState<WatchlistItem[]>([]);
  const [historyLabels, setHistoryLabels] = useState<string[]>([]);

  const [portfolioInput, setPortfolioInput] = useState("TCS, RELIANCE, INFY");
  const [portfolioResult, setPortfolioResult] = useState<PortfolioAnalysisResponse | null>(null);
  const [portfolioLoading, setPortfolioLoading] = useState(false);

  const [alerts, setAlerts] = useState<AlertResponse[]>([]);
  const [alertsLoading, setAlertsLoading] = useState(false);
  const [alertType, setAlertType] = useState<"price_above" | "price_below" | "percent_drop">("price_below");
  const [alertThreshold, setAlertThreshold] = useState("");

  function pushStatus(message: string) {
    setStatusLog((current) => (current[current.length - 1] === message ? current : [...current, message].slice(-8)));
  }

  function trackStock(stock: StockSnapshot) {
    setTrackedStocks((current) => [stock, ...current.filter((item) => item.ticker !== stock.ticker)].slice(0, 6));
  }

  function isAuthError(error: unknown) {
    return typeof error === "object" && error !== null && "status" in error && (error as any).status === 401;
  }

  function handleAuthFailure(message = "Session expired. Please login again.") {
    setAuthToken(null);
    setUser(null);
    setAuthError(message);
  }

  function buildQueryWithOptions(raw: string) {
    const personaText = personaOptions.find((item) => item.id === persona)?.prompt;
    const horizonText = horizonOptions.find((item) => item.id === horizon)?.prompt;
    const focusText = focusAreas
      .map((id) => focusOptions.find((item) => item.id === id)?.prompt)
      .filter(Boolean)
      .join(" | ");
    const meta = [personaText ? `Persona: ${personaText}` : null, horizonText ? `Horizon: ${horizonText}` : null, focusText ? `Emphasis: ${focusText}` : null].filter(Boolean);
    return meta.length ? `${raw}. ${meta.join(" ")}` : raw;
  }

  function toggleFocus(id: string) {
    setFocusAreas((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]));
  }

  function persistNotebook(next: NotebookEntry[]) {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(NOTEBOOK_STORAGE_KEY, JSON.stringify(next));
    }
  }

  async function pingHealth() {
    setHealth("checking");
    try {
      await healthCheck();
      setHealth("ok");
    } catch {
      setHealth("down");
    }
  }

  useEffect(() => {
    void pingHealth();
    const id = window.setInterval(() => void pingHealth(), 60000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    persistNotebook(notebook);
  }, [notebook]);

  async function loadWorkspace(token: string) {
    setAuthError(null);
    const [profile, history, watchlist, nextAlerts] = await Promise.all([
      fetchCurrentUser(token),
      fetchUserHistory(token),
      fetchSavedWatchlist(token),
      fetchAlerts(token)
    ]);
    setUser(profile);
    setHistoryLabels(history.items.map((item) => `${item.ticker} ${item.recommendation.toUpperCase()} ${Math.round(item.confidence * 100)}%`));
    setSavedWatchlist(watchlist.items);
    setAlerts(nextAlerts);
  }

  useEffect(() => {
    if (!authToken) {
      setUser(null);
      setSavedWatchlist([]);
      setHistoryLabels([]);
      setAlerts([]);
      setAuthChecking(false);
      if (typeof window !== "undefined") {
        window.localStorage.removeItem(TOKEN_STORAGE_KEY);
      }
      return;
    }
    if (typeof window !== "undefined") {
      window.localStorage.setItem(TOKEN_STORAGE_KEY, authToken);
    }
    setAuthChecking(true);
    void loadWorkspace(authToken)
      .catch((requestError) => {
        if (isAuthError(requestError)) {
          handleAuthFailure();
        } else {
          setAuthError(requestError instanceof Error ? requestError.message : "Could not load the user workspace.");
          setAuthToken(null);
        }
      })
      .finally(() => setAuthChecking(false));
  }, [authToken]);

  useEffect(() => {
    if (!authToken) return undefined;

    const intervalId = window.setInterval(() => {
      void fetchAlerts(authToken)
        .then((items) => setAlerts(items))
        .catch((err) => {
          if (isAuthError(err)) {
            handleAuthFailure();
          }
        });
    }, 30000);

    return () => window.clearInterval(intervalId);
  }, [authToken]);

  async function submitQuery(nextQuery: string) {
    const trimmed = nextQuery.trim();
    if (!trimmed) return;
    if (!authToken || !user) {
      setError("Please login to run an analysis.");
      return;
    }

    const enrichedQuery = buildQueryWithOptions(trimmed);
    const startedAt = typeof performance !== "undefined" ? performance.now() : Date.now();
    const assistantMessageId = `assistant-${Date.now()}`;
    let receivedAnswerDelta = false;
    setIsLoading(true);
    setError(null);
    setStatusLog([]);
    pushStatus("Resolving company and ticker...");
    setStreamStatus("Resolving company and ticker...");
    setMessages((current) => [...current, { id: `user-${Date.now()}`, role: "user", content: trimmed }, { id: assistantMessageId, role: "assistant", content: "Resolving company and ticker..." }]);

    try {
      await analyzeStockStream(
        enrichedQuery,
        {
          onStatus: (event) => {
            setStreamStatus(event.message);
            pushStatus(event.message);
            if (!receivedAnswerDelta) {
              setMessages((current) => current.map((message) => (message.id === assistantMessageId ? { ...message, content: event.message } : message)));
            }
          },
          onAnswerDelta: ({ delta }) => {
            const isFirstDelta = !receivedAnswerDelta;
            receivedAnswerDelta = true;
            setMessages((current) =>
              current.map((message) =>
                message.id === assistantMessageId ? { ...message, content: isFirstDelta ? delta : `${message.content}${delta}` } : message
              )
            );
          },
          onComplete: (nextAnalysis) => {
            setAnalysis(nextAnalysis);
            trackStock(nextAnalysis.stock);
            setMessages((current) =>
              current.map((message) =>
                message.id === assistantMessageId ? { id: nextAnalysis.analysis_id, role: "assistant", content: nextAnalysis.answer, analysis: nextAnalysis } : message
              )
            );
          }
        },
        authToken
      );
      if (authToken) await loadWorkspace(authToken);
      setQuery("");
    } catch (requestError) {
      if (isAuthError(requestError)) {
        handleAuthFailure();
      } else {
        setError(requestError instanceof Error ? requestError.message : "Analysis failed.");
      }
    } finally {
      setIsLoading(false);
      setStreamStatus("Ready");
      const endedAt = typeof performance !== "undefined" ? performance.now() : Date.now();
      setLastLatencyMs(Math.max(0, Math.round(endedAt - startedAt)));
    }
  }

  async function handleAuthSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAuthError(null);
    setAuthFieldErrors({});
    setAuthBusy(true);

    const trimmedEmail = authEmail.trim();
    const trimmedPassword = authPassword.trim();
    const trimmedName = authName.trim();

    const nextFieldErrors: AuthFieldErrors = {};
    if (trimmedEmail.length < MIN_EMAIL_LENGTH || !trimmedEmail.includes("@")) {
      nextFieldErrors.email = "Enter a valid email address.";
    }
    if (trimmedPassword.length < MIN_PASSWORD_LENGTH) {
      nextFieldErrors.password = `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
    }
    if (authMode === "register" && trimmedName.length < 2) {
      nextFieldErrors.name = "Please enter your full name.";
    }
    if (Object.keys(nextFieldErrors).length) {
      setAuthFieldErrors(nextFieldErrors);
      setAuthBusy(false);
      return;
    }

    try {
      const response = authMode === "register" ? await registerUser(trimmedName, trimmedEmail, trimmedPassword) : await loginUser(trimmedEmail, trimmedPassword);
      setUser(response.user);
      setAuthToken(response.token);
      setAuthPassword("");
      setError(null);
    } catch (requestError) {
      if (isAuthError(requestError)) {
        handleAuthFailure();
      } else {
        setAuthError(requestError instanceof Error ? requestError.message : "Authentication failed.");
      }
    } finally {
      setAuthBusy(false);
    }
  }

  async function handlePortfolioAnalyze() {
    const tickers = portfolioInput.split(",").map((item) => item.trim()).filter(Boolean);
    if (!tickers.length) return;
    setPortfolioLoading(true);
    try {
      setPortfolioResult(await analyzePortfolio(tickers));
    } catch (requestError) {
      if (isAuthError(requestError)) {
        handleAuthFailure();
      } else {
        setError(requestError instanceof Error ? requestError.message : "Portfolio analysis failed.");
      }
    } finally {
      setPortfolioLoading(false);
    }
  }

  async function handleSaveTicker() {
    if (!authToken || !analysis) return;
    try {
      const response = await saveTickerToWatchlist(authToken, analysis.stock.ticker);
      setSavedWatchlist(response.items);
    } catch (requestError) {
      if (isAuthError(requestError)) {
        handleAuthFailure();
      } else {
        setError(requestError instanceof Error ? requestError.message : "Could not save the ticker.");
      }
    }
  }

  async function handleCreateAlert() {
    if (!authToken || !analysis || !alertThreshold.trim()) return;
    setAlertsLoading(true);
    try {
      await createAlert(authToken, analysis.stock.ticker, alertType, Number(alertThreshold));
      setAlerts(await fetchAlerts(authToken));
      setAlertThreshold("");
    } catch (requestError) {
      if (isAuthError(requestError)) {
        handleAuthFailure();
      } else {
        setError(requestError instanceof Error ? requestError.message : "Could not create the alert.");
      }
    } finally {
      setAlertsLoading(false);
    }
  }

  function addToNotebook() {
    if (!analysis) return;
    const entry: NotebookEntry = {
      id: analysis.analysis_id,
      created_at: new Date().toISOString(),
      analysis
    };
    setNotebook((current) => {
      const next = [entry, ...current.filter((item) => item.id !== entry.id)].slice(0, 8);
      persistNotebook(next);
      return next;
    });
  }

  function removeNotebookEntry(id: string) {
    setNotebook((current) => {
      const next = current.filter((item) => item.id !== id);
      persistNotebook(next);
      return next;
    });
  }

  function restoreNotebookEntry(entry: NotebookEntry) {
    setAnalysis(entry.analysis);
    trackStock(entry.analysis.stock);
    setMessages((current) => [
      ...current,
      { id: `user-${Date.now()}`, role: "user", content: `Replaying saved analysis for ${entry.analysis.stock.ticker}` },
      { id: entry.analysis.analysis_id, role: "assistant", content: entry.analysis.answer, analysis: entry.analysis }
    ]);
  }

  async function copyLastAnswer() {
    if (!analysis || typeof navigator === "undefined") return;
    const payload = `${analysis.stock.ticker} — ${analysis.stock.company_name}\nDecision: ${analysis.decision?.decision ?? analysis.recommendation} (${analysis.decision?.confidence ?? Math.round(analysis.confidence * 100)}%)\n\n${analysis.answer}`;
    await navigator.clipboard.writeText(payload);
  }

  async function downloadLastAnswer() {
    if (!analysis || typeof document === "undefined") return;
    const payload = `${analysis.stock.ticker} — ${analysis.stock.company_name}\nDecision: ${analysis.decision?.decision ?? analysis.recommendation} (${analysis.decision?.confidence ?? Math.round(analysis.confidence * 100)}%)\n\n${analysis.answer}`;
    const blob = new Blob([payload], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${analysis.stock.ticker}-analysis.txt`;
    link.click();
    URL.revokeObjectURL(url);
  }

  const decisionLabel = analysis?.decision?.decision ?? analysis?.recommendation ?? "standby";
  const decisionConfidence = analysis ? analysis.decision?.confidence ?? Math.round(analysis.confidence * 100) : null;
  const activeTicker = analysis ? analysis.stock.ticker.replace(".NS", "").replace(".BO", "") : "Awaiting query";
  const triggeredAlerts = alerts.filter((item) => item.triggered).length;
  const isAuthenticated = Boolean(user && authToken);

  if (!isAuthenticated) {
    return (
      <div className="auth-shell">
        <div className="auth-hero-card">
          <div className="auth-hero-top">
            <p className="hero-kicker">FinSight AI</p>
            <span className="badge glow">Private Beta</span>
          </div>
          <h1 className="hero-title">Secure Research Workspace</h1>
          <p className="hero-copy">
            Log in to unlock streaming analysis, portfolio diagnostics, alerts, and a personal notebook. New users should create an
            account first—then you’ll be redirected into the full console.
          </p>
          <div className="auth-bullets">
            <span className="pill">Streaming agent trace</span>
            <span className="pill">Portfolio QA</span>
            <span className="pill">Smart alerts</span>
            <span className="pill">Notebook saves</span>
          </div>
          <div className="auth-stats">
            <article>
              <small>Avg response</small>
              <strong>~1.2s</strong>
            </article>
            <article>
              <small>Coverage</small>
              <strong>India + US</strong>
            </article>
            <article>
              <small>Security</small>
              <strong>Session JWT</strong>
            </article>
          </div>
        </div>
        <form className="auth-card auth-gate" onSubmit={handleAuthSubmit}>
          <div className="toggle-row">
            <button
              type="button"
              className={`toggle-chip ${authMode === "login" ? "active" : ""}`}
              onClick={() => {
                setAuthMode("login");
                setAuthError(null);
                setAuthFieldErrors({});
              }}
            >
              Login
            </button>
            <button
              type="button"
              className={`toggle-chip ${authMode === "register" ? "active" : ""}`}
              onClick={() => {
                setAuthMode("register");
                setAuthError(null);
                setAuthFieldErrors({});
              }}
            >
              Signup
            </button>
          </div>
          {authMode === "register" ? (
            <input
              value={authName}
              onChange={(event) => setAuthName(event.target.value)}
              placeholder="Full name"
              disabled={authBusy || authChecking}
              minLength={2}
              required
            />
          ) : null}
          {authFieldErrors.name ? <p className="input-hint error">{authFieldErrors.name}</p> : null}
          <input
            value={authEmail}
            onChange={(event) => setAuthEmail(event.target.value)}
            placeholder="Email"
            disabled={authBusy || authChecking}
            minLength={MIN_EMAIL_LENGTH}
            required
            type="email"
          />
          {authFieldErrors.email ? <p className="input-hint error">{authFieldErrors.email}</p> : null}
          <input
            type="password"
            value={authPassword}
            onChange={(event) => setAuthPassword(event.target.value)}
            placeholder={`Password (min ${MIN_PASSWORD_LENGTH} chars)`}
            disabled={authBusy || authChecking}
            minLength={MIN_PASSWORD_LENGTH}
            required
          />
          {authFieldErrors.password ? <p className="input-hint error">{authFieldErrors.password}</p> : null}
          <div className="auth-actions">
            <button
              type="submit"
              disabled={
                authBusy ||
                authChecking ||
                !authEmail ||
                !authPassword ||
                (authMode === "register" && !authName)
              }
            >
              {authChecking ? "Restoring session..." : authMode === "register" ? "Create account" : "Login"}
            </button>
            {authMode === "login" ? (
              <button
                type="button"
                className="ghost-button strong"
                onClick={() => {
                  setAuthMode("register");
                  setAuthError(null);
                }}
              >
                Create account
              </button>
            ) : (
              <button
                type="button"
                className="ghost-button"
                onClick={() => {
                  setAuthMode("login");
                  setAuthError(null);
                }}
              >
                Back to login
              </button>
            )}
          </div>
          {authError ? <div className="error-banner">{authError}</div> : null}
          <p className="auth-note">Only authenticated users can access the workspace. Passwords must be at least 8 characters.</p>
        </form>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <div className="command-bar">
        <div className="command-left">
          <span className={`status-dot status-${health}`} aria-label="Backend status" />
          <span className="command-label">
            Backend {health === "ok" ? "online" : health === "down" ? "unreachable" : "checking..."}
          </span>
          {lastLatencyMs !== null ? <span className="command-pill">Last run {lastLatencyMs} ms</span> : null}
          {analysis ? <span className="command-pill neutral">Active {analysis.stock.ticker}</span> : null}
        </div>
        <div className="command-actions">
          <button type="button" className="ghost-button" onClick={() => void pingHealth()}>
            Recheck
          </button>
          <button type="button" className="ghost-button" onClick={() => void copyLastAnswer()} disabled={!analysis}>
            Copy answer
          </button>
          <button type="button" className="ghost-button" onClick={() => void downloadLastAnswer()} disabled={!analysis}>
            Export .txt
          </button>
        </div>
      </div>
      <header className="hero">
        <div className="hero-main">
          <p className="hero-kicker">Stock Research Workspace</p>
          <div className="hero-title-row">
            <h1 className="hero-title">FinSight AI</h1>
            <span className="hero-badge">Operator Console</span>
          </div>
          <p className="hero-copy">
            A multi-agent investment decision workspace that combines live market data, explainable AI, portfolio diagnostics,
            alerts, user memory, and streaming execution in one industry-style interface.
          </p>
          <div className="hero-strip">
            <span className="hero-pill">Decision Engine</span>
            <span className="hero-pill">Explainable AI</span>
            <span className="hero-pill">Portfolio Intelligence</span>
            <span className="hero-pill">Streaming Workflow</span>
          </div>
        </div>
        <div className="hero-side">
          <div className="market-stamp">
            <span>Coverage</span>
            <strong>India-first + Multi-Agent</strong>
            <span>Data</span>
            <strong>Price + News + Signals + Memory</strong>
          </div>
          <div className="hero-stats">
            <article className="hero-stat">
              <span>Active Ticker</span>
              <strong>{activeTicker}</strong>
              <p>Current live analysis target</p>
            </article>
            <article className="hero-stat">
              <span>Decision</span>
              <strong>{titleCase(decisionLabel)}</strong>
              <p>{decisionConfidence !== null ? `${decisionConfidence}% confidence` : "Run a query to score conviction"}</p>
            </article>
            <article className="hero-stat">
              <span>Tracked Symbols</span>
              <strong>{trackedStocks.length}</strong>
              <p>Recent symbols in market pulse</p>
            </article>
            <article className="hero-stat">
              <span>Workspace</span>
              <strong>{user ? user.name : "Guest"}</strong>
              <p>{user ? `${triggeredAlerts} triggered alert${triggeredAlerts === 1 ? "" : "s"}` : "Login unlocks memory + alerts"}</p>
            </article>
          </div>
        </div>
      </header>

      <main className="layout">
        <section className="panel conversation-panel">
          <div className="panel-head">
          <div>
            <p className="eyebrow">Agent Chat</p>
            <h2>Ask a market question</h2>
            <p className="panel-subcopy">
              Run a stock query and the app will resolve the ticker, gather evidence, stream progress, and return a structured
              decision.
            </p>
          </div>
          <span className="status-pill">{isLoading ? streamStatus : "Ready"}</span>
        </div>
          <div className="builder-grid">
            <div className="builder-group">
              <div className="builder-label">Persona</div>
              <div className="builder-chips">
                {personaOptions.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className={`chip ${persona === item.id ? "chip-active" : ""}`}
                    onClick={() => setPersona(item.id)}
                    disabled={isLoading}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="builder-group">
              <div className="builder-label">Focus</div>
              <div className="builder-chips">
                {focusOptions.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className={`chip ${focusAreas.includes(item.id) ? "chip-active" : ""}`}
                    onClick={() => toggleFocus(item.id)}
                    disabled={isLoading}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="builder-group">
              <div className="builder-label">Horizon</div>
              <div className="builder-chips">
                {horizonOptions.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className={`chip ${horizon === item.id ? "chip-active" : ""}`}
                    onClick={() => setHorizon(item.id)}
                    disabled={isLoading}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
          <div className="prompt-grid">
            {quickPrompts.map((prompt) => (
              <button
                key={prompt}
                type="button"
                className="prompt-chip"
                onClick={() => {
                  setQuery(prompt);
                  void submitQuery(prompt);
                }}
                disabled={isLoading}
              >
                {prompt}
              </button>
            ))}
          </div>
          <div className="chat-stream-shell">
            <div className="chat-stream">
              {messages.map((message) => (
                <article key={message.id} className={`message ${message.role === "user" ? "message-user" : "message-assistant"}`}>
                  <div className="message-meta">
                    <span>{message.role === "user" ? "You" : "FinSight AI"}</span>
                    {message.analysis ? (
                      <span className="message-tag">
                        {message.analysis.stock.ticker} - {message.analysis.decision?.decision ?? message.analysis.recommendation}
                      </span>
                    ) : null}
                  </div>
                  <p>{message.content}</p>
                </article>
              ))}
            </div>
          </div>
          <form
            className="composer"
            onSubmit={(event) => {
              event.preventDefault();
              void submitQuery(query);
            }}
          >
            <label className="sr-only" htmlFor="query">Ask about a stock</label>
            <textarea id="query" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Example: Should I buy TCS now?" rows={3} disabled={isLoading} />
            <div className="composer-actions">
              <p>Streaming exposes the full agent pipeline in real time.</p>
              <button type="submit" disabled={isLoading || !query.trim()}>
                {isLoading ? "Analyzing..." : "Run analysis"}
              </button>
            </div>
          </form>
          <article className="detail-card status-card">
            <div className="detail-card-header">
              <h3>Streaming Trace</h3>
              <span>{statusLog.length} stages</span>
            </div>
            <ul className="detail-list compact-list">
              {statusLog.length ? statusLog.map((item) => <li key={item}>{item}</li>) : <li>Waiting for the next request.</li>}
            </ul>
          </article>
          {error ? <div className="error-banner">{error}</div> : null}
        </section>

        <aside className="panel rail-panel">
          <div className="panel-head">
            <div>
              <p className="eyebrow">Market Pulse</p>
              <h2>Tracked Tickers</h2>
              <p className="panel-subcopy">Only symbols you search appear here, with live AI context and recent trend data.</p>
            </div>
            <span className="status-pill status-pill-muted">{trackedStocks.length ? `${trackedStocks.length} live` : "Waiting"}</span>
          </div>
          <div className="watchlist-grid">
            {trackedStocks.map((item) => (
              <article key={item.ticker} className="watch-card">
                <div className="watch-card-header">
                  <div>
                    <strong>{item.ticker.replace(".NS", "").replace(".BO", "")}</strong>
                    <span>{item.company_name}</span>
                  </div>
                  <span className={item.day_change_percent && item.day_change_percent >= 0 ? "up" : "down"}>
                    {formatSignedPercent(item.day_change_percent)}
                  </span>
                </div>
                <div className="watch-card-price">{formatCurrency(item.current_price)}</div>
                <Sparkline points={item.price_history} />
                <div className="metric-row">
                  <span>Trend</span>
                  <strong>{titleCase(item.trend_signal)}</strong>
                </div>
                <div className="metric-row">
                  <span>Risk</span>
                  <strong>{item.risk_score ?? "N/A"}/100</strong>
                </div>
                {item.ai_summary ? <p className="watch-card-copy">{item.ai_summary}</p> : null}
              </article>
            ))}
          </div>
          {!trackedStocks.length ? (
            <article className="detail-card placeholder-card watchlist-placeholder">
              <p>Search TCS, HDFC Bank, SBIN, or another supported ticker to populate live AI intelligence here.</p>
            </article>
          ) : null}

          {analysis ? (
            <>
              <div className="panel-head analysis-head">
                <div>
                  <p className="eyebrow">Decision Engine</p>
                  <h2>{analysis.stock.company_name}</h2>
                  <p className="panel-subcopy">Structured recommendation, specialist reasoning, technical context, and prior memory.</p>
                </div>
                <span className={`signal-badge signal-${analysis.recommendation}`}>{analysis.decision?.decision ?? analysis.recommendation}</span>
              </div>
              <div className="analysis-overview-grid">
                <article className="overview-card">
                  <span>Live Price</span>
                  <strong>{formatCurrency(analysis.stock.current_price)}</strong>
                  <p>{analysis.stock.ticker}</p>
                </article>
                <article className="overview-card">
                  <span>Trend</span>
                  <strong>{titleCase(analysis.stock.trend_signal)}</strong>
                  <p>{formatSignedPercent(analysis.stock.one_month_return_percent)} one month</p>
                </article>
                <article className="overview-card">
                  <span>Risk Score</span>
                  <strong>{analysis.stock.risk_score ?? "N/A"}/100</strong>
                  <p>Signal-derived risk composite</p>
                </article>
              </div>
              <article className="decision-card">
                <div className="decision-topline">
                  <div>
                    <span>Decision</span>
                    <strong>{analysis.decision?.decision ?? analysis.recommendation.toUpperCase()}</strong>
                  </div>
                  <div>
                    <span>Confidence</span>
                    <strong>{analysis.decision?.confidence ?? Math.round(analysis.confidence * 100)}%</strong>
                  </div>
                </div>
                <div className="decision-kpis">
                  <div className="decision-kpi">
                    <span>RSI</span>
                    <strong>{analysis.stock.rsi_14 ?? "N/A"}</strong>
                  </div>
                  <div className="decision-kpi">
                    <span>Support</span>
                    <strong>{formatCurrency(analysis.stock.support_level)}</strong>
                  </div>
                  <div className="decision-kpi">
                    <span>Resistance</span>
                    <strong>{formatCurrency(analysis.stock.resistance_level)}</strong>
                  </div>
                </div>
                <div className="decision-columns">
                  <div>
                    <h3>Reasons</h3>
                    <ul className="detail-list compact-list">
                      {(analysis.decision?.reasons ?? analysis.thesis_points).map((item) => <li key={item}>{item}</li>)}
                    </ul>
                  </div>
                  <div>
                    <h3>Risks</h3>
                    <ul className="detail-list compact-list">
                      {(analysis.decision?.risks ?? analysis.risk_factors).map((item) => <li key={item}>{item}</li>)}
                    </ul>
                  </div>
                </div>
                <div className="decision-footer">
                  <p>{analysis.stock.ai_summary ?? analysis.stock.summary}</p>
                  <div className="decision-actions">
                    {user ? (
                      <button type="button" className="secondary-button secondary-button-inverse" onClick={() => void handleSaveTicker()}>
                        Save {analysis.stock.ticker}
                      </button>
                    ) : (
                      <span className="decision-note">Login to save this ticker and attach alerts to it.</span>
                    )}
                    <button type="button" className="secondary-button secondary-button-inverse" onClick={() => addToNotebook()}>
                      Pin to notebook
                    </button>
                  </div>
                </div>
              </article>
              <div className="specialist-grid">
                {analysis.specialists.map((item) => (
                  <article key={item.agent_name} className="stat-card specialist-card">
                    <span>{item.agent_name}</span>
                    <strong>{titleCase(item.stance)}</strong>
                    <p>{Math.round(item.confidence * 100)}% confidence</p>
                    <ul className="detail-list compact-list">
                      {item.reasons.map((reason) => <li key={reason}>{reason}</li>)}
                    </ul>
                  </article>
                ))}
              </div>
              <article className="detail-card">
                <div className="detail-card-header">
                  <h3>Chart + History</h3>
                  <span>{titleCase(analysis.chart_insight?.momentum ?? "neutral")}</span>
                </div>
                <p>{analysis.chart_insight?.summary ?? analysis.stock.ai_summary ?? analysis.stock.summary}</p>
                <div className="metric-row">
                  <span>Support</span>
                  <strong>{formatCurrency(analysis.chart_insight?.support_level ?? analysis.stock.support_level)}</strong>
                </div>
                <div className="metric-row">
                  <span>Resistance</span>
                  <strong>{formatCurrency(analysis.chart_insight?.resistance_level ?? analysis.stock.resistance_level)}</strong>
                </div>
                <div className="metric-row">
                  <span>Historical</span>
                  <strong>{analysis.historical_context?.summary ?? "Unavailable"}</strong>
                </div>
              </article>
              <article className="detail-card">
                <div className="detail-card-header">
                  <h3>Memory + Headlines</h3>
                  <span>{analysis.memory_context.length} memories</span>
                </div>
                <ul className="detail-list compact-list">
                  {analysis.memory_context.length ? (
                    analysis.memory_context.map((item) => (
                      <li key={item.analysis_id}>
                        <strong>{item.ticker}</strong>: {item.summary}
                      </li>
                    ))
                  ) : (
                    <li>No prior similar analyses were retrieved yet.</li>
                  )}
                </ul>
                <ul className="headline-list">
                  {analysis.news.slice(0, 4).map((item) => (
                    <li key={`${item.title}-${item.link ?? ""}`}>
                      <div>
                        <strong>{item.title}</strong>
                        <span>{item.publisher ?? "News source"}</span>
                      </div>
                      <span className={`sentiment-pill ${item.sentiment_label ?? "neutral"}`}>
                        {titleCase(item.sentiment_label ?? "neutral")}
                      </span>
                    </li>
                  ))}
                </ul>
              </article>
            </>
          ) : (
            <article className="detail-card placeholder-card">
              <p>Run a query to unlock the structured BUY/HOLD/SELL engine, specialist agents, historical context, and memory retrieval.</p>
            </article>
          )}
        </aside>
      </main>

      <section className="workspace-grid">
        <article className="panel workspace-panel">
          <div className="panel-head">
            <div>
              <p className="eyebrow">Authentication</p>
              <h2>{user ? "Your Workspace" : "Login / Signup"}</h2>
              <p className="panel-subcopy">Persist history, watchlist decisions, and smart alerts against a user session.</p>
            </div>
            {user ? (
              <button
                type="button"
                className="secondary-button"
                onClick={() => {
                  setAuthToken(null);
                  setAuthError(null);
                }}
              >
                Logout
              </button>
            ) : null}
          </div>
          {user ? (
            <>
              <div className="workspace-summary">
                <div>
                  <span>Signed in as</span>
                  <strong>{user.name}</strong>
                  <p>{user.email}</p>
                </div>
                <div>
                  <span>Saved Watchlist</span>
                  <strong>{savedWatchlist.length}</strong>
                  <p>Persistent user tickers</p>
                </div>
              </div>
              <article className="detail-card">
                <div className="detail-card-header">
                  <h3>Saved Watchlist</h3>
                </div>
                <ul className="detail-list compact-list">
                  {savedWatchlist.length ? savedWatchlist.map((item) => <li key={`${item.ticker}-${item.created_at}`}>{item.ticker}</li>) : <li>No saved watchlist items yet.</li>}
                </ul>
              </article>
              <article className="detail-card">
                <div className="detail-card-header">
                  <h3>Recent History</h3>
                </div>
                <ul className="detail-list compact-list">
                  {historyLabels.length ? historyLabels.map((item) => <li key={item}>{item}</li>) : <li>Run an authenticated analysis to build memory.</li>}
                </ul>
              </article>
            </>
          ) : (
            <form className="auth-form" onSubmit={handleAuthSubmit}>
              <div className="toggle-row">
                <button type="button" className={`toggle-chip ${authMode === "login" ? "active" : ""}`} onClick={() => setAuthMode("login")}>Login</button>
                <button type="button" className={`toggle-chip ${authMode === "register" ? "active" : ""}`} onClick={() => setAuthMode("register")}>Signup</button>
              </div>
              {authMode === "register" ? <input value={authName} onChange={(event) => setAuthName(event.target.value)} placeholder="Full name" /> : null}
              <input value={authEmail} onChange={(event) => setAuthEmail(event.target.value)} placeholder="Email" />
              <input type="password" value={authPassword} onChange={(event) => setAuthPassword(event.target.value)} placeholder="Password" />
              <button type="submit" disabled={!authEmail || !authPassword || (authMode === "register" && !authName)}>
                {authMode === "register" ? "Create account" : "Login"}
              </button>
            </form>
          )}
        </article>

        <article className="panel workspace-panel">
          <div className="panel-head">
            <div>
              <p className="eyebrow">Portfolio Analyzer</p>
              <h2>Risk and diversification</h2>
              <p className="panel-subcopy">Analyze portfolio concentration, diversification strength, and high-level position quality.</p>
            </div>
          </div>
          <div className="auth-form">
            <textarea value={portfolioInput} onChange={(event) => setPortfolioInput(event.target.value)} placeholder="TCS, RELIANCE, INFY" rows={3} />
            <button type="button" onClick={() => void handlePortfolioAnalyze()} disabled={portfolioLoading || !portfolioInput.trim()}>
              {portfolioLoading ? "Analyzing..." : "Analyze portfolio"}
            </button>
          </div>
          {portfolioResult ? (
            <>
              <div className="overview-grid workspace-overview">
                <article className="stat-card">
                  <span>Risk Level</span>
                  <strong>{titleCase(portfolioResult.risk_level)}</strong>
                  <p>Composite risk</p>
                </article>
                <article className="stat-card">
                  <span>Diversification</span>
                  <strong>{portfolioResult.diversification_score}</strong>
                  <p>Higher is better</p>
                </article>
                <article className="stat-card">
                  <span>Concentration</span>
                  <strong>{portfolioResult.concentration_score}</strong>
                  <p>Exposure concentration</p>
                </article>
                <article className="stat-card">
                  <span>Overexposed</span>
                  <strong>{portfolioResult.overexposed_tickers.length}</strong>
                  <p>{portfolioResult.overexposed_tickers.join(", ") || "Balanced"}</p>
                </article>
              </div>
              <article className="detail-card">
                <div className="detail-card-header">
                  <h3>Holdings</h3>
                </div>
                <ul className="detail-list compact-list">
                  {portfolioResult.holdings.map((item) => (
                    <li key={item.ticker}>
                      <strong>{item.ticker}</strong> {(item.weight * 100).toFixed(0)}% | {item.recommendation.toUpperCase()} | Risk {item.risk_score}
                    </li>
                  ))}
                </ul>
              </article>
              <article className="detail-card">
                <div className="detail-card-header">
                  <h3>Suggestions</h3>
                </div>
                <ul className="detail-list compact-list">
                  {portfolioResult.suggestions.map((item) => <li key={item}>{item}</li>)}
                </ul>
              </article>
            </>
          ) : (
            <article className="detail-card placeholder-card">
              <p>Enter a basket of tickers and the AI will score diversification, overexposure, and portfolio risk.</p>
            </article>
          )}
        </article>

        <article className="panel workspace-panel">
          <div className="panel-head">
            <div>
              <p className="eyebrow">Smart Alerts</p>
              <h2>Price and drawdown triggers</h2>
              <p className="panel-subcopy">Attach operational alerts to the currently analyzed ticker and keep them refreshed automatically.</p>
            </div>
          </div>
          {user && analysis ? (
            <>
              <div className="alert-form">
                <select value={alertType} onChange={(event) => setAlertType(event.target.value as typeof alertType)}>
                  <option value="price_below">Price below</option>
                  <option value="price_above">Price above</option>
                  <option value="percent_drop">Percent drop</option>
                </select>
                <input value={alertThreshold} onChange={(event) => setAlertThreshold(event.target.value)} placeholder={alertType === "percent_drop" ? "5" : "950"} />
                <button type="button" onClick={() => void handleCreateAlert()} disabled={alertsLoading || !alertThreshold.trim()}>
                  {alertsLoading ? "Saving..." : `Create on ${analysis.stock.ticker}`}
                </button>
              </div>
              <article className="detail-card">
                <div className="detail-card-header">
                  <h3>Alert Feed</h3>
                </div>
                <ul className="detail-list compact-list">
                  {alerts.length ? (
                    alerts.map((item) => (
                      <li key={item.id}>
                        <strong>{item.ticker}</strong> {titleCase(item.alert_type)} {item.threshold_value} | {item.message}
                      </li>
                    ))
                  ) : (
                    <li>No alerts yet.</li>
                  )}
                </ul>
              </article>
            </>
          ) : (
            <article className="detail-card placeholder-card">
              <p>Login and run an analysis to create alerts like "Notify if TCS drops 5%".</p>
            </article>
          )}
        </article>

        <article className="panel workspace-panel">
          <div className="panel-head">
            <div>
              <p className="eyebrow">Notebook</p>
              <h2>Saved analyses</h2>
              <p className="panel-subcopy">Pin snapshots locally, replay them, or re-run with fresh data.</p>
            </div>
            <span className="status-pill status-pill-muted">{notebook.length} saved</span>
          </div>
          {notebook.length ? (
            <ul className="notebook-list">
              {notebook.map((entry) => (
                <li key={entry.id}>
                  <div>
                    <strong>{entry.analysis.stock.ticker}</strong>
                    <span>{entry.analysis.stock.company_name}</span>
                    <span className="notebook-meta">
                      {entry.analysis.decision?.decision ?? entry.analysis.recommendation} •{" "}
                      {new Date(entry.created_at).toLocaleString()}
                    </span>
                  </div>
                  <div className="notebook-actions">
                    <button type="button" className="ghost-button" onClick={() => restoreNotebookEntry(entry)}>
                      View snapshot
                    </button>
                    <button type="button" className="ghost-button" onClick={() => void submitQuery(entry.analysis.query)}>
                      Re-run live
                    </button>
                    <button type="button" className="ghost-button ghost-danger" onClick={() => removeNotebookEntry(entry.id)}>
                      Remove
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <article className="detail-card placeholder-card">
              <p>Pin any completed analysis to keep a local, offline snapshot you can replay or export.</p>
            </article>
          )}
        </article>
      </section>
    </div>
  );
}
