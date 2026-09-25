import React, { useState, useEffect } from "react";
import { X, Upload, Download, Trash2, CheckCircle2, AlertCircle, Loader2, Search, RefreshCw, ArrowUpCircle, Check } from "lucide-react";
import { api, Extension, PopularExtension, WebStoreSearchResult, DownloadProgress, ExtensionUpdateInfo, ApiError } from "../lib/api";

function CircularProgress({
  percent,
  size = 30,
  strokeWidth = 3,
}: {
  percent: number;
  size?: number;
  strokeWidth?: number;
}) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.max(0, Math.min(100, percent));
  const offset = circumference - (clamped / 100) * circumference;

  return (
    <div className="relative flex items-center justify-center shrink-0" style={{ width: size, height: size }}>
      <svg className="transform -rotate-90" width={size} height={size}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="currentColor"
          strokeWidth={strokeWidth}
          fill="transparent"
          className="text-gray-700"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="currentColor"
          strokeWidth={strokeWidth}
          fill="transparent"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          className="text-indigo-400 transition-all duration-200 ease-in-out"
        />
      </svg>
      <span className="absolute text-[8px] font-bold text-indigo-300">
        {clamped}%
      </span>
    </div>
  );
}

interface ExtensionManagerModalProps {
  isOpen: boolean;
  onClose: () => void;
  onExtensionsChanged?: () => void;
}

