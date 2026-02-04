import {
  BarChart3,
  BookOpen,
  ChevronDown,
  ChevronRight,
  Clock,
  Copy,
  Download,
  Eye,
  EyeOff,
  Globe,
  Home,
  Key,
  LogOut,
  Menu,
  Moon,
  Plus,
  RefreshCw,
  Search,
  Send,
  Sun,
  Terminal,
  X,
  Zap,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { showToast } from "@/utils/toast";
import { authApi } from "@/api/auth";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { profileMenuItems } from "@/config/navigation";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/authStore";
import { useThemeStore } from "@/stores/themeStore";
import { JsonEditor } from "@/components/ui/json-editor";
import { WebSocketTesterPanel } from "@/components/playground/WebSocketTesterPanel";

interface Endpoint {
  name: string;
  path: string;
  method: "GET" | "POST" | "WS";
  body?: Record<string, unknown>;
  params?: Record<string, unknown>;
  description?: string;
}

interface EndpointsByCategory {
  [category: string]: Endpoint[];
}

interface OpenTab {
  id: string;
  endpoint: Endpoint;
  requestBody: string;
  modified: boolean;
}

async function fetchCSRFToken(): Promise<string> {
  const response = await fetch("/auth/csrf-token", {
    credentials: "include",
  });
  const data = await response.json();
  return data.csrf_token;
}

interface SyntaxToken {
  text: string;
  type: "key" | "string" | "number" | "boolean" | "null" | "plain";
}

function tokenizeJson(json: string): SyntaxToken[] {
  // For very large JSON, return as plain text for performance
  if (json.length > 100 * 1024) {
    return [{ text: json, type: "plain" }];
  }

  const tokens: SyntaxToken[] = [];
  const regex =
    /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g;
  let lastIndex = 0;
  let match = regex.exec(json);

  while (match !== null) {
    // Add plain text before this match
    if (match.index > lastIndex) {
      tokens.push({ text: json.slice(lastIndex, match.index), type: "plain" });
    }

    const text = match[0];
    let type: SyntaxToken["type"] = "number";

    if (/^"/.test(text)) {
      type = /:$/.test(text) ? "key" : "string";
    } else if (/true|false/.test(text)) {
      type = "boolean";
    } else if (/null/.test(text)) {
      type = "null";
    }

    tokens.push({ text, type });
    lastIndex = regex.lastIndex;
    match = regex.exec(json);
  }

  // Add remaining plain text
  if (lastIndex < json.length) {
    tokens.push({ text: json.slice(lastIndex), type: "plain" });
  }

  return tokens;
}

function getTokenClassName(type: SyntaxToken["type"]): string {
  switch (type) {
    case "key":
      return "text-sky-400";
    case "string":
      return "text-emerald-400";
    case "number":
      return "text-orange-400";
    case "boolean":
      return "text-purple-400";
    case "null":
      return "text-red-400";
    default:
      return "";
  }
}

function isValidApiUrl(url: string, method?: string): { valid: boolean; error?: string } {
  // Allow WebSocket URLs for WS method
  if (method === "WS" && (url.startsWith("ws://") || url.startsWith("wss://"))) {
    return { valid: true };
  }

  if (url.startsWith("/api/") || url.startsWith("/playground/")) {
    return { valid: true };
  }

  try {
    const parsed = new URL(url, window.location.origin);

    if (parsed.origin !== window.location.origin) {
      return { valid: false, error: "Only same-origin requests are allowed" };
    }

    if (
      !parsed.pathname.startsWith("/api/") &&
      !parsed.pathname.startsWith("/playground/")
    ) {
      return {
        valid: false,
        error: "Only /api/ and /playground/ endpoints are allowed",
      };
    }

    return { valid: true };
  } catch {
    return { valid: false, error: "Invalid URL format" };
  }
}

export default function Playground() {
  const navigate = useNavigate();
  // Theme store
  const { mode, appMode, toggleMode, toggleAppMode, isTogglingMode } =
    useThemeStore();
  const { user, logout } = useAuthStore();

  const handleLogout = async () => {
    try {
      await authApi.logout();
      logout();
      navigate("/login");
      showToast.success("Logged out successfully", 'analyzer');
    } catch {
      logout();
      navigate("/login");
    }
  };

  const [apiKey, setApiKey] = useState("");
  const [showApiKey, setShowApiKey] = useState(false);
  const [endpoints, setEndpoints] = useState<EndpointsByCategory>({});
  const [collapsedCategories, setCollapsedCategories] = useState<Set<string>>(
    new Set(['data', 'utilities', 'websocket']),
  );
  const [searchQuery, setSearchQuery] = useState("");

  // Tabs state
  const [openTabs, setOpenTabs] = useState<OpenTab[]>([]);
  const [activeTabId, setActiveTabId] = useState<string | null>(null);

  // Request state
  const [method, setMethod] = useState<"GET" | "POST" | "WS">("POST");
  const [url, setUrl] = useState("");
  const [requestBody, setRequestBody] = useState("");

  // Response state
  const [isLoading, setIsLoading] = useState(false);
  const [responseStatus, setResponseStatus] = useState<number | null>(null);
  const [responseTime, setResponseTime] = useState<number | null>(null);
  const [responseSize, setResponseSize] = useState<number | null>(null);
  const [responseData, setResponseData] = useState<string | null>(null);
  const [responseHeaders, setResponseHeaders] = useState<
    Record<string, string>
  >({});

  // Mobile sidebar
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);

  // Playground mode - REST API or WebSocket
  const [playgroundMode, setPlaygroundMode] = useState<"rest" | "websocket">("rest");
  const [wsInitialMessage, setWsInitialMessage] = useState<string>("");

  useEffect(() => {
    loadApiKey();
    loadEndpoints();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadApiKey = async () => {
    try {
      const response = await fetch("/playground/api-key", {
        credentials: "include",
      });
      if (response.ok) {
        const data = await response.json();
        setApiKey(data.api_key || "");
      }
    } catch {
      // Silently fail - API key may not exist yet
    }
  };

  const loadEndpoints = async () => {
    try {
      const response = await fetch("/playground/endpoints", {
        credentials: "include",
      });
      if (response.ok) {
        const data = await response.json();
        setEndpoints(data);
      }
    } catch {
      showToast.error("Failed to load endpoints", 'analyzer');
    }
  };

  const getDefaultBody = useCallback(
    (endpoint: Endpoint): string => {
      let body: Record<string, unknown> = {};
      if (endpoint.method === "GET" && endpoint.params) {
        body = { ...endpoint.params };
      } else if (endpoint.body) {
        body = { ...endpoint.body };
      }

      if (apiKey && !body.apikey) {
        body.apikey = apiKey;
      }

      return JSON.stringify(body, null, 2);
    },
    [apiKey],
  );

  const selectEndpoint = (endpoint: Endpoint) => {
    // Handle WebSocket endpoints - switch to WebSocket mode
    if (endpoint.method === "WS") {
      const body = endpoint.body ? JSON.stringify(endpoint.body, null, 2) : "";
      // Replace apikey placeholder with actual API key
      const bodyWithApiKey = apiKey ? body.replace(/"apikey":\s*""/, `"apikey": "${apiKey}"`) : body;
      setWsInitialMessage(bodyWithApiKey);
      setPlaygroundMode("websocket");
      return;
    }

    // Check if tab already exists (match by both path AND name for endpoints sharing same path)
    const existingTab = openTabs.find(
      (t) =>
        t.endpoint.path === endpoint.path && t.endpoint.name === endpoint.name,
    );

    if (existingTab) {
      setActiveTabId(existingTab.id);
      setMethod(existingTab.endpoint.method);
      setUrl(existingTab.endpoint.path);
      setRequestBody(existingTab.requestBody);
    } else {
      // Create new tab
      const newTab: OpenTab = {
        id: `${endpoint.name}-${Date.now()}`,
        endpoint,
        requestBody: getDefaultBody(endpoint),
        modified: false,
      };

      setOpenTabs((prev) => [...prev, newTab]);
      setActiveTabId(newTab.id);
      setMethod(endpoint.method);
      setUrl(endpoint.path);
      setRequestBody(newTab.requestBody);
    }

    // Clear response when switching
    setResponseData(null);
    setResponseStatus(null);
    setResponseTime(null);
    setResponseSize(null);
  };

  const closeTab = (tabId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    const tabIndex = openTabs.findIndex((t) => t.id === tabId);
    const newTabs = openTabs.filter((t) => t.id !== tabId);
    setOpenTabs(newTabs);

    if (activeTabId === tabId) {
      // Select adjacent tab or clear
      if (newTabs.length > 0) {
        const newIndex = Math.min(tabIndex, newTabs.length - 1);
        const newActiveTab = newTabs[newIndex];
        setActiveTabId(newActiveTab.id);
        setMethod(newActiveTab.endpoint.method);
        setUrl(newActiveTab.endpoint.path);
        setRequestBody(newActiveTab.requestBody);
      } else {
        setActiveTabId(null);
        setMethod("POST");
        setUrl("");
        setRequestBody("");
      }
    }
  };

  const switchTab = (tab: OpenTab) => {
    setActiveTabId(tab.id);
    setMethod(tab.endpoint.method);
    setUrl(tab.endpoint.path);
    setRequestBody(tab.requestBody);
    setResponseData(null);
    setResponseStatus(null);
  };

  const updateCurrentTabBody = (newBody: string) => {
    setRequestBody(newBody);
    if (activeTabId) {
      setOpenTabs((prev) =>
        prev.map((t) =>
          t.id === activeTabId
            ? {
                ...t,
                requestBody: newBody,
                modified: newBody !== getDefaultBody(t.endpoint),
              }
            : t,
        ),
      );
    }
  };

  const toggleCategory = (category: string) => {
    setCollapsedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(category)) {
        next.delete(category);
      } else {
        next.add(category);
      }
      return next;
    });
  };

  const prettifyBody = () => {
    try {
      const parsed = JSON.parse(requestBody);
      const prettified = JSON.stringify(parsed, null, 2);
      updateCurrentTabBody(prettified);
      showToast.success("JSON prettified", 'analyzer');
    } catch {
      showToast.error("Invalid JSON - cannot prettify", 'analyzer');
    }
  };

  const sendRequest = async () => {
    if (!url) {
      showToast.warning("Please select an endpoint", 'analyzer');
      return;
    }


    const validation = isValidApiUrl(url, method);
    if (!validation.valid) {
      showToast.error(validation.error || 'Validation error', 'analyzer');
      return;
    }

    setIsLoading(true);
    setResponseData(null);
    setResponseStatus(null);
    setResponseTime(null);
    setResponseSize(null);
    setResponseHeaders({});

    const startTime = Date.now();

    try {
      const options: RequestInit = {
        method,
        credentials: "include",
        headers: {
          Accept: "application/json",
        },
      };

      let fetchUrl = url;

      if (method === "GET") {
        if (requestBody.trim()) {
          try {
            const params = JSON.parse(requestBody);
            const urlObj = new URL(url, window.location.origin);
            Object.entries(params).forEach(([key, value]) => {
              if (value !== null && value !== undefined && value !== "") {
                urlObj.searchParams.append(key, String(value));
              }
            });
            fetchUrl = urlObj.toString();
          } catch {
            showToast.error("Invalid JSON for query parameters", 'analyzer');
            setIsLoading(false);
            return;
          }
        }
      } else {
        const csrfToken = await fetchCSRFToken();
        (options.headers as Record<string, string>)["Content-Type"] =
          "application/json";
        (options.headers as Record<string, string>)["X-CSRFToken"] = csrfToken;
        if (requestBody.trim()) {
          options.body = requestBody;
        }
      }

      const response = await fetch(fetchUrl, options);
      const elapsed = Date.now() - startTime;

      // Capture headers
      const headers: Record<string, string> = {};
      response.headers.forEach((value, key) => {
        headers[key] = value;
      });
      setResponseHeaders(headers);

      let data;
      const contentType = response.headers.get("content-type");
      if (contentType?.includes("application/json")) {
        data = await response.json();
      } else {
        data = { text: await response.text(), contentType };
      }

      const responseText = JSON.stringify(data, null, 2);
      setResponseStatus(response.status);
      setResponseTime(elapsed);
      setResponseSize(new Blob([responseText]).size);
      setResponseData(responseText);
    } catch (error) {
      const elapsed = Date.now() - startTime;
      setResponseStatus(0);
      setResponseTime(elapsed);
      setResponseData(
        JSON.stringify(
          { error: error instanceof Error ? error.message : "Unknown error" },
          null,
          2,
        ),
      );
    } finally {
      setIsLoading(false);
    }
  };

  const copyResponse = () => {
    if (responseData) {
      navigator.clipboard.writeText(responseData);
      showToast.success("Response copied!", 'clipboard');
    }
  };

  const copyApiKey = () => {
    if (apiKey) {
      navigator.clipboard.writeText(apiKey);
      showToast.success("API key copied!", 'clipboard');
    }
  };

  const handleModeToggle = async () => {
    const result = await toggleAppMode();
    if (result.success) {
      const newMode = useThemeStore.getState().appMode;
      showToast.success(
        `Switched to ${newMode === "live" ? "Live" : "Analyze"} mode`,
        'analyzer'
      );

      if (newMode === "analyzer") {
        setTimeout(() => {
          showToast.warning(
            "Analyzer (Sandbox) mode is for testing purposes only",
            'analyzer',
            { duration: 10000 },
          );
        }, 2000);
      }
    } else {
      showToast.error(result.message || "Failed to toggle mode", 'analyzer');
    }
  };

  const copyCurl = () => {
    if (!url) return;

    let curlUrl = url;

    if (method === "GET" && requestBody.trim()) {
      try {
        const params = JSON.parse(requestBody);
        const urlObj = new URL(url, window.location.origin);
        Object.entries(params).forEach(([key, value]) => {
          if (value !== null && value !== undefined && value !== "") {
            urlObj.searchParams.append(key, String(value));
          }
        });
        curlUrl = urlObj.toString();
      } catch {
        showToast.error("Invalid JSON for query parameters", 'analyzer');
        return;
      }
    }

    const absoluteUrl = new URL(curlUrl, window.location.origin).href;
    let curl = `curl -X ${method} "${absoluteUrl}"`;
    curl += ' \\\n  -H "Accept: application/json"';

    if (method !== "GET" && requestBody.trim()) {
      curl += ' \\\n  -H "Content-Type: application/json"';
      curl += ` \\\n  -d '${requestBody.replace(/'/g, "'\\''")}'`;
    }

    navigator.clipboard.writeText(curl);
    showToast.success("Copied as cURL", 'clipboard');
  };

  // Filter endpoints by search
  const filteredEndpoints = Object.entries(endpoints).reduce(
    (acc, [category, eps]) => {
      if (!searchQuery) {
        acc[category] = eps;
      } else {
        const filtered = eps.filter(
          (ep) =>
            ep.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
            ep.path.toLowerCase().includes(searchQuery.toLowerCase()),
        );
        if (filtered.length) acc[category] = filtered;
      }
      return acc;
    },
    {} as EndpointsByCategory,
  );

  const getStatusColor = (status: number | null) => {
    if (!status) return "text-muted-foreground";
    if (status >= 200 && status < 300)
      return "text-emerald-500 dark:text-emerald-400";
    if (status >= 400) return "text-red-500 dark:text-red-400";
    return "text-yellow-500 dark:text-yellow-400";
  };

  const getStatusBg = (status: number | null) => {
    if (!status) return "bg-muted/50";
    if (status >= 200 && status < 300) return "bg-emerald-500/10";
    if (status >= 400) return "bg-red-500/10";
    return "bg-yellow-500/10";
  };

  const formatSize = (bytes: number) => {
    if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)}KB`;
    return `${bytes}B`;
  };

  const activeTab = openTabs.find((t) => t.id === activeTabId);

  return (
    <div className="h-full flex flex-col bg-background text-foreground">
      {/* Top Header Bar */}
      <div className="h-12 border-b border-border flex items-center px-2 bg-card/50">
        {/* Left: Logo and Menu */}
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 text-muted-foreground hover:text-foreground hover:bg-accent"
            onClick={() => setIsSidebarOpen(!isSidebarOpen)}
          >
            <Menu className="h-4 w-4" />
          </Button>
          <div className="flex items-center gap-2 px-2">
            <img
              src="/images/android-chrome-192x192.png"
              alt="OpenAlgo"
              className="w-6 h-6"
            />
            <span className="font-semibold text-sm">openalgo</span>
          </div>
        </div>

        {/* Center: Tabs */}
        <div className="flex-1 flex items-center gap-1 px-4 overflow-x-auto">
          {openTabs.map((tab) => (
            <div
              key={tab.id}
              className={cn(
                "flex items-center gap-2 px-3 py-1.5 rounded-md text-xs cursor-pointer group",
                "hover:bg-accent",
                tab.id === activeTabId
                  ? "bg-accent text-foreground"
                  : "text-muted-foreground",
              )}
              onClick={() => switchTab(tab)}
            >
              <Badge
                variant="outline"
                className={cn(
                  "text-[9px] px-1 py-0 h-4 border-0 font-semibold",
                  tab.endpoint.method === "GET"
                    ? "bg-sky-500/20 text-sky-400"
                    : tab.endpoint.method === "WS"
                      ? "bg-purple-500/20 text-purple-400"
                      : "bg-emerald-500/20 text-emerald-400",
                )}
              >
                {tab.endpoint.method}
              </Badge>
              <span className="truncate max-w-[100px]">
                {tab.endpoint.name}
              </span>
              {tab.modified && (
                <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
              )}
              <button
                type="button"
                className="opacity-0 group-hover:opacity-100 hover:text-foreground p-0.5 -mr-1"
                onClick={(e) => closeTab(tab.id, e)}
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6 text-muted-foreground hover:text-foreground hover:bg-accent"
            onClick={() => {
              // Select first available endpoint
              const firstCat = Object.keys(endpoints)[0];
              if (firstCat && endpoints[firstCat]?.[0]) {
                selectEndpoint(endpoints[firstCat][0]);
              }
            }}
          >
            <Plus className="h-3.5 w-3.5" />
          </Button>
        </div>

        {/* Right: Actions */}
        <div className="flex items-center gap-2 px-2">
          {/* Playground Mode Toggle */}
          <div className="flex items-center gap-1 px-2 py-1 rounded-lg bg-secondary/50">
            <Button
              variant={playgroundMode === "rest" ? "default" : "ghost"}
              size="sm"
              className="h-6 px-2 text-xs"
              onClick={() => setPlaygroundMode("rest")}
            >
              REST API
            </Button>
            <Button
              variant={playgroundMode === "websocket" ? "default" : "ghost"}
              size="sm"
              className="h-6 px-2 text-xs"
              onClick={() => setPlaygroundMode("websocket")}
            >
              <Globe className="h-3 w-3 mr-1" />
              WebSocket
            </Button>
          </div>

          {/* Mode Badge */}
          <Badge
            variant={appMode === "live" ? "default" : "secondary"}
            className={cn(
              "text-xs",
              appMode === "analyzer" &&
                "bg-purple-500 hover:bg-purple-600 text-white",
            )}
          >
            <span className="hidden sm:inline">
              {appMode === "live" ? "Live Mode" : "Analyze Mode"}
            </span>
            <span className="sm:hidden">
              {appMode === "live" ? "Live" : "Analyze"}
            </span>
          </Badge>

          {/* Mode Toggle */}
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={handleModeToggle}
            disabled={isTogglingMode}
            title={`Switch to ${appMode === "live" ? "Analyze" : "Live"} mode`}
          >
            {isTogglingMode ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
            ) : appMode === "live" ? (
              <Zap className="h-4 w-4" />
            ) : (
              <BarChart3 className="h-4 w-4" />
            )}
          </Button>

          {/* Theme Toggle */}
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={toggleMode}
            disabled={appMode !== "live"}
            title={
              mode === "light" ? "Switch to dark mode" : "Switch to light mode"
            }
          >
            {mode === "light" ? (
              <Sun className="h-4 w-4" />
            ) : (
              <Moon className="h-4 w-4" />
            )}
          </Button>

          <Button variant="ghost" size="sm" className="h-7 text-xs" asChild>
            <Link to="/dashboard">
              <Home className="h-3.5 w-3.5 mr-1.5" />
              Dashboard
            </Link>
          </Button>

          {/* Profile Dropdown */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 rounded-full bg-primary text-primary-foreground"
              >
                <span className="text-sm font-medium">
                  {user?.username?.[0]?.toUpperCase() || "O"}
                </span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              {profileMenuItems.map((item) => (
                <DropdownMenuItem
                  key={item.href}
                  onSelect={() => navigate(item.href)}
                  className="cursor-pointer"
                >
                  <item.icon className="h-4 w-4 mr-2" />
                  {item.label}
                </DropdownMenuItem>
              ))}
              <DropdownMenuItem asChild>
                <a
                  href="https://docs.openalgo.in"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2"
                >
                  <BookOpen className="h-4 w-4" />
                  Docs
                </a>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={handleLogout}
                className="text-destructive focus:text-destructive"
              >
                <LogOut className="h-4 w-4 mr-2" />
                Logout
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        {playgroundMode === "websocket" ? (
          /* WebSocket Mode */
          <WebSocketTesterPanel apiKey={apiKey} initialMessage={wsInitialMessage} />
        ) : (
          <>
        {/* Sidebar */}
        <div
          className={cn(
            "w-56 border-r border-border bg-card/30 flex flex-col overflow-hidden",
            "transition-all duration-200",
            isSidebarOpen
              ? "translate-x-0"
              : "-translate-x-full absolute h-full z-50",
          )}
        >
          {/* Search */}
          <div className="p-2 border-b border-border shrink-0">
            <div className="relative">
              <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="search here"
                className="h-7 pl-8 text-xs bg-secondary/50 border-border text-foreground placeholder:text-muted-foreground"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>
          </div>

          {/* Endpoints List */}
          <div className="flex-1 overflow-y-auto min-h-0">
            <div className="p-2">
              {Object.entries(filteredEndpoints).map(([category, eps]) => (
                <div key={category} className="mb-2">
                  <button
                    type="button"
                    className="flex items-center gap-1.5 w-full px-2 py-1 rounded text-[11px] font-medium uppercase tracking-wider text-muted-foreground hover:text-foreground hover:bg-accent/50"
                    onClick={() => toggleCategory(category)}
                  >
                    {collapsedCategories.has(category) ? (
                      <ChevronRight className="h-3 w-3" />
                    ) : (
                      <ChevronDown className="h-3 w-3" />
                    )}
                    {category}
                  </button>

                  {!collapsedCategories.has(category) && (
                    <div className="mt-0.5 space-y-0.5">
                      {eps.map((endpoint, idx) => (
                        <button
                          type="button"
                          key={idx}
                          className={cn(
                            "w-full flex items-center gap-2 px-2 py-1 rounded text-left text-xs hover:bg-accent/50",
                            activeTab?.endpoint.path === endpoint.path &&
                              "bg-accent text-foreground",
                          )}
                          onClick={() => selectEndpoint(endpoint)}
                        >
                          <Badge
                            variant="outline"
                            className={cn(
                              "text-[9px] px-1 py-0 h-4 border-0 font-semibold shrink-0",
                              endpoint.method === "GET"
                                ? "bg-sky-500/20 text-sky-400"
                                : endpoint.method === "WS"
                                  ? "bg-purple-500/20 text-purple-400"
                                  : "bg-emerald-500/20 text-emerald-400",
                            )}
                          >
                            {endpoint.method}
                          </Badge>
                          <span className="truncate text-foreground/80">
                            {endpoint.name}
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* API Key Section */}
          <div className="p-2 border-t border-border shrink-0">
            <div className="flex items-center gap-2 px-2 py-1.5 rounded bg-secondary/50">
              <Key className="h-3 w-3 text-muted-foreground" />
              <Input
                type={showApiKey ? "text" : "password"}
                value={apiKey}
                readOnly
                className="flex-1 h-5 text-[10px] font-mono bg-transparent border-none p-0 text-muted-foreground"
                placeholder="No API key"
              />
              <Button
                variant="ghost"
                size="icon"
                className="h-5 w-5 text-muted-foreground hover:text-foreground"
                onClick={() => setShowApiKey(!showApiKey)}
              >
                {showApiKey ? (
                  <EyeOff className="h-3 w-3" />
                ) : (
                  <Eye className="h-3 w-3" />
                )}
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-5 w-5 text-muted-foreground hover:text-foreground"
                onClick={copyApiKey}
              >
                <Copy className="h-3 w-3" />
              </Button>
            </div>
          </div>
        </div>

        {/* Main Panels */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {activeTab ? (
            <>
              {/* URL Bar */}
              <div className="flex items-center gap-2 px-4 py-2 border-b border-border bg-card/30">
                <Badge
                  variant="outline"
                  className={cn(
                    "text-xs px-2 py-0.5 border-0 font-semibold",
                    method === "GET"
                      ? "bg-sky-500/20 text-sky-400"
                      : method === "WS"
                        ? "bg-purple-500/20 text-purple-400"
                        : "bg-emerald-500/20 text-emerald-400",
                  )}
                >
                  {method}
                </Badge>
                <div className="flex-1 flex items-center gap-1 px-3 py-1.5 rounded bg-secondary/50 font-mono text-sm">
                  {method === "WS" ? (
                    <span className="text-foreground">{url}</span>
                  ) : (
                    <>
                      <span className="text-muted-foreground">
                        http://127.0.0.1:5000
                      </span>
                      <span className="text-foreground">{url}</span>
                    </>
                  )}
                </div>
                <Button
                  size="sm"
                  className="h-8 px-4 bg-emerald-600 hover:bg-emerald-700 text-white"
                  onClick={sendRequest}
                  disabled={isLoading}
                >
                  {isLoading ? (
                    <RefreshCw className="h-4 w-4 animate-spin" />
                  ) : (
                    <>
                      <Send className="h-3.5 w-3.5 mr-1.5" />
                      Send
                    </>
                  )}
                </Button>
              </div>

              {/* Request/Response Panels */}
              <div className="flex-1 flex overflow-hidden">
                {/* Request Panel */}
                <div className="flex-1 flex flex-col border-r border-border min-w-0">
                  {/* Request Tabs */}
                  <Tabs
                    defaultValue="body"
                    className="flex-1 flex flex-col min-h-0"
                  >
                    <div className="flex items-center justify-between px-4 py-1.5 border-b border-border bg-card/30">
                      <TabsList className="h-7 bg-transparent p-0 gap-2">
                        <TabsTrigger
                          value="body"
                          className="h-6 px-2 text-xs data-[state=active]:bg-accent data-[state=active]:text-foreground text-muted-foreground"
                        >
                          Body
                        </TabsTrigger>
                        <TabsTrigger
                          value="headers"
                          className="h-6 px-2 text-xs data-[state=active]:bg-accent data-[state=active]:text-foreground text-muted-foreground"
                        >
                          Headers
                        </TabsTrigger>
                      </TabsList>
                      <div className="flex items-center gap-1">
                        <span className="text-[10px] text-muted-foreground mr-2">
                          JSON
                        </span>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 text-[10px] text-muted-foreground hover:text-foreground hover:bg-accent"
                          onClick={prettifyBody}
                        >
                          Prettify
                        </Button>
                      </div>
                    </div>

                    <TabsContent
                      value="body"
                      className="flex-1 m-0 overflow-hidden"
                    >
                      <div className="h-full flex bg-background">
                        <JsonEditor
                          value={requestBody}
                          onChange={updateCurrentTabBody}
                          placeholder='{"apikey": ""}'
                          className="flex-1 min-h-0"
                        />
                      </div>
                    </TabsContent>

                    <TabsContent
                      value="headers"
                      className="flex-1 m-0 p-4 overflow-auto bg-background"
                    >
                      <div className="text-xs font-mono space-y-2">
                        <div className="flex gap-2">
                          <span className="text-muted-foreground">
                            Content-Type:
                          </span>
                          <span className="text-foreground/80">
                            application/json
                          </span>
                        </div>
                        <div className="flex gap-2">
                          <span className="text-muted-foreground">Accept:</span>
                          <span className="text-foreground/80">
                            application/json
                          </span>
                        </div>
                      </div>
                    </TabsContent>
                  </Tabs>
                </div>

                {/* Response Panel */}
                <div className="flex-1 flex flex-col min-w-0">
                  {/* Response Header */}
                  <Tabs
                    defaultValue="response"
                    className="flex-1 flex flex-col min-h-0"
                  >
                    <div className="flex items-center justify-between px-4 py-1.5 border-b border-border bg-card/30">
                      <TabsList className="h-7 bg-transparent p-0 gap-2">
                        <TabsTrigger
                          value="response"
                          className="h-6 px-2 text-xs data-[state=active]:bg-accent data-[state=active]:text-foreground text-muted-foreground"
                        >
                          Response
                        </TabsTrigger>
                        <TabsTrigger
                          value="headers"
                          className="h-6 px-2 text-xs data-[state=active]:bg-accent data-[state=active]:text-foreground text-muted-foreground"
                        >
                          Headers
                        </TabsTrigger>
                      </TabsList>
                      <div className="flex items-center gap-3 text-xs font-mono">
                        {responseStatus !== null && (
                          <span
                            className={cn(
                              "px-2 py-0.5 rounded",
                              getStatusBg(responseStatus),
                              getStatusColor(responseStatus),
                            )}
                          >
                            {responseStatus}{" "}
                            {responseStatus >= 200 && responseStatus < 300
                              ? "OK"
                              : "Error"}
                          </span>
                        )}
                        {responseTime !== null && (
                          <span className="text-muted-foreground flex items-center gap-1">
                            <Clock className="h-3 w-3" />
                            {responseTime}ms
                          </span>
                        )}
                        {responseSize !== null && (
                          <span className="text-muted-foreground flex items-center gap-1">
                            <Download className="h-3 w-3" />
                            {formatSize(responseSize)}
                          </span>
                        )}
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 text-[10px] text-muted-foreground hover:text-foreground hover:bg-accent"
                          onClick={copyCurl}
                        >
                          <Terminal className="h-3 w-3 mr-1" />
                          cURL
                        </Button>
                        {responseData && (
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-6 w-6 text-muted-foreground hover:text-foreground"
                            onClick={copyResponse}
                          >
                            <Copy className="h-3 w-3" />
                          </Button>
                        )}
                      </div>
                    </div>

                    <TabsContent
                      value="response"
                      className="flex-1 m-0 overflow-hidden"
                    >
                      <div className="h-full flex bg-background">
                        {responseData ? (
                          <>
                            {/* Line Numbers */}
                            <div className="w-10 bg-card/50 text-muted-foreground/50 text-xs font-mono py-3 px-2 text-right select-none overflow-hidden border-r border-border">
                              {responseData.split("\n").map((_, i) => (
                                <div key={i} className="leading-5">
                                  {i + 1}
                                </div>
                              ))}
                            </div>
                            {/* Response Content */}
                            <ScrollArea className="flex-1 p-3">
                              <pre className="text-xs font-mono whitespace-pre-wrap break-words leading-5">
                                {tokenizeJson(responseData).map((token, i) => (
                                  <span
                                    key={i}
                                    className={getTokenClassName(token.type)}
                                  >
                                    {token.text}
                                  </span>
                                ))}
                              </pre>
                            </ScrollArea>
                          </>
                        ) : (
                          <div className="flex-1 flex flex-col items-center justify-center text-center">
                            {isLoading ? (
                              <RefreshCw className="h-8 w-8 text-muted-foreground/50 animate-spin" />
                            ) : (
                              <>
                                <Send className="h-10 w-10 text-muted-foreground/30 mb-3" />
                                <p className="text-muted-foreground text-sm">
                                  No response yet
                                </p>
                                <p className="text-muted-foreground/70 text-xs mt-1">
                                  Click Send to make a request
                                </p>
                              </>
                            )}
                          </div>
                        )}
                      </div>
                    </TabsContent>

                    <TabsContent
                      value="headers"
                      className="flex-1 m-0 p-4 overflow-auto bg-background"
                    >
                      {Object.keys(responseHeaders).length > 0 ? (
                        <div className="text-xs font-mono space-y-2">
                          {Object.entries(responseHeaders).map(
                            ([key, value]) => (
                              <div key={key} className="flex gap-2">
                                <span className="text-muted-foreground">
                                  {key}:
                                </span>
                                <span className="text-foreground/80 break-all">
                                  {value}
                                </span>
                              </div>
                            ),
                          )}
                        </div>
                      ) : (
                        <div className="text-xs text-muted-foreground">
                          No headers to display
                        </div>
                      )}
                    </TabsContent>
                  </Tabs>
                </div>
              </div>
            </>
          ) : (
            /* Empty State */
            <div className="flex-1 flex flex-col items-center justify-center text-center bg-background">
              <img
                src="/images/android-chrome-192x192.png"
                alt="OpenAlgo"
                className="w-16 h-16 mb-4"
              />
              <h2 className="text-lg font-semibold text-foreground/80 mb-2">
                API Playground [WS-TEST]
              </h2>
              <p className="text-muted-foreground text-sm mb-4">
                Select an endpoint from the sidebar to get started
              </p>
              {!apiKey && (
                <Button variant="outline" size="sm" asChild>
                  <Link to="/apikey">
                    <Key className="h-4 w-4 mr-2" />
                    Generate API Key
                  </Link>
                </Button>
              )}
            </div>
          )}
        </div>
          </>
        )}
      </div>
    </div>
  );
}
