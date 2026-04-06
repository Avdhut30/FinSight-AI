import { FormEvent, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Sparkline } from "./components/Sparkline";
import {
  analyzePortfolio,
  analyzeStockStream,
  createAlert,
  fetchAlerts,
  fetchCurrentUser,
  fetchSavedWatchlist,
  fetchUserHistory,
  fetchIndices,
  loginUser,
  healthCheck,
  registerUser,
  saveTickerToWatchlist
} from "./lib/api";
import type {
  AlertResponse,
  AnalyzeResponse,
  PortfolioAnalysisResponse,
  StockSnapshot,
  UserHistoryItem,
  UserProfile,
  WatchlistItem
} from "./types";

type ChatMessage = { id: string; role: "assistant" | "user"; content: string; analysis?: AnalyzeResponse };
type NotebookEntry = { id: string; created_at: string; analysis: AnalyzeResponse };
type AuthFieldErrors = { name?: string; email?: string; password?: string };
type Toast = { id: string; type: "success" | "error" | "info"; message: string };
type Tag = { id: string; label: string };

const TOKEN_STORAGE_KEY = "token";
const LEGACY_TOKEN_KEY = "finsight-auth-token";
const NOTEBOOK_STORAGE_KEY = "finsight-notebook";
const THEME_STORAGE_KEY = "finsight-theme";
const MIN_PASSWORD_LENGTH = 8;
const MIN_EMAIL_LENGTH = 5;
const quickPrompts = [
  "Should I buy Infosys now?",
  "Why did TCS move today?",
  "What does recent news suggest for HDFC Bank?",
  "What was the trend of SBIN over the last 6 months?"
];
const quickActions = [
  { id: "explain-move", label: "Explain today's move", template: (ticker: string) => `Explain today's move in ${ticker}. Focus on price drivers, news, and sentiment.` },
  { id: "bull-case", label: "Bull case", template: (ticker: string) => `Build the bullish case for ${ticker} with 3 catalysts and price targets.` },
  { id: "bear-case", label: "Bear case", template: (ticker: string) => `Build the bear case for ${ticker}. Highlight 3 key risks and downside scenarios.` },
  { id: "risk-check", label: "Risk check", template: (ticker: string) => `Give a risk checklist for ${ticker}: valuation, liquidity, governance, macro sensitivity.` }
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
const indexLabels: Record<string, string> = {
  "^NSEI": "NIFTY 50",
  "^BSESN": "SENSEX"
};
const chartPalette = ["#0ea5e9", "#16a34a", "#f97316", "#8b5cf6", "#ef4444", "#22d3ee"];
const inrFormatter = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 });

