import { useState, useEffect } from "react";
import {
  X,
  Cpu,
  Download,
  Trash2,
  CheckCircle2,
  AlertCircle,
  AlertTriangle,
  Loader2,
  RefreshCw,
  HardDrive,
  RotateCcw,
} from "lucide-react";
import {
  api,
  KernelItem,
  KernelListResponse,
  KernelDownloadProgress,
  ApiError,
} from "../lib/api";

interface KernelManagerModalProps {
  isOpen: boolean;
  onClose: () => void;
  onKernelChanged?: () => void;
}

export function KernelManagerModal({
  isOpen,
  onClose,
  onKernelChanged,
}: KernelManagerModalProps) {
  const [loading, setLoading] = useState(false);
  const [kernelData, setKernelData] = useState<KernelListResponse | null>(null);
  const [downloadingVersion, setDownloadingVersion] = useState<string | null>(null);
  const [downloadProgress, setDownloadProgress] = useState<KernelDownloadProgress | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [feedback, setFeedback] = useState<{
    type: "success" | "error" | "info";
    text: string;
  } | null>(null);

  const fetchKernels = async () => {
    try {
      setLoading(true);
      const data = await api.listKernels();
      setKernelData(data);
    } catch (err) {
      console.error("Failed to load kernels:", err);
      const msg = err instanceof ApiError ? err.message : "获取内核列表失败";
      setFeedback({ type: "error", text: msg });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    if (isOpen) {
      window.addEventListener("keydown", handleKeyDown);
      fetchKernels();
      setFeedback(null);
    } else {
      // Clear progress when modal is closed (unless downloading)
      if (!downloadingVersion) {
        setDownloadProgress(null);
      }
    }
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  const handleDownload = async (kernel: KernelItem) => {
    if (downloadingVersion) return;

    setDownloadingVersion(kernel.version);
    setDownloadProgress({
      stage: "connecting",
      message: `正在连接下载服务器 (${kernel.version})...`,
      percent: 0,
    });
    setFeedback(null);

    try {
      await api.downloadKernelStream(kernel.version, kernel.tier, (prog) => {
        setDownloadProgress(prog);
      });

      setFeedback({
        type: "success",
        text: `内核 ${kernel.name} (${kernel.version}) 安装成功！`,
      });
      await fetchKernels();
      onKernelChanged?.();
    } catch (err) {
      console.error("Kernel download failed:", err);
      const msg = err instanceof Error ? err.message : "内核下载失败";
      setFeedback({ type: "error", text: msg });
    } finally {
      setDownloadingVersion(null);
    }
  };

  const handleDelete = async (kernel: KernelItem) => {
    const confirmMsg = kernel.is_active
      ? `警告：内核 ${kernel.version} 当前正在使用中。删除后可能需要重新下载才能启动浏览器。确定删除吗？`
      : `确定要删除内核 ${kernel.name} (${kernel.version}) 吗？`;

    if (!window.confirm(confirmMsg)) return;

    try {
      setActionLoading(true);
      const res = await api.deleteKernel(kernel.version);
      setFeedback({
        type: "success",
        text: res.message || `内核 ${kernel.version} 已删除`,
      });
      await fetchKernels();
      onKernelChanged?.();
    } catch (err) {
      console.error("Failed to delete kernel:", err);
      const msg = err instanceof ApiError ? err.message : "删除内核失败";
      setFeedback({ type: "error", text: msg });
    } finally {
      setActionLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="bg-gray-900 border border-gray-800 rounded-xl w-full max-w-2xl shadow-2xl flex flex-col max-h-[85vh] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-800 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="h-8 w-8 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400">
              <Cpu className="h-4 w-4" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-white">
                Chromium 内核管理 / Kernel Manager
              </h2>
              <p className="text-xs text-gray-400">
                管理 CloakBrowser 的定制 Chromium 内核（支持断点续传与多版本管理）
              </p>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={fetchKernels}
              disabled={loading || !!downloadingVersion}
              className="text-gray-400 hover:text-white p-1.5 rounded-lg hover:bg-gray-800 transition disabled:opacity-50"
              title="刷新内核列表"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            </button>
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-white p-1.5 rounded-lg hover:bg-gray-800 transition"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        {/* Platform & Status Ribbon */}
        {kernelData && (
          <div className="px-6 py-2.5 bg-gray-800/40 border-b border-gray-800/60 flex items-center justify-between text-xs">
            <div className="flex items-center gap-4 text-gray-400">
              <span>
                平台架构: <strong className="text-gray-200 font-mono">{kernelData.current_platform}</strong>
              </span>
              <span>
                当前授权:{" "}
                <span
                  className={`px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase ${
                    kernelData.current_tier === "pro"
                      ? "bg-purple-950/60 text-purple-300 border border-purple-800/50"
                      : "bg-blue-950/60 text-blue-300 border border-blue-800/50"
                  }`}
                >
                  {kernelData.current_tier}
                </span>
              </span>
            </div>
            <div>
              {kernelData.installed ? (
                <span className="inline-flex items-center gap-1.5 text-emerald-400 font-medium">
                  <CheckCircle2 className="h-3.5 w-3.5" /> 内核就绪
                  {kernelData.active_version && (
                    <span className="text-gray-400 text-[11px]">({kernelData.active_version})</span>
                  )}
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 text-amber-400 font-medium">
                  <AlertTriangle className="h-3.5 w-3.5" /> 未安装内核
                </span>
              )}
            </div>
          </div>
        )}

        {/* Feedback Alert */}
        {feedback && (
          <div
            className={`mx-6 mt-4 p-3 rounded-lg text-xs flex items-center gap-2 ${
              feedback.type === "success"
                ? "bg-emerald-950/40 text-emerald-300 border border-emerald-800/40"
                : feedback.type === "info"
                ? "bg-blue-950/40 text-blue-300 border border-blue-800/40"
                : "bg-red-950/40 text-red-300 border border-red-800/40"
            }`}
          >
            {feedback.type === "success" ? (
              <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
            ) : feedback.type === "info" ? (
              <AlertCircle className="h-4 w-4 shrink-0 text-blue-400" />
            ) : (
              <AlertCircle className="h-4 w-4 shrink-0 text-red-400" />
            )}
            <span className="flex-1">{feedback.text}</span>
          </div>
        )}

        {/* Active Download Progress Box */}
        {downloadingVersion && downloadProgress && (
          <div className="mx-6 mt-4 p-4 rounded-xl bg-blue-950/20 border border-blue-800/40 flex flex-col gap-2.5">
            <div className="flex items-center justify-between text-xs">
              <div className="flex items-center gap-2">
                <Loader2 className="h-4 w-4 text-blue-400 animate-spin shrink-0" />
                <span className="font-medium text-blue-200">
                  {downloadProgress.stage === "connecting" && "正在连接服务器..."}
                  {downloadProgress.stage === "downloading" && "正在下载内核文件..."}
                  {downloadProgress.stage === "verifying" && "正在校验 SHA256 完整性..."}
                  {downloadProgress.stage === "extracting" && "正在解压并安装内核..."}
                  {downloadProgress.stage === "completed" && "安装就绪！"}
                  {downloadProgress.stage === "error" && "下载失败"}
                </span>
              </div>
              <span className="font-bold text-blue-300 font-mono text-sm">
                {downloadProgress.percent}%
              </span>
            </div>

            {/* Progress bar */}
            <div className="w-full bg-gray-800 h-2.5 rounded-full overflow-hidden">
              <div
                className="bg-gradient-to-r from-blue-500 to-indigo-500 h-full rounded-full transition-all duration-300 ease-out"
                style={{ width: `${Math.max(0, Math.min(100, downloadProgress.percent))}%` }}
              />
            </div>

            {/* Sub-info: bytes & speed */}
            <div className="flex items-center justify-between text-[11px] text-gray-400 font-mono">
              <span className="truncate max-w-[280px]">
                {downloadProgress.message}
              </span>
              <div className="flex items-center gap-3 shrink-0">
                {downloadProgress.speed_mb !== undefined && downloadProgress.speed_mb > 0 && (
                  <span className="text-indigo-300">
                    {downloadProgress.speed_mb.toFixed(1)} MB/s
                  </span>
                )}
                {downloadProgress.downloaded_bytes !== undefined && downloadProgress.total_bytes ? (
                  <span>
                    {(downloadProgress.downloaded_bytes / 1024 / 1024).toFixed(1)} /{" "}
                    {(downloadProgress.total_bytes / 1024 / 1024).toFixed(1)} MB
                  </span>
                ) : null}
              </div>
            </div>
          </div>
        )}

        {/* Kernel List */}
        <div className="p-6 overflow-y-auto flex-1 space-y-3">
          {loading && !kernelData ? (
            <div className="flex flex-col items-center justify-center py-12 text-gray-500 gap-2">
              <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
              <span className="text-xs">正在扫描可用内核...</span>
            </div>
          ) : !kernelData?.kernels || kernelData.kernels.length === 0 ? (
            <div className="text-center py-12 text-gray-500 text-xs">
              暂无匹配当前平台的可用内核
            </div>
          ) : (
            kernelData.kernels.map((kernel) => {
              const isThisDownloading = downloadingVersion === kernel.version;
              const isAnyDownloading = !!downloadingVersion;

              return (
                <div
                  key={kernel.version}
                  className={`p-4 rounded-xl border transition-all ${
                    kernel.is_active
                      ? "bg-blue-950/15 border-blue-800/40"
                      : kernel.installed
                      ? "bg-gray-800/30 border-gray-800 hover:border-gray-700"
                      : "bg-gray-800/20 border-gray-800/60 hover:border-gray-700"
                  }`}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap mb-1">
                        <span className="font-semibold text-sm text-gray-100">
                          {kernel.name}
                        </span>
                        <span className="font-mono text-xs text-gray-400 bg-gray-800/80 px-2 py-0.5 rounded">
                          v{kernel.version}
                        </span>

                        {/* Badges */}
                        <span
                          className={`text-[10px] font-semibold px-1.5 py-0.5 rounded uppercase ${
                            kernel.tier === "pro"
                              ? "bg-purple-950/60 text-purple-300 border border-purple-800/40"
                              : "bg-blue-950/60 text-blue-300 border border-blue-800/40"
                          }`}
                        >
                          {kernel.tier}
                        </span>

                        {kernel.is_active && (
                          <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-emerald-950/60 text-emerald-300 border border-emerald-800/40 flex items-center gap-1">
                            <CheckCircle2 className="h-3 w-3" /> 当前使用
                          </span>
                        )}

                        {kernel.installed && !kernel.is_active && (
                          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-gray-800 text-gray-300">
                            已就绪
                          </span>
                        )}
                      </div>

                      <p className="text-xs text-gray-400 mb-2">
                        {kernel.description}
                      </p>

                      {kernel.installed && kernel.binary_path && (
                        <div className="flex items-center gap-1.5 text-[11px] text-gray-500 font-mono truncate">
                          <HardDrive className="h-3 w-3 shrink-0" />
                          <span className="truncate" title={kernel.binary_path}>
                            {kernel.binary_path}
                          </span>
                          {kernel.size_mb && (
                            <span className="shrink-0 text-gray-400">
                              ({kernel.size_mb} MB)
                            </span>
                          )}
                        </div>
                      )}
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-2 shrink-0">
                      {isThisDownloading ? (
                        <button
                          disabled
                          className="px-3 py-1.5 rounded-lg bg-blue-600/50 text-blue-200 text-xs font-medium flex items-center gap-1.5 cursor-not-allowed"
                        >
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          下载中...
                        </button>
                      ) : kernel.installed ? (
                        <>
                          <button
                            onClick={() => handleDownload(kernel)}
                            disabled={isAnyDownloading || actionLoading}
                            className="px-2.5 py-1.5 rounded-lg text-xs font-medium text-gray-400 hover:text-white hover:bg-gray-800 transition flex items-center gap-1 disabled:opacity-50"
                            title="重新下载并覆盖此内核"
                          >
                            <RotateCcw className="h-3.5 w-3.5" />
                            重新下载
                          </button>
                          <button
                            onClick={() => handleDelete(kernel)}
                            disabled={isAnyDownloading || actionLoading}
                            className="p-1.5 rounded-lg text-gray-400 hover:text-red-400 hover:bg-gray-800 transition disabled:opacity-50"
                            title="删除此内核"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </>
                      ) : (
                        <button
                          onClick={() => handleDownload(kernel)}
                          disabled={isAnyDownloading || actionLoading}
                          className="px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium transition flex items-center gap-1.5 shadow-lg shadow-blue-600/20 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          <Download className="h-3.5 w-3.5" />
                          下载安装
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Footer info */}
        <div className="px-6 py-3 border-t border-gray-800 bg-gray-900/80 flex items-center justify-between text-xs text-gray-400">
          <div className="flex items-center gap-1.5">
            <span className="text-blue-400">💡</span>
            <span>
              支持断点续传（HTTP Range）与防抖重试，若网络中断，再次点击可从上次进度继续。
            </span>
          </div>
          <button
            type="button"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onClose();
            }}
            className="px-4 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-200 text-xs font-medium transition cursor-pointer"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}
