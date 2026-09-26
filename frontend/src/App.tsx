import { useState, useCallback, useEffect, useRef } from "react";
import { Lock, PanelLeftClose, PanelLeft, Settings, Power, Network, Puzzle, Cpu, AlertTriangle, X, Loader2, Globe, Plus } from "lucide-react";
import { useProfiles } from "./hooks/useProfiles";
import { api, ApiError, setOnUnauthorized, type ProfileCreateData, type SystemStatus, type UpdateInfo, type LaunchDenial, type KernelDownloadProgress } from "./lib/api";
import { ProfileList } from "./components/ProfileList";
import { ProfileForm, setCachedInstalledKernels } from "./components/ProfileForm";
import { ProfileViewer } from "./components/ProfileViewer";
import { NativeWindowStatus } from "./components/NativeWindowStatus";
import { LaunchButton } from "./components/LaunchButton";
import { StatusIndicator } from "./components/StatusIndicator";
import { SystemStatusBadge } from "./components/SystemStatusBadge";
import { UpdateBanner } from "./components/UpdateBanner";
import { LaunchErrorBanner } from "./components/LaunchErrorBanner";
import { SettingsPanel } from "./components/SettingsPanel";
import { LoginPage } from "./components/LoginPage";
import { ProxyManagerModal } from "./components/ProxyManagerModal";
import { ExtensionManagerModal } from "./components/ExtensionManagerModal";
import { KernelManagerModal } from "./components/KernelManagerModal";

type AuthState = "checking" | "required" | "ok" | "error";
type View = "empty" | "create" | "edit" | "view";