export function ExtensionManagerModal({
  isOpen,
  onClose,
  onExtensionsChanged,
}: ExtensionManagerModalProps) {
  const [browserType, setBrowserType] = useState<"cloakbrowser" | "camoufox">("cloakbrowser");
  const [activeTab, setActiveTab] = useState<"webstore" | "popular" | "upload">("webstore");
  const [extensions, setExtensions] = useState<Extension[]>([]);
  const [popular, setPopular] = useState<PopularExtension[]>([]);
  const [searchResults, setSearchResults] = useState<WebStoreSearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [searching, setSearching] = useState(false);
  const [installingId, setInstallingId] = useState<string | null>(null);
  const [installingName, setInstallingName] = useState<string | null>(null);
  const [downloadProgress, setDownloadProgress] = useState<DownloadProgress | null>(null);
  const [webstoreInput, setWebstoreInput] = useState("");
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [checkingUpdates, setCheckingUpdates] = useState(false);
  const [updateMap, setUpdateMap] = useState<Record<string, ExtensionUpdateInfo>>({});

  const fetchExtensions = async () => {
    try {
      setLoading(true);
      const list = await api.listExtensions(browserType);
      setExtensions(list);
    } catch (err) {
      console.error("Failed to load extensions:", err);
    } finally {
      setLoading(false);
    }
  };

  const fetchPopular = async () => {
    try {
      const list = await api.getPopularExtensions();
      setPopular(list);
    } catch (err) {
      console.error("Failed to load popular extensions:", err);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchExtensions();
      fetchPopular();
      setFeedback(null);
    }
  }, [isOpen, browserType]);

  if (!isOpen) return null;

  const handleInstallFromWebStore = async (idOrUrl?: string, extName?: string) => {
    const target = (idOrUrl || webstoreInput).trim();
    if (!target) return;

    let displayName = extName;
    if (!displayName) {
      const foundPop = popular.find((p) => p.id === target || target.includes(p.id));
      if (foundPop) displayName = foundPop.name;
      const foundSearch = searchResults.find((s) => s.id === target || target.includes(s.id));
      if (foundSearch) displayName = foundSearch.name;
    }

    setActionLoading(true);
    setInstallingId(target);
    setInstallingName(displayName || null);
    setFeedback(null);
    setDownloadProgress({
      stage: "connecting",
      message: "正在连接 Chrome 应用商店...",
      percent: 0,
    });

    try {
      const installed = await api.installFromWebStoreStream(target, (progress) => {
        setDownloadProgress(progress);
      }, browserType);
      setFeedback({ type: "success", text: `成功安装扩展 "${installed.name}"！` });
      if (!idOrUrl) setWebstoreInput("");
      await fetchExtensions();
      onExtensionsChanged?.();
    } catch (err: any) {
      const msg = err?.message || (err instanceof ApiError ? err.message : "Failed to install from Web Store");
      setFeedback({ type: "error", text: msg });
    } finally {
      setActionLoading(false);
      setInstallingId(null);
      setInstallingName(null);
      setDownloadProgress(null);
    }
  };

  const handleSearchOrInstall = async () => {
    const target = webstoreInput.trim();
    if (!target) return;

    // Check if it looks like a direct 32-char ID or Web Store URL
    const isDirectId = /^[a-p]{32}$/i.test(target);
    const isUrl = target.includes("chromewebstore.google.com");

    if (isDirectId || isUrl) {
      handleInstallFromWebStore(target);
      return;
    }

    // Keyword search
    setSearching(true);
    setFeedback(null);
    try {
      const results = await api.searchWebStore(target);
      setSearchResults(results);
      if (results.length === 0) {
        setFeedback({
          type: "error",
          text: `No extensions found for "${target}". Try another keyword or paste direct ID/URL.`,
        });
      }
    } catch (err: any) {
      const msg = err?.message || (err instanceof ApiError ? err.message : "Failed to search Chrome Web Store");
      setFeedback({ type: "error", text: msg });
    } finally {
      setSearching(false);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setActionLoading(true);
    setFeedback(null);
    try {
      const installed = await api.uploadExtension(file, browserType);
      setFeedback({ type: "success", text: `Successfully installed "${installed.name}"!` });
      e.target.value = "";
      await fetchExtensions();
      onExtensionsChanged?.();
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Failed to upload extension";
      setFeedback({ type: "error", text: msg });
    } finally {
      setActionLoading(false);
    }
  };

  const handleDelete = async (extId: string, name: string) => {
    if (!confirm(`Are you sure you want to remove extension "${name}"?`)) return;

    setActionLoading(true);
    setFeedback(null);
    try {
      await api.deleteExtension(extId);
      setFeedback({ type: "success", text: `Removed "${name}".` });
      await fetchExtensions();
      onExtensionsChanged?.();
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Failed to delete extension";
      setFeedback({ type: "error", text: msg });
    } finally {
      setActionLoading(false);
    }
  };

  const handleCheckUpdates = async () => {
    setCheckingUpdates(true);
    setFeedback(null);
    try {
      const res = await api.checkExtensionUpdates();
      setUpdateMap(res.updates);
      const availableCount = Object.values(res.updates).filter((u) => u.has_update).length;
      if (availableCount > 0) {
        setFeedback({
          type: "success",
          text: `检查完成：发现 ${availableCount} 个插件有可用新版本！`,
        });
      } else {
        setFeedback({
          type: "success",
          text: "检查完成：所有来自应用商店的插件均已是最新版本。",
        });
      }
    } catch (err: any) {
      const msg = err?.message || (err instanceof ApiError ? err.message : "检查更新失败");
      setFeedback({ type: "error", text: msg });
    } finally {
      setCheckingUpdates(false);
    }
  };

  const handleUpdateExtension = async (ext: Extension) => {
    const target = ext.webstore_id || ext.id;
    if (!target) return;
    await handleInstallFromWebStore(target, ext.name);
    setUpdateMap((prev) => {
      const next = { ...prev };
      const current = next[ext.id];
      if (current) {
        next[ext.id] = {
          has_update: false,
          status: "up_to_date",
          current_version: current.latest_version ?? ext.version,
          latest_version: current.latest_version ?? ext.version,
        };
      }
      return next;
    });
  };

  const handleUpdateAll = async () => {
    const updatable = extensions.filter((e) => updateMap[e.id]?.has_update);
    if (updatable.length === 0) return;
    for (const ext of updatable) {
      await handleUpdateExtension(ext);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="bg-gray-900 border border-gray-800 rounded-xl w-full max-w-2xl shadow-2xl flex flex-col max-h-[85vh] overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-800 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="h-8 w-8 rounded-lg bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400 font-bold">
              🧩
            </div>
            <div>
              <h2 className="text-base font-semibold text-white">Extension Store & Manager</h2>
              <p className="text-xs text-gray-400">Install extensions for your browser profiles</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white p-1 rounded-lg hover:bg-gray-800 transition"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Browser Type Tabs */}
        <div className="flex border-b border-gray-800/60">
          <button
            className={`flex-1 py-2 text-sm font-medium border-b-2 transition-colors ${
              browserType === "cloakbrowser"
                ? "border-indigo-500 text-white"
                : "border-transparent text-gray-500 hover:text-gray-300 hover:border-gray-700"
            }`}
            onClick={() => {
              setBrowserType("cloakbrowser");
              setActiveTab("webstore");
            }}
          >
            CloakBrowser (Chrome)
          </button>
          <button
            className={`flex-1 py-2 text-sm font-medium border-b-2 transition-colors ${
              browserType === "camoufox"
                ? "border-indigo-500 text-white"
                : "border-transparent text-gray-500 hover:text-gray-300 hover:border-gray-700"
            }`}
            onClick={() => {
              setBrowserType("camoufox");
              setActiveTab("upload"); // Camoufox doesn't support Chrome webstore
            }}
          >
            Camoufox (Firefox)
          </button>
        </div>

        {/* Feedback Alert */}
        {feedback && (
          <div
            className={`mx-6 mt-4 p-3 rounded-lg text-xs flex items-center gap-2 ${
              feedback.type === "success"
                ? "bg-emerald-950/40 text-emerald-300 border border-emerald-800/40"
                : "bg-red-950/40 text-red-300 border border-red-800/40"
            }`}
          >
            {feedback.type === "success" ? (
              <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
            ) : (
              <AlertCircle className="h-4 w-4 shrink-0 text-red-400" />
            )}
            <span className="flex-1">{feedback.text}</span>
          </div>
        )}

        {/* Installation Tabs */}
        <div className="px-6 pt-4 pb-2 border-b border-gray-800/60">
          <div className="flex gap-2 text-xs font-medium">
            {browserType === "cloakbrowser" && (
              <>
                <button
                  className={`px-3 py-1.5 rounded-md transition ${
                    activeTab === "webstore"
                      ? "bg-indigo-600 text-white"
                      : "text-gray-400 hover:text-gray-200 hover:bg-gray-800"
                  }`}
                  onClick={() => setActiveTab("webstore")}
                >
                  Web Store ID / URL
                </button>
                <button
                  className={`px-3 py-1.5 rounded-md transition ${
                    activeTab === "popular"
                      ? "bg-indigo-600 text-white"
                      : "text-gray-400 hover:text-gray-200 hover:bg-gray-800"
                  }`}
                  onClick={() => setActiveTab("popular")}
                >
                  Popular Extensions
                </button>
              </>
            )}
            <button
              className={`px-3 py-1.5 rounded-md transition ${
                activeTab === "upload"
                  ? "bg-indigo-600 text-white"
                  : "text-gray-400 hover:text-gray-200 hover:bg-gray-800"
              }`}
              onClick={() => setActiveTab("upload")}
            >
              Upload {browserType === "cloakbrowser" ? ".crx / .zip" : ".xpi / .zip"}
            </button>
          </div>

          <div className="mt-3 pb-2">
            {activeTab === "webstore" && (
              <div className="space-y-3">
                <div className="flex gap-2">
                  <div className="relative flex-1">
                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-500" />
                    <input
                      className="input w-full pl-8 text-xs"
                      value={webstoreInput}
                      onChange={(e) => setWebstoreInput(e.target.value)}
                      placeholder="Search Chrome Web Store by keyword, or enter 32-char ID / URL..."
                      disabled={actionLoading || searching}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") handleSearchOrInstall();
                      }}
                    />
                  </div>
                  <button
                    type="button"
                    className="btn-primary text-xs px-4 flex items-center gap-1.5 disabled:opacity-50"
                    onClick={() => handleSearchOrInstall()}
                    disabled={actionLoading || searching || !webstoreInput.trim()}
                  >
                    {searching || actionLoading ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Search className="h-3.5 w-3.5" />
                    )}
                    Search / Install
                  </button>
                </div>

                {/* Progress bar for Web Store downloads */}
                {actionLoading && downloadProgress && (
                  <div className="space-y-1.5 p-2.5 rounded-lg bg-indigo-950/40 border border-indigo-800/40">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-indigo-300 flex items-center gap-1.5 min-w-0 flex-1">
                        <Loader2 className="h-3.5 w-3.5 animate-spin text-indigo-400 shrink-0" />
                        {installingName ? (
                          <span className="font-semibold text-white truncate shrink-0 max-w-[150px]">
                            {installingName}:
                          </span>
                        ) : null}
                        <span className="truncate">{downloadProgress.message}</span>
                      </span>
                      <span className="text-indigo-400 font-mono text-[11px] shrink-0 font-medium ml-2">
                        {downloadProgress.percent}%
                      </span>
                    </div>
                    <div className="h-1.5 w-full bg-gray-800 rounded-full overflow-hidden">
                      <div
                        className="bg-indigo-500 h-full rounded-full transition-all duration-200 ease-out"
                        style={{ width: `${Math.max(0, Math.min(100, downloadProgress.percent))}%` }}
                      />
                    </div>
                  </div>
                )}

                {/* Search Results */}
                {searchResults.length > 0 && (
                  <div className="space-y-1.5 max-h-56 overflow-y-auto border border-gray-800/80 rounded-lg p-2 bg-gray-950/40">
                    <div className="text-[11px] text-gray-400 font-medium px-1 flex items-center justify-between">
                      <span>Search Results ({searchResults.length}):</span>
                      <button
                        type="button"
                        onClick={() => setSearchResults([])}
                        className="text-[10px] text-gray-500 hover:text-gray-300"
                      >
                        Clear
                      </button>
                    </div>
                    {searchResults.map((item) => {
                      const isInstalled = extensions.some(
                        (e) => e.webstore_id === item.id || e.name.toLowerCase() === item.name.toLowerCase()
                      );
                      const isThisInstalling = actionLoading && (installingId === item.id || installingId?.includes(item.id));

                      return (
                        <div
                          key={item.id}
                          className="p-2 rounded-lg border border-gray-800/60 bg-gray-900/60 flex items-center justify-between gap-2.5 hover:border-gray-700 transition"
                        >
                          <div className="flex items-center gap-2.5 min-w-0 flex-1">
                            {item.icon_url ? (
                              <img
                                src={item.icon_url}
                                alt={item.name}
                                className="h-7 w-7 rounded shrink-0 object-contain bg-gray-800/60 p-0.5"
                              />
                            ) : (
                              <div className="h-7 w-7 rounded shrink-0 bg-indigo-950/60 border border-indigo-800/40 flex items-center justify-center text-indigo-300 text-xs font-bold">
                                🧩
                              </div>
                            )}
                            <div className="min-w-0 flex-1">
                              <div className="text-xs font-semibold text-white truncate">{item.name}</div>
                              {item.description && (
                                <div className="text-[10px] text-gray-400 truncate">{item.description}</div>
                              )}
                            </div>
                          </div>
                          {isThisInstalling ? (
                            <div className="flex flex-col items-end gap-1 shrink-0 w-24">
                              <div className="flex justify-between w-full text-[10px] text-indigo-300">
                                <span className="truncate max-w-[50px]">{downloadProgress?.stage === "unpacking" ? "解压中" : "下载中"}</span>
                                <span className="font-mono font-bold">{downloadProgress?.percent ?? 0}%</span>
                              </div>
                              <div className="h-1.5 w-full bg-gray-800 rounded-full overflow-hidden">
                                <div
                                  className="bg-indigo-500 h-full rounded-full transition-all duration-200"
                                  style={{ width: `${Math.max(0, Math.min(100, downloadProgress?.percent ?? 0))}%` }}
                                />
                              </div>
                            </div>
                          ) : (
                            <button
                              type="button"
                              className={`text-xs px-2.5 py-1 rounded transition shrink-0 flex items-center gap-1 ${
                                isInstalled
                                  ? "bg-gray-800 text-gray-400 cursor-default"
                                  : "btn-secondary text-indigo-300 hover:text-white"
                              }`}
                              disabled={actionLoading || isInstalled}
                              onClick={() => handleInstallFromWebStore(item.id, item.name)}
                            >
                              {isInstalled ? (
                                "Installed"
                              ) : (
                                <>
                                  <Download className="h-3 w-3" />
                                  Install
                                </>
                              )}
                            </button>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}

            {activeTab === "popular" && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-48 overflow-y-auto pr-1">
                {popular.map((item) => {
                  const isInstalled = extensions.some(
                    (e) => e.webstore_id === item.id || e.name.toLowerCase().includes(item.name.toLowerCase())
                  );
                  const isThisInstalling = actionLoading && (installingId === item.id || installingId?.includes(item.id));
                  return (
                    <div
                      key={item.id}
                      className="p-2.5 rounded-lg border border-gray-800 bg-gray-800/40 flex items-center justify-between gap-2"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="text-xs font-semibold text-white truncate">{item.name}</div>
                        <div className="text-[11px] text-gray-400 truncate">{item.description}</div>
                      </div>
                      {isThisInstalling ? (
                        <div className="flex items-center gap-1.5 shrink-0">
                          <CircularProgress percent={downloadProgress?.percent ?? 0} />
                          {downloadProgress?.stage === "unpacking" && (
                            <span className="text-[10px] text-indigo-300 animate-pulse">解压中</span>
                          )}
                        </div>
                      ) : (
                        <button
                          type="button"
                          className={`text-xs px-2.5 py-1 rounded transition shrink-0 ${
                            isInstalled
                              ? "bg-gray-700/50 text-gray-400 cursor-default"
                              : "btn-secondary text-indigo-300 hover:text-white"
                          }`}
                          disabled={actionLoading || isInstalled}
                          onClick={() => handleInstallFromWebStore(item.id, item.name)}
                        >
                          {isInstalled ? "Installed" : "Install"}
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            )}

            {activeTab === "upload" && (
              <div className="border-2 border-dashed border-gray-700 rounded-lg p-4 text-center hover:border-gray-600 transition">
                <input
                  type="file"
                  id="ext-file-upload"
                  className="hidden"
                  accept={browserType === "cloakbrowser" ? ".crx,.zip" : ".xpi,.zip"}
                  onChange={handleFileUpload}
                  disabled={actionLoading}
                />
                <label
                  htmlFor="ext-file-upload"
                  className="cursor-pointer flex flex-col items-center justify-center gap-1.5 text-xs text-gray-300"
                >
                  <Upload className="h-5 w-5 text-indigo-400" />
                  <span>Click to browse and upload <code className="text-indigo-300">{browserType === "cloakbrowser" ? ".crx / .zip" : ".xpi / .zip"}</code></span>
                  <span className="text-[10px] text-gray-500">Unpacks automatically into persistent extension library</span>
                </label>
              </div>
            )}
          </div>
        </div>

        {/* Installed Extensions List */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
                Installed Extensions ({extensions.length})
              </h3>
              {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-gray-400" />}
            </div>

            {extensions.length > 0 && (
              <div className="flex items-center gap-2">
                {Object.values(updateMap).some((u) => u.has_update) && (
                  <button
                    type="button"
                    onClick={handleUpdateAll}
                    disabled={actionLoading || checkingUpdates}
                    className="px-2.5 py-1 rounded bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-xs flex items-center gap-1.5 transition disabled:opacity-50"
                  >
                    <ArrowUpCircle className="h-3.5 w-3.5" />
                    全部更新 ({Object.values(updateMap).filter((u) => u.has_update).length})
                  </button>
                )}
                <button
                  type="button"
                  onClick={handleCheckUpdates}
                  disabled={checkingUpdates || actionLoading}
                  className="btn-secondary text-xs px-2.5 py-1 flex items-center gap-1.5 disabled:opacity-50"
                  title="检查所有插件是否有新版本"
                >
                  <RefreshCw className={`h-3 w-3 ${checkingUpdates ? "animate-spin text-indigo-400" : ""}`} />
                  <span>{checkingUpdates ? "检查中..." : "检查更新"}</span>
                </button>
              </div>
            )}
          </div>

          {extensions.length === 0 && !loading ? (
            <div className="text-center py-8 text-gray-500 text-xs">
              No extensions installed yet. Use the tabs above to install from Chrome Web Store or upload a file.
            </div>
          ) : (
            <div className="space-y-2">
              {extensions.map((ext) => {
                const updateInfo = updateMap[ext.id];
                return (
                  <div
                    key={ext.id}
                    className="p-3 rounded-lg border border-gray-800 bg-gray-800/30 flex items-center justify-between gap-3 hover:border-gray-700 transition"
                  >
                    <div className="flex items-center gap-3 min-w-0 flex-1">
                      {ext.icon_url ? (
                        <img src={ext.icon_url} alt={ext.name} className="h-8 w-8 rounded shrink-0 object-contain bg-gray-900/50 p-1" />
                      ) : (
                        <div className="h-8 w-8 rounded shrink-0 bg-indigo-950/60 border border-indigo-800/40 flex items-center justify-center text-indigo-300 text-xs font-bold">
                          {ext.name.charAt(0).toUpperCase()}
                        </div>
                      )}
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-xs font-medium text-white truncate">{ext.name}</span>
                          <span className="text-[10px] text-gray-400 bg-gray-800 px-1.5 py-0.2 rounded border border-gray-700 font-mono">
                            v{ext.version}
                          </span>
                          {updateInfo?.has_update && (
                            <span className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-amber-950/80 border border-amber-700/60 text-amber-300 font-medium animate-pulse">
                              <ArrowUpCircle className="h-3 w-3" />
                              可更新至 v{updateInfo.latest_version}
                            </span>
                          )}
                          {updateInfo && !updateInfo.has_update && updateInfo.status === "up_to_date" && (
                            <span className="inline-flex items-center gap-0.5 text-[10px] px-1.5 py-0.2 rounded bg-emerald-950/50 border border-emerald-800/40 text-emerald-400">
                              <Check className="h-2.5 w-2.5" />
                              最新
                            </span>
                          )}
                          {ext.source === "upload" && (
                            <span className="text-[10px] text-gray-500 bg-gray-800/50 px-1.5 py-0.2 rounded">
                              本地上传
                            </span>
                          )}
                        </div>
                        <p className="text-[11px] text-gray-400 truncate max-w-md">
                          {ext.description || ext.path}
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                      {updateInfo?.has_update && (
                        <button
                          type="button"
                          onClick={() => handleUpdateExtension(ext)}
                          disabled={actionLoading}
                          className="px-2.5 py-1 rounded bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-xs flex items-center gap-1 transition disabled:opacity-50"
                          title={`更新 ${ext.name} 至 v${updateInfo.latest_version}`}
                        >
                          <ArrowUpCircle className="h-3.5 w-3.5" />
                          更新
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => handleDelete(ext.id, ext.name)}
                        disabled={actionLoading}
                        className="text-gray-500 hover:text-red-400 p-1.5 rounded hover:bg-gray-800 transition"
                        title="Delete extension"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-gray-800 flex justify-end bg-gray-950/40">
          <button type="button" className="btn-secondary text-xs px-4" onClick={onClose}>
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
