import React, { useState } from "react";
import { AlertTriangle, RefreshCw, X } from "lucide-react";
import type { SystemProxyStatus } from "../lib/api";

interface SystemProxyWarningBannerProps {
  status: SystemProxyStatus | null;
  onRefresh?: () => void;
  loading?: boolean;
}

export const SystemProxyWarningBanner: React.FC<SystemProxyWarningBannerProps> = ({
  status,
  onRefresh,
  loading = false,
}) => {
  const [dismissed, setDismissed] = useState(false);

  if (dismissed || !status || !status.active) return null;

  const appName = status.detected_app || "系统代理/VPN";
  const mode = status.tun_mode ? "TUN 虚拟网卡模式" : "系统代理";
  const proxyInfo = status.http_proxy ? ` (${status.http_proxy})` : "";

  return (
    <div className="flex items-start justify-between gap-2.5 rounded-lg border border-amber-500/30 bg-amber-500/10 p-2.5 text-xs text-amber-300 mt-2">
      <div className="flex items-start gap-2 min-w-0 flex-1">
        <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-amber-400" />
        <div className="leading-relaxed">
          <p className="font-semibold text-amber-200">
            提示：宿主机已开启 {appName}（{mode}）{proxyInfo}
          </p>
          <p className="text-[11px] text-amber-300/80 mt-0.5">
            {status.tun_mode
              ? `若您未在 ${appName} 中连接代理节点（或当前处于直连分流规则），当前测得的即为本机真实物理直连；若已连接代理节点，流量可能受其接管影响。`
              : `若系统代理处于开启状态，直连探测流量可能被系统代理转发。建议核对出口 IP 是否与预期直连环境一致。`}
          </p>
        </div>
      </div>
      <div className="flex items-center gap-1 shrink-0">
        {onRefresh && (
          <button
            type="button"
            onClick={() => {
              setDismissed(false);
              onRefresh();
            }}
            disabled={loading}
            className="p-1 rounded hover:bg-amber-500/20 text-amber-400 hover:text-amber-200 transition"
            title="重新检测系统代理状态"
            aria-label="重新检测系统代理状态"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          </button>
        )}
        <button
          type="button"
          onClick={() => setDismissed(true)}
          className="p-1 rounded hover:bg-amber-500/20 text-amber-400/80 hover:text-amber-200 transition"
          title="关闭提示"
          aria-label="关闭提示"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
};