export default function App() {
  const [authState, setAuthState] = useState<AuthState>("checking");
  const [authRequired, setAuthRequired] = useState(false);

  useEffect(() => {
    setOnUnauthorized(() => setAuthState("required"));

    api.authStatus()
      .then(({ auth_required, authenticated }) => {
        setAuthRequired(auth_required);
        if (!auth_required || authenticated) {
          setAuthState("ok");
        } else {
          setAuthState("required");
        }
      })
      .catch((err) => {
        console.warn("[auth] status check failed:", err);
        setAuthState("error");
      });

    return () => setOnUnauthorized(null);
  }, []);

  if (authState === "checking") {
    return (
      <div className="h-screen flex items-center justify-center">
        <div className="text-gray-500 text-sm">Loading...</div>
      </div>
    );
  }

  if (authState === "error") {
    return (
      <div className="h-screen flex items-center justify-center bg-surface-0">
        <div className="text-center">
          <p className="text-red-400 text-sm mb-2">Unable to reach the server</p>
          <button
            onClick={() => {
              setAuthState("checking");
              api.authStatus()
                .then(({ auth_required, authenticated }) => {
                  setAuthRequired(auth_required);
                  setAuthState(!auth_required || authenticated ? "ok" : "required");
                })
                .catch(() => setAuthState("error"));
            }}
            className="text-xs text-gray-400 hover:text-gray-200 underline"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (authState === "required") {
    return <LoginPage onSuccess={() => setAuthState("ok")} />;
  }

  return (
    <AppContent
      authRequired={authRequired}
      onLogout={async () => {
        await api.logout();
        setAuthState("required");
      }}
    />
  );
}

interface AppContentProps {
  authRequired: boolean;
  onLogout: () => void;
}

function AppContent({ authRequired, onLogout }: AppContentProps) {
  const { profiles, loading, error, refresh, create, update, remove, reorder, launch, stop, reset, duplicate } = useProfiles();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [extensionsVersion, setExtensionsVersion] = useState(0);
  const [view, setView] = useState<View>("empty");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null);
  const [updateDismissed, setUpdateDismissed] = useState(false);
  const [launchError, setLaunchError] = useState<LaunchDenial | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [proxyManagerOpen, setProxyManagerOpen] = useState(false);
  const [extensionManagerOpen, setExtensionManagerOpen] = useState(false);
  const [kernelManagerOpen, setKernelManagerOpen] = useState(false);
  const [kernelsVersion, setKernelsVersion] = useState(0);
  const [settingsVersion, setSettingsVersion] = useState(0);
  const [kernelBannerDismissed, setKernelBannerDismissed] = useState(false);
  const [activeDownload, setActiveDownload] = useState<KernelDownloadProgress | null>(null);
  const [stopped, setStopped] = useState(false);

  const refreshSystemStatus = useCallback(() => {
    api.getStatus().then(setSystemStatus).catch(() => setSystemStatus(null));
  }, []);

  const handleCloseSettings = useCallback(() => setSettingsOpen(false), []);
  const handleCloseProxyManager = useCallback(() => setProxyManagerOpen(false), []);
  const handleCloseExtensionManager = useCallback(() => setExtensionManagerOpen(false), []);
  const handleCloseKernelManager = useCallback(() => setKernelManagerOpen(false), []);

  const handleQuit = useCallback(async () => {
    if (!window.confirm("Quit AntiBrowser-Manager? This stops the server and closes all running profiles.")) {
      return;
    }
    setStopped(true);
    try {
      await api.shutdown();
    } catch {
      // The server exits mid-request, so a network error here is expected.
    }
  }, []);

  useEffect(() => {
    refreshSystemStatus();
    api.checkUpdate().then(setUpdateInfo).catch(() => setUpdateInfo(null));
    api.listKernels().then((res) => {
      setCachedInstalledKernels(res.kernels.filter((k) => k.installed));
    }).catch(() => {});
  }, [refreshSystemStatus]);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    let isSubscribed = true;

    const checkDownloadStatus = async () => {
      try {
        const res = await api.getKernelDownloadStatus();
        if (!isSubscribed) return;
        if (res.active && res.task) {
          setActiveDownload(res.task);
          timer = setTimeout(checkDownloadStatus, 1500);
        } else {
          setActiveDownload((prev) => {
            if (prev) {
              refreshSystemStatus();
            }
            return null;
          });
          timer = setTimeout(checkDownloadStatus, 4000);
        }
      } catch {
        if (isSubscribed) {
          timer = setTimeout(checkDownloadStatus, 6000);
        }
      }
    };

    checkDownloadStatus();

    return () => {
      isSubscribed = false;
      clearTimeout(timer);
    };
  }, [refreshSystemStatus]);

  const selected = profiles.find((p) => p.id === selectedId) ?? null;

  // Switching profiles clears the banner (like X); a post-handshake denial
  // (profile.last_error, arriving via the poll) shows only while its own
  // profile stays selected, never carried across a switch.
  const prevSelectedId = useRef(selectedId);
  const selectedLastErrorMsg = selected?.last_error?.message ?? null;
  useEffect(() => {
    const switched = prevSelectedId.current !== selectedId;
    prevSelectedId.current = selectedId;
    if (switched) {
      setLaunchError(null);
      return;
    }
    if (selected?.last_error) setLaunchError(selected.last_error);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, selectedLastErrorMsg]);

  const handleSelect = useCallback((id: string) => {
    setSelectedId(id);
    const profile = profiles.find((p) => p.id === id);
    setView(profile?.status === "running" ? "view" : "edit");
  }, [profiles]);

  const handleNew = useCallback(() => {
    setSelectedId(null);
    setView("create");
  }, []);

  const handleCreate = useCallback(async (data: ProfileCreateData) => {
    const profile = await create(data);
    if (profile) {
      setSelectedId(profile.id);
      setView("edit");
    }
  }, [create]);

  const handleUpdate = useCallback(async (data: ProfileCreateData) => {
    if (!selectedId) return;
    await update(selectedId, data);
  }, [selectedId, update]);

  const handleDelete = useCallback(async () => {
    if (!selectedId) return;
    await remove(selectedId);
    setSelectedId(null);
    setView("empty");
  }, [selectedId, remove]);

  const handleLaunch = useCallback(async () => {
    if (!selectedId) return;
    setLaunchError(null);
    try {
      const result = await launch(selectedId);
      if (result) setView("view");
    } catch (err) {
      // A license denial (out of seats, bad/expired key) → 402/403 with a
      // structured detail; surface it in the top banner.
      if (err instanceof ApiError && (err.status === 402 || err.status === 403)) {
        setLaunchError({
          message: err.message,
          reason: (err.reason as LaunchDenial["reason"]) ?? "license",
          upgrade_url: err.upgradeUrl,
        });
      } else {
        setLaunchError({
          message: err instanceof Error ? err.message : "Failed to launch profile",
          reason: "license",
        });
      }
    }
  }, [selectedId, launch]);

  const handleStop = useCallback(async () => {
    if (!selectedId) return;
    await stop(selectedId);
    setView("edit");
  }, [selectedId, stop]);

  const handleReset = useCallback(async () => {
    if (!selectedId) return;
    await reset(selectedId);
    // Stays in the edit view — the profile is wiped but not launched.
  }, [selectedId, reset]);

  const handleDuplicate = useCallback(async (includeBrowserState: boolean) => {
    if (!selectedId) return;
    const profile = await duplicate(selectedId, includeBrowserState);
    if (profile) {
      setSelectedId(profile.id);
      setView("edit");
    }
  }, [selectedId, duplicate]);

  const handleClipboardSyncChange = useCallback(async (enabled: boolean) => {
    if (!selectedId) throw new Error("No profile selected");
    const updated = await update(selectedId, { clipboard_sync: enabled });
    if (!updated) throw new Error("Failed to save clipboard preference");
  }, [selectedId, update]);

  const handleVncDisconnect = useCallback(() => {
    setView("edit");
  }, []);

  if (loading) {
    return (
      <div className="h-screen flex items-center justify-center">
        <div className="text-gray-500 text-sm">Loading...</div>
      </div>
    );
  }

  if (stopped) {
    return (
      <div className="h-screen flex flex-col items-center justify-center bg-surface-0 text-center px-6">
        <Power className="h-10 w-10 text-gray-600 mb-4" />
        <h1 className="text-lg font-medium mb-1">AntiBrowser-Manager has stopped</h1>
        <p className="text-sm text-gray-500">The server is no longer running. You can close this tab.</p>
        <p className="text-xs text-gray-600 mt-4">Relaunch the app to start it again.</p>
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col">
      {settingsOpen && (
        <SettingsPanel
          onClose={handleCloseSettings}
          onSaved={(status) => {
            setSystemStatus(status);
            setSettingsVersion(v => v + 1);
          }}
          onOpenKernelManager={() => {
            setSettingsOpen(false);
            setKernelManagerOpen(true);
          }}
          systemStatus={systemStatus}
        />
      )}
      {proxyManagerOpen && (
        <ProxyManagerModal
          isOpen={proxyManagerOpen}
          onClose={handleCloseProxyManager}
        />
      )}
      {extensionManagerOpen && (
        <ExtensionManagerModal
          isOpen={extensionManagerOpen}
          onClose={handleCloseExtensionManager}
          onExtensionsChanged={() => {
            setExtensionsVersion((v) => v + 1);
            refresh();
          }}
        />
      )}
      {kernelManagerOpen && (
        <KernelManagerModal
          isOpen={kernelManagerOpen}
          onClose={handleCloseKernelManager}
          onKernelChanged={() => {
            refreshSystemStatus();
            setKernelsVersion((v) => v + 1);
            api.listKernels().then((res) => {
              setCachedInstalledKernels(res.kernels.filter((k) => k.installed));
            }).catch(() => {});
          }}
        />
      )}
      {activeDownload && !kernelManagerOpen && (
        <div className="bg-blue-950/80 border-b border-blue-800/60 px-4 py-2 text-xs flex items-center justify-between text-blue-200">
          <div className="flex items-center gap-2 min-w-0">
            <Loader2 className="h-4 w-4 text-blue-400 shrink-0 animate-spin" />
            <span className="truncate">
              <strong>正在后台下载内核{activeDownload.version ? ` (${activeDownload.version})` : ""}:</strong>{" "}
              {activeDownload.message || `已完成 ${activeDownload.percent}%`}
            </span>
            <div className="w-24 bg-gray-800 rounded-full h-1.5 overflow-hidden ml-2 shrink-0 hidden sm:block">
              <div
                className="bg-blue-500 h-1.5 rounded-full transition-all duration-300"
                style={{ width: `${Math.min(Math.max(activeDownload.percent || 0, 0), 100)}%` }}
              />
            </div>
            <span className="font-mono text-[11px] text-blue-300 shrink-0">{activeDownload.percent}%</span>
          </div>
          <div className="flex items-center gap-3 shrink-0 ml-3">
            <button
              onClick={() => setKernelManagerOpen(true)}
              className="px-2.5 py-1 rounded bg-blue-600 hover:bg-blue-500 text-white font-medium text-xs transition"
            >
              查看详情
            </button>
          </div>
        </div>
      )}
      {systemStatus && systemStatus.binary_installed === false && !kernelBannerDismissed && !activeDownload && (
        <div className="bg-amber-950/70 border-b border-amber-800/60 px-4 py-2 text-xs flex items-center justify-between text-amber-200">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0" />
            <span>
              <strong>未检测到 Chromium 内核</strong>：启动浏览器配置前，请先下载并安装内核。
            </span>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setKernelManagerOpen(true)}
              className="px-2.5 py-1 rounded bg-amber-500 hover:bg-amber-400 text-gray-950 font-semibold text-xs transition"
            >
              立即下载内核
            </button>
            <button
              onClick={() => setKernelBannerDismissed(true)}
              className="text-amber-400/70 hover:text-amber-200 p-0.5 rounded"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}
      {updateInfo?.update_available && !updateDismissed && (
        <UpdateBanner info={updateInfo} onDismiss={() => setUpdateDismissed(true)} />
      )}
      {launchError && (
        <LaunchErrorBanner error={launchError} onDismiss={() => setLaunchError(null)} />
      )}
      <div className="flex-1 flex min-h-0">
      {/* Sidebar */}
      {sidebarOpen && (
        <div className="w-64 border-r border-border bg-surface-1 flex-shrink-0">
          <ProfileList
            profiles={profiles}
            selectedId={selectedId}
            onSelect={handleSelect}
            onNew={handleNew}
            onReorder={reorder}
            systemStatus={systemStatus}
          />
        </div>
      )}

      {/* Main panel */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top bar */}
        <div className="flex items-center justify-between px-4 py-2 border-b border-border bg-surface-1">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="text-gray-500 hover:text-gray-300 p-1"
              title={sidebarOpen ? "Hide sidebar" : "Show sidebar"}
            >
              {sidebarOpen ? <PanelLeftClose className="h-4 w-4" /> : <PanelLeft className="h-4 w-4" />}
            </button>
            {selected && (
              <div className="flex items-center gap-2">
                <StatusIndicator status={selected.status} size="md" />
                <span className="text-sm font-medium">{selected.name}</span>
              </div>
            )}
          </div>
          <div className="flex items-center gap-3">
            <SystemStatusBadge status={systemStatus} />
            <button
              onClick={() => setKernelManagerOpen(true)}
              className="relative text-gray-500 hover:text-blue-400 p-1"
              title="内核管理 / Kernel Manager"
            >
              <Cpu className="h-4 w-4" />
              {systemStatus && systemStatus.binary_installed === false && (
                <span className="absolute top-0.5 right-0.5 w-2 h-2 rounded-full bg-amber-400 ring-2 ring-surface-1 animate-pulse" />
              )}
            </button>
            <button
              onClick={() => setProxyManagerOpen(true)}
              className="text-gray-500 hover:text-cyan-400 p-1"
              title="管理代理 / Manage Proxies"
            >
              <Network className="h-4 w-4" />
            </button>
            <button
              onClick={() => setExtensionManagerOpen(true)}
              className="text-gray-500 hover:text-amber-400 p-1"
              title="管理扩展 / Manage Extensions"
            >
              <Puzzle className="h-4 w-4" />
            </button>
            <button
              onClick={() => setSettingsOpen(true)}
              className="text-gray-500 hover:text-gray-300 p-1"
              title="Settings"
            >
              <Settings className="h-4 w-4" />
            </button>
            <button
              onClick={handleQuit}
              className="text-gray-500 hover:text-red-400 p-1"
              title="Quit Manager (stops the server)"
            >
              <Power className="h-4 w-4" />
            </button>
            {selected && (
              <LaunchButton
                key={selected.id}
                status={selected.status}
                onLaunch={handleLaunch}
                onStop={handleStop}
              />
            )}
            {authRequired && (
              <button
                onClick={onLogout}
                className="text-gray-500 hover:text-gray-300 p-1"
                title="Log out"
              >
                <Lock className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </div>

        {/* Error banner */}
        {error && (
          <div className="px-4 py-2 bg-red-600/15 border-b border-red-600/30 text-red-400 text-sm">
            {error}
          </div>
        )}

        {/* Content */}
        <div className="flex-1 overflow-y-auto overscroll-contain">
          {view === "empty" && (
            <div className="flex items-center justify-center h-full px-6">
              <div className="max-w-md text-center">
                <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-surface-2 border border-border mb-4 text-accent">
                  <Globe className="h-6 w-6" />
                </div>
                <h3 className="text-base font-semibold text-gray-200">
                  AntiBrowser-Manager 已就绪
                </h3>
                <p className="mt-1.5 text-sm text-gray-400">
                  支持 CloakBrowser (Chromium) 与 Camoufox (Firefox) 双反指纹内核
                </p>
                <div className="mt-6 flex flex-col sm:flex-row items-center justify-center gap-3">
                  <button
                    onClick={() => {
                      setSelectedId(null);
                      setView("create");
                    }}
                    className="btn-primary w-full sm:w-auto px-5 flex items-center justify-center gap-1.5"
                  >
                    <Plus className="w-4 h-4" />
                    <span>新建浏览器环境</span>
                  </button>
                  <button
                    onClick={() => setKernelManagerOpen(true)}
                    className="btn-secondary w-full sm:w-auto px-5 flex items-center justify-center gap-1.5"
                  >
                    <Cpu className="w-4 h-4" />
                    <span>内核管理</span>
                  </button>
                </div>
                {(systemStatus?.license_tier ?? "keyless") === "keyless" && (
                  <p className="mt-6 text-xs text-gray-500">
                    使用 CloakBrowser 商业版？
                    <button
                      onClick={() => setSettingsOpen(true)}
                      className="ml-1 text-accent hover:underline"
                    >
                      在设置中配置 Pro 授权
                    </button>
                  </p>
                )}
              </div>
            </div>
          )}

          {view === "create" && (
            <ProfileForm
              key="create"
              profile={null}
              hostOs={systemStatus?.host_os ?? null}
              viewerMode={systemStatus?.viewer_mode ?? null}
              onSave={handleCreate}
              onCancel={() => setView("empty")}
              extensionsUpdated={extensionsVersion}
              kernelsUpdated={kernelsVersion}
              settingsUpdated={settingsVersion}
              onOpenKernelManager={() => setKernelManagerOpen(true)}
            />
          )}

          {view === "edit" && selected && (
            <ProfileForm
              key={selected.id}
              profile={selected}
              hostOs={systemStatus?.host_os ?? null}
              viewerMode={systemStatus?.viewer_mode ?? null}
              onSave={handleUpdate}
              onDelete={handleDelete}
              onReset={handleReset}
              onDuplicate={handleDuplicate}
              onCancel={() => {
                setSelectedId(null);
                setView("empty");
              }}
              extensionsUpdated={extensionsVersion}
              kernelsUpdated={kernelsVersion}
              settingsUpdated={settingsVersion}
              onOpenKernelManager={() => setKernelManagerOpen(true)}
            />
          )}

          {view === "view" && selected && selected.status === "running" && (
            selected.viewer_mode === "vnc" ? (
              <ProfileViewer
                key={selected.id}
                profileId={selected.id}
                cdpUrl={selected.cdp_url}
                clipboardSync={selected.clipboard_sync}
                onClipboardSyncChange={handleClipboardSyncChange}
                onDisconnect={handleVncDisconnect}
              />
            ) : (
              <NativeWindowStatus
                key={selected.id}
                profileId={selected.id}
                profileName={selected.name}
                cdpUrl={selected.cdp_url}
                capturePreview={selected.capture_preview}
              />
            )
          )}
        </div>
      </div>
      </div>
    </div>
  );
}