function getStoredToken() {
  return typeof window === "undefined"
    ? null
    : window.localStorage.getItem(TOKEN_STORAGE_KEY) ?? window.localStorage.getItem(LEGACY_TOKEN_KEY);
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
  const navigate = useNavigate();
  const location = useLocation();
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
  const [historyItems, setHistoryItems] = useState<UserHistoryItem[]>([]);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [streamingMessageId, setStreamingMessageId] = useState<string | null>(null);
  const [theme, setTheme] = useState<string>(() => (typeof window === "undefined" ? "light" : window.localStorage.getItem(THEME_STORAGE_KEY) ?? "light"));

  const [portfolioInput, setPortfolioInput] = useState("TCS, RELIANCE, INFY");
  const [portfolioResult, setPortfolioResult] = useState<PortfolioAnalysisResponse | null>(null);
  const [portfolioLoading, setPortfolioLoading] = useState(false);
  const [tags, setTags] = useState<Tag[]>([]);
  const [tagInput, setTagInput] = useState("");

  const [alerts, setAlerts] = useState<AlertResponse[]>([]);
  const [alertsLoading, setAlertsLoading] = useState(false);
  const [alertType, setAlertType] = useState<"price_above" | "price_below" | "percent_drop">("price_below");
  const [alertThreshold, setAlertThreshold] = useState("");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(true);
  const [indices, setIndices] = useState<StockSnapshot[]>([]);
  const [indicesLoading, setIndicesLoading] = useState(false);

  function pushStatus(message: string) {
    setStatusLog((current) => (current[current.length - 1] === message ? current : [...current, message].slice(-8)));
  }

  function pushToast(message: string, type: Toast["type"] = "info") {
    const id = `toast-${Date.now()}`;
    setToasts((current) => [...current, { id, type, message }]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id));
    }, 4200);
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
    pushToast(message, "error");
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

  function handleLogout() {
    setAuthToken(null);
    setAuthError(null);
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(TOKEN_STORAGE_KEY);
      window.localStorage.removeItem(LEGACY_TOKEN_KEY);
    }
    pushToast("Logged out", "info");
    navigate("/login", { replace: true });
  }

  function addTag() {
    const trimmed = tagInput.trim();
    if (!trimmed) return;
    const id = trimmed.toLowerCase().replace(/\s+/g, "-");
    if (tags.some((t) => t.id === id)) {
      setTagInput("");
      return;
    }
    const next = [...tags, { id, label: trimmed }];
    setTags(next);
    setTagInput("");
  }

  function removeTag(id: string) {
    setTags((current) => current.filter((tag) => tag.id !== id));
  }

  function copyShareLink() {
    if (!analysis || typeof navigator === "undefined") return;
    const payload = `${window.location.origin}/analysis/${analysis.analysis_id}`;
    navigator.clipboard.writeText(payload).then(() => pushToast("Share link copied", "success"));
  }

  function exportPDF() {
    if (!analysis) {
      pushToast("Run an analysis to export.", "info");
      return;
    }
    window.print();
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
    setIndicesLoading(true);
    fetchIndices()
      .then((data) => setIndices(data))
      .catch(() => pushToast("Could not load index data", "error"))
      .finally(() => setIndicesLoading(false));
  }, []);

  useEffect(() => {
    if (typeof document === "undefined") return;
    const next = theme === "light" ? "theme-light" : "theme-dark";
    document.body.classList.remove("theme-light", "theme-dark");
    document.body.classList.add(next);
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  }, [theme]);

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
    setHistoryItems(history.items);
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
        window.localStorage.removeItem(LEGACY_TOKEN_KEY);
      }
      return;
    }
    if (typeof window !== "undefined") {
      window.localStorage.setItem(TOKEN_STORAGE_KEY, authToken);
      window.localStorage.setItem(LEGACY_TOKEN_KEY, authToken);
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

  useEffect(() => {
    const onLanding = location.pathname === "/";
    if (authToken && user && (location.pathname === "/login" || onLanding)) {
      navigate("/dashboard", { replace: true });
      return;
    }
    if (!authToken && location.pathname === "/dashboard") {
      navigate("/login", { replace: true });
    }
  }, [authToken, user, location.pathname, navigate]);

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
    setStreamingMessageId(assistantMessageId);
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
            setStreamingMessageId(null);
          }
        },
        authToken
      );
      if (authToken) await loadWorkspace(authToken);
      pushToast("Analysis ready", "success");
      setQuery("");
    } catch (requestError) {
      if (isAuthError(requestError)) {
        handleAuthFailure();
      } else {
        setError(requestError instanceof Error ? requestError.message : "Analysis failed.");
        pushToast(requestError instanceof Error ? requestError.message : "Analysis failed.", "error");
      }
    } finally {
      setIsLoading(false);
      setStreamingMessageId(null);
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
      if (typeof window !== "undefined") {
        window.localStorage.setItem(TOKEN_STORAGE_KEY, response.token);
        window.localStorage.setItem(LEGACY_TOKEN_KEY, response.token);
      }
      setAuthPassword("");
      setError(null);
      pushToast(authMode === "register" ? "Account created. Redirecting to dashboard." : "Welcome back!", "success");
      if (typeof window !== "undefined") {
        window.location.href = "/dashboard";
      } else {
        navigate("/dashboard", { replace: true });
      }
    } catch (requestError) {
      if (isAuthError(requestError)) {
        handleAuthFailure();
      } else {
        setAuthError(requestError instanceof Error ? requestError.message : "Authentication failed.");
        pushToast(requestError instanceof Error ? requestError.message : "Authentication failed.", "error");
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
      pushToast("Portfolio analyzed", "success");
    } catch (requestError) {
      if (isAuthError(requestError)) {
        handleAuthFailure();
      } else {
        setError(requestError instanceof Error ? requestError.message : "Portfolio analysis failed.");
        pushToast(requestError instanceof Error ? requestError.message : "Portfolio analysis failed.", "error");
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
      pushToast("Saved to your watchlist", "success");
    } catch (requestError) {
      if (isAuthError(requestError)) {
        handleAuthFailure();
      } else {
        setError(requestError instanceof Error ? requestError.message : "Could not save the ticker.");
        pushToast(requestError instanceof Error ? requestError.message : "Could not save the ticker.", "error");
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
      pushToast("Alert created", "success");
    } catch (requestError) {
      if (isAuthError(requestError)) {
        handleAuthFailure();
      } else {
        setError(requestError instanceof Error ? requestError.message : "Could not create the alert.");
        pushToast(requestError instanceof Error ? requestError.message : "Could not create the alert.", "error");
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
      pushToast("Saved to notebook", "success");
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

  function runQuickAction(actionId: string) {
    if (!analysis) {
      pushToast("Run an analysis first.", "info");
      return;
    }
    const action = quickActions.find((item) => item.id === actionId);
    if (!action) return;
    const ticker = analysis.stock.ticker.replace(".NS", "").replace(".BO", "");
    const q = action.template(ticker);
    setQuery(q);
    void submitQuery(q);
  }

  async function copyLastAnswer() {
    if (!analysis || typeof navigator === "undefined") return;
    const payload = `${analysis.stock.ticker} â€” ${analysis.stock.company_name}\nDecision: ${analysis.decision?.decision ?? analysis.recommendation} (${analysis.decision?.confidence ?? Math.round(analysis.confidence * 100)}%)\n\n${analysis.answer}`;
    await navigator.clipboard.writeText(payload);
  }

  async function downloadLastAnswer() {
    if (!analysis || typeof document === "undefined") return;
    const payload = `${analysis.stock.ticker} â€” ${analysis.stock.company_name}\nDecision: ${analysis.decision?.decision ?? analysis.recommendation} (${analysis.decision?.confidence ?? Math.round(analysis.confidence * 100)}%)\n\n${analysis.answer}`;
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
  const streamingActive = Boolean(streamingMessageId);
  const showOverlay = isLoading || portfolioLoading || authBusy || authChecking;
  const isLandingPage = location.pathname === "/";
  const isLoginPage = location.pathname === "/login";

  const trendChartData = useMemo(() => {
    if (!analysis?.stock.price_history?.length) return [];
    return analysis.stock.price_history.map((point) => ({
      ...point,
      label: new Date(point.date).toLocaleDateString("en-IN", { month: "short", day: "numeric" })
    }));
  }, [analysis?.stock.price_history]);

  const portfolioChartData = useMemo(() => {
    if (!portfolioResult?.holdings?.length) return [];
    return portfolioResult.holdings.map((item) => ({
      name: item.ticker,
      value: Math.round((item.weight ?? 0) * 100)
    }));
  }, [portfolioResult]);

  function toggleTheme() {
    setTheme((current) => (current === "light" ? "dark" : "light"));
  }

  const overlay = showOverlay ? (
    <div className={`loading-overlay ${streamingActive ? "overlay-streaming" : ""}`}>
      <div className="spinner" aria-hidden />
      <div>
        <p className="overlay-title">{streamingActive ? "Streaming AI response..." : "Working..."}</p>
        <p className="overlay-sub">{streamStatus}</p>
        {statusLog.length ? (
          <ul className="overlay-steps">
            {statusLog.slice(-4).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  ) : null;

  const toastStack = (
    <div className="toast-stack">
      {toasts.map((toast) => (
        <div key={toast.id} className={`toast toast-${toast.type}`}>
          <span>{toast.message}</span>
          <button type="button" className="icon-button" onClick={() => setToasts((current) => current.filter((item) => item.id !== toast.id))}>
            x
          </button>
        </div>
      ))}
    </div>
  );

  if (!isAuthenticated && isLandingPage) {
    return (
      <>
        {overlay}
        {toastStack}
        <div className="landing-page">
          <header className="landing-hero">
            <div className="landing-hero-copy">
              <p className="hero-kicker">FinSight AI</p>
              <h1>Trading-grade AI for modern investors</h1>
              <p className="hero-copy">
                Live streaming analysis, price-aware decisions, and portfolio intelligence built for a startup-grade SaaS launch.
              </p>
              <div className="landing-cta-row">
                <button type="button" className="cta-primary" onClick={() => navigate("/login")}>
                  Start free
                </button>
                <button type="button" className="cta-ghost" onClick={() => navigate("/dashboard")}>
                  View dashboard
                </button>
              </div>
              <div className="landing-pills">
                <span className="pill">Streaming /analyze/stream</span>
                <span className="pill">Charts + alerts</span>
                <span className="pill">Save history</span>
              </div>
            </div>
            <div className="landing-hero-card">
              <div className="landing-card-head">
                <span className="status-dot status-ok" />
                Live AI trace
                <span className="chip">Realtime</span>
              </div>
              <div className="landing-card-body">
                <p className="muted">Analyzing TCS...</p>
                <div className="typing-line">
                  Resolving company and ticker <span className="cursor">|</span>
                </div>
                <div className="mini-metrics">
                  <div>
                    <small>Decision</small>
                    <strong>BUY</strong>
                  </div>
                  <div>
                    <small>Confidence</small>
                    <strong>87%</strong>
                  </div>
                  <div>
                    <small>Latency</small>
                    <strong>{lastLatencyMs ? `${lastLatencyMs} ms` : "~1s"}</strong>
                  </div>
                </div>
              </div>
            </div>
          </header>

          <div className="index-strip">
            {(indicesLoading || !indices.length) && (
              <div className="index-chip skeleton">Loading indices...</div>
            )}
            {!indicesLoading &&
              indices.map((item) => {
                const label = indexLabels[item.ticker] ?? item.ticker;
                return (
                  <div key={item.ticker} className="index-chip">
                    <div>
                      <strong>{label}</strong>
                      <span className="muted">{item.ticker}</span>
                    </div>
                    <div className="index-metrics">
                      <span className="price">{item.current_price?.toFixed(2) ?? "—"}</span>
                      <span className={`pct ${item.day_change_percent && item.day_change_percent >= 0 ? "up" : "down"}`}>
                        {formatSignedPercent(item.day_change_percent)}
                      </span>
                    </div>
                  </div>
                );
              })}
          </div>

          <section className="landing-section">
            <div className="section-head">
              <h2>Powerful Features</h2>
              <p>Production-ready SaaS surface with streaming AI, charts, and saved history.</p>
            </div>
            <div className="feature-grid">
              <div className="feature-card">
                <h3>Real-time Analysis</h3>
                <p>Get instant AI-powered stock insights.</p>
              </div>
              <div className="feature-card">
                <h3>Portfolio Insights</h3>
                <p>Track and optimize your investments.</p>
              </div>
              <div className="feature-card">
                <h3>Smart Alerts</h3>
                <p>Stay ahead with intelligent notifications.</p>
              </div>
              <div className="feature-card">
                <h3>History & Notebook</h3>
                <p>Save analyses, replay snapshots, and export.</p>
              </div>
            </div>
          </section>

          <section className="landing-section how-section">
            <div className="section-head">
              <h2>How it works</h2>
              <p>Three steps to a live trading assistant.</p>
            </div>
            <div className="how-grid">
              <article className="how-card">
                <span className="step">1</span>
                <h3>Sign up</h3>
                <p>Create your workspace and store the token locally.</p>
              </article>
              <article className="how-card">
                <span className="step">2</span>
                <h3>Analyze stocks</h3>
                <p>Use the streaming /analyze/stream endpoint to watch the agent type in real time.</p>
              </article>
              <article className="how-card">
                <span className="step">3</span>
                <h3>Get insights</h3>
                <p>View charts, reasoning, alerts, and save outcomes to history.</p>
              </article>
            </div>
          </section>

          <section className="landing-section pricing-section">
            <h2>Pricing</h2>
            <div className="pricing-grid">
              <div className="pricing-card">
                <h3>Free</h3>
                <p className="muted">Basic access</p>
                <button className="cta-primary" onClick={() => navigate("/login")}>
                  Get Started
                </button>
              </div>
              <div className="pricing-card pricing-card-accent">
                <h3>Pro</h3>
                <p>Advanced AI insights</p>
                <button className="cta-ghost" onClick={() => navigate("/login")}>
                  Upgrade
                </button>
              </div>
            </div>
          </section>

          <section className="landing-section preview-section">
            <div className="section-head">
              <h2>Dashboard preview</h2>
              <p>Sidebar layout, top bar status, charts, alerts, and saved history are ready out of the box.</p>
            </div>
            <div className="preview-grid">
              <div className="preview-card">
                <h4>Streaming output</h4>
                <p className="muted">“Analyzing...” typing effect shows deltas as they arrive.</p>
              </div>
              <div className="preview-card">
                <h4>Charts</h4>
                <p className="muted">Recharts line and pie visualizations for price and portfolio mix.</p>
              </div>
              <div className="preview-card">
                <h4>Saved history</h4>
                <p className="muted">Persisted analyses and watchlists tied to your auth token.</p>
              </div>
            </div>
          </section>

          <footer className="landing-footer">
            <div className="footer-left">
              <strong>FinSight AI</strong>
              <p className="muted">Built for investors who want realtime, explainable AI.</p>
            </div>
            <div className="footer-right">
              <a onClick={() => navigate("/login")}>Login</a>
              <a onClick={() => navigate("/dashboard")}>Dashboard</a>
              <a href="mailto:team@finsight.ai">Contact</a>
            </div>
          </footer>
        </div>
      </>
    );
  }

  if (!isAuthenticated && isLoginPage) {
    return (
      <>
        {overlay}
        {toastStack}
        <div className="auth-shell">
          <div className="auth-hero-card">
            <div className="auth-hero-top">
              <p className="hero-kicker">FinSight AI</p>
              <span className="badge glow">Private Beta</span>
            </div>
            <h1 className="hero-title">Secure Research Workspace</h1>
            <p className="hero-copy">
              Log in to unlock streaming analysis, portfolio diagnostics, alerts, and a personal notebook. New users should create an account first—then you’ll be redirected into the full console.
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
      </>
    );
  }

  if (!isAuthenticated) {
    return (
      <>
        {overlay}
        {toastStack}
      </>
    );
  }

  return (
    <>
      {overlay}
      {toastStack}
      <div className={`dashboard-shell ${sidebarCollapsed ? "collapsed" : "open"}`}>
        <aside className={`dashboard-sidebar ${sidebarCollapsed ? "collapsed" : "open"}`}>
          <div className="sidebar-logo">
            <button
              type="button"
              className="icon-button sidebar-toggle"
              onClick={() => setSidebarCollapsed((v) => !v)}
              aria-label="Toggle menu"
            >
              ☰
            </button>
            <span className="sidebar-brand">FinSight</span>
          </div>
          <ul className="sidebar-links">
            <li className="active"><span className="label">Dashboard</span></li>
            <li><span className="label">Analyze</span></li>
            <li><span className="label">Portfolio</span></li>
            <li><span className="label">Alerts</span></li>
            <li><span className="label">Settings</span></li>
          </ul>
          <div className="sidebar-foot">
            <div className="status-row">
              <span className={`status-dot status-${health}`} />
              <span className="muted">Backend {health === "ok" ? "online" : health}</span>
            </div>
            <p className="muted">Triggered alerts: {triggeredAlerts}</p>
          </div>
        </aside>
        <div className="dashboard-main">
          <header className="dashboard-topbar">
            <div>
              <p className="eyebrow">Welcome back</p>
              <h2>Command center</h2>
              <p className="panel-subcopy">Streaming AI output, charts, alerts, and saved history in one view.</p>
            </div>
            <div className="topbar-actions">
              <button type="button" className="ghost-button" onClick={toggleTheme}>
                {theme === "light" ? "Dark mode" : "Light mode"}
              </button>
              <button type="button" className="ghost-button" onClick={() => void pingHealth()}>
                Check status
              </button>
              <button type="button" className="ghost-button" onClick={() => copyShareLink()} disabled={!analysis}>
                Copy link
              </button>
              <button type="button" className="ghost-button" onClick={handleLogout}>
                Logout
              </button>
              <div className="nav-user">
                <div className="nav-avatar">{user?.name?.charAt(0) ?? "F"}</div>
                <div>
                  <strong>{user?.name ?? "Authenticated"}</strong>
                  <p>{user?.email ?? "user@finsight.ai"}</p>
                </div>
              </div>
            </div>
          </header>
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
          <button type="button" className="ghost-button" onClick={() => copyShareLink()} disabled={!analysis}>
            Copy share link
          </button>
          <button type="button" className="ghost-button" onClick={() => exportPDF()} disabled={!analysis}>
            Export PDF
          </button>
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
          <div className="hero-badge-chip">
            <span className="dot-new" />
            <span>NEW</span>
            <span>AI Research Console</span>
          </div>
          <p className="hero-kicker">Stock Research Workspace</p>
          <div className="hero-title-row">
            <h1 className="hero-title">Intelligence That Drives Better Decisions</h1>
          </div>
          <p className="hero-copy">
            Connects research, streaming AI, and portfolio risk into one live command center with instant alerts and memory.
          </p>
          <div className="hero-ctas">
            <button type="button" className="cta-primary" onClick={() => navigate("/dashboard")}>
              Get started
            </button>
            <button type="button" className="cta-ghost" onClick={() => navigate("/login")}>
              Login
            </button>
          </div>
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
          <div className="action-grid">
            {quickActions.map((action) => (
              <button
                key={action.id}
                type="button"
                className="action-chip"
                onClick={() => runQuickAction(action.id)}
                disabled={isLoading || !analysis}
                title="Runs against the active ticker"
              >
                {action.label}
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
                  <p className={message.id === streamingMessageId ? "streaming-line" : ""}>
                    {message.content}
                    {message.id === streamingMessageId ? <span className="cursor">|</span> : null}
                  </p>
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
              <button type="submit" className="primary-button" disabled={isLoading || !query.trim()}>
                {isLoading ? "Analyzing..." : "Run analysis"}
              </button>
            </div>
          </form>
          <div className="tag-bar">
            <div className="tag-input-wrap">
              <input
                value={tagInput}
                onChange={(event) => setTagInput(event.target.value)}
                placeholder="Add a tag (e.g., earnings, breakout)"
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    addTag();
                  }
                }}
              />
              <button type="button" className="ghost-button" onClick={() => addTag()}>
                Add tag
              </button>
            </div>
            <div className="tag-list">
              {tags.map((tag) => (
                <span key={tag.id} className="tag-chip">
                  {tag.label}
                  <button type="button" className="icon-button" onClick={() => removeTag(tag.id)}>
                    x
                  </button>
                </span>
              ))}
            </div>
          </div>
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

              <article className="detail-card chart-card">
                <div className="detail-card-header">
                  <h3>Trend chart</h3>
                  <span>{trendChartData.length ? `${trendChartData.length} points` : "Awaiting data"}</span>
                </div>
                {trendChartData.length ? (
                  <div className="chart-wrapper">
                    <ResponsiveContainer width="100%" height={260}>
                      <LineChart data={trendChartData} margin={{ top: 12, right: 12, left: 0, bottom: 6 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                        <XAxis dataKey="label" tick={{ fill: "#9ca3af", fontSize: 11 }} />
                        <YAxis tick={{ fill: "#9ca3af", fontSize: 11 }} domain={["auto", "auto"]} />
                        <Tooltip />
                        <Line type="monotone" dataKey="close" stroke="#0ea5e9" strokeWidth={2.2} dot={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <p className="placeholder">Run an analysis to render the live chart.</p>
                )}
              </article>
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
              <button type="button" className="secondary-button" onClick={handleLogout}>
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
                  <h3>Past analyses</h3>
                </div>
                <ul className="detail-list compact-list history-list">
                  {historyItems.length ? (
                    historyItems.slice(0, 6).map((item) => (
                      <li key={item.analysis_id}>
                        <div className="history-row">
                          <div>
                            <strong>{item.ticker}</strong> {item.recommendation.toUpperCase()} â€¢ {Math.round(item.confidence * 100)}%
                            <span className="history-date">{new Date(item.created_at).toLocaleString()}</span>
                          </div>
                          <button type="button" className="ghost-button" onClick={() => void submitQuery(item.query)}>
                            Re-run
                          </button>
                        </div>
                      </li>
                    ))
                  ) : (
                    <li>Run an authenticated analysis to build memory.</li>
                  )}
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
              <button type="submit" className="primary-button" disabled={!authEmail || !authPassword || (authMode === "register" && !authName)}>
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
            <button type="button" className="primary-button" onClick={() => void handlePortfolioAnalyze()} disabled={portfolioLoading || !portfolioInput.trim()}>
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
              {portfolioChartData.length ? (
                <article className="detail-card chart-card">
                  <div className="detail-card-header">
                    <h3>Portfolio mix</h3>
                    <span>{portfolioChartData.length} holdings</span>
                  </div>
                  <div className="chart-wrapper pie-wrapper">
                    <ResponsiveContainer width="100%" height={240}>
                      <PieChart>
                        <Pie data={portfolioChartData} dataKey="value" nameKey="name" innerRadius={60} outerRadius={90} paddingAngle={3}>
                          {portfolioChartData.map((entry, index) => (
                            <Cell key={entry.name} fill={chartPalette[index % chartPalette.length]} />
                          ))}
                        </Pie>
                        <Legend />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                </article>
              ) : null}
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
                <button type="button" className="primary-button" onClick={() => void handleCreateAlert()} disabled={alertsLoading || !alertThreshold.trim()}>
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
                      {entry.analysis.decision?.decision ?? entry.analysis.recommendation} â€¢{" "}
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
    </div>
  </div>
    </>
  );
}







