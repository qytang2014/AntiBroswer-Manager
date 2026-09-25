/**
 * API client for AntiBrowser-Manager backend.
 */

export type HostOS = "windows" | "macos" | "linux";
export type RuntimeMode = "native" | "docker";
export type ViewerMode = "native-window" | "vnc";

export interface Profile {
  id: string;
  name: string;
  fingerprint_seed: number;
  proxy: string | null;
  timezone: string | null;
  locale: string | null;
  screen_width: number;
  screen_height: number;
  gpu_family: "auto" | "nvidia" | "intel";
  humanize: boolean;
  human_preset: string;
  geoip: boolean;
  clipboard_sync: boolean;
  auto_launch: boolean;
  color_scheme: string | null;
  launch_args: string[];
  extension_paths: string[];
  allow_3p_cookies: boolean;
  set_google_default: boolean;
  search_engine_name?: string | null;
  search_engine_keyword?: string | null;
  search_engine_url?: string | null;
  capture_preview: boolean;
  restore_session: boolean;
  browser_version?: string | null;
  browser_type?: string | null;
  cpu_cores?: number | null;
  memory_gb?: number | null;
  webgl_vendor?: string | null;
  webgl_renderer?: string | null;
  canvas_noise?: boolean;
  audio_noise?: boolean;
  do_not_track?: boolean;
  firefox_user_prefs?: Record<string, any> | null;
  extra_launch_args?: Record<string, string[]> | null;
  notes: string | null;
  user_data_dir: string;
  created_at: string;
  updated_at: string;
  sort_order: number;
  tags: { tag: string; color: string | null }[];
  status: "running" | "stopped" | "initializing";
  runtime_mode: RuntimeMode;
  viewer_mode: ViewerMode;
  vnc_ws_port: number | null;
  cdp_url: string | null;
  // Set when the last launch closed on a license denial (out of seats / bad
  // key). Cleared on the next launch. Shown under the Launch button.
  last_error: LaunchDenial | null;
  license_id: string | null;
}

export interface LaunchDenial {
  message: string;
  reason: "seat_limit" | "license";
  upgrade_url?: string;
}

export interface ProfileCreateData {
  name: string;
  fingerprint_seed?: number | null;
  proxy?: string | null;
  timezone?: string | null;
  locale?: string | null;
  screen_width?: number;
  screen_height?: number;
  gpu_family?: "auto" | "nvidia" | "intel";
  humanize?: boolean;
  human_preset?: string;
  geoip?: boolean;
  clipboard_sync?: boolean;
  auto_launch?: boolean;
  color_scheme?: string | null;
  launch_args?: string[];
  extension_paths?: string[];
  allow_3p_cookies?: boolean;
  set_google_default?: boolean;
  search_engine_name?: string | null;
  search_engine_keyword?: string | null;
  search_engine_url?: string | null;
  capture_preview?: boolean;
  restore_session?: boolean;
  browser_version?: string | null;
  browser_type?: string | null;
  cpu_cores?: number | null;
  memory_gb?: number | null;
  webgl_vendor?: string | null;
  webgl_renderer?: string | null;
  canvas_noise?: boolean;
  audio_noise?: boolean;
  do_not_track?: boolean;
  firefox_user_prefs?: Record<string, any> | null;
  extra_launch_args?: Record<string, string[]> | null;
  notes?: string | null;
  tags?: { tag: string; color: string | null }[];
  license_id?: string | null;
}

export interface LaunchResult {
  profile_id: string;
  status: string;
  runtime_mode: RuntimeMode;
  viewer_mode: ViewerMode;
  vnc_ws_port: number | null;
  display: string | null;
  cdp_url: string | null;
}

export interface ProxyTestResult {
  ok: boolean;
  ip?: string | null;
  country?: string | null;
  city?: string | null;
  timezone?: string | null;
  locale?: string | null;
  latency_ms?: number | null;
  error?: string | null;
  cached?: boolean;
}

export interface DownloadProgress {
  stage: "connecting" | "downloading" | "unpacking" | "completed" | "error";
  message: string;
  percent: number;
  downloaded_bytes?: number;
  total_bytes?: number;
  extension?: Extension;
}

export interface Extension {
  id: string;
  name: string;
  version: string;
  description?: string | null;
  icon_url?: string | null;
  path: string;
  source: string;
  webstore_id?: string | null;
  created_at: string;
}

export interface PopularExtension {
  id: string;
  name: string;
  description: string;
  version: string;
  rating: number;
}

export interface WebStoreSearchResult {
  id: string;
  name: string;
  description?: string;
  icon_url?: string | null;
}

export interface ExtensionUpdateInfo {
  has_update: boolean;
  current_version: string;
  latest_version: string | null;
  status: "update_available" | "up_to_date" | "unknown" | "unsupported" | "error";
  error?: string;
}

export interface ExtensionCheckUpdatesResult {
  updates: Record<string, ExtensionUpdateInfo>;
  checked_at: string;
}


export interface SystemStatus {
  running_count: number;
  binary_version: string;
  binary_installed?: boolean;
  license_tier: string; // "pro" | "free" | "keyless"
  profiles_total: number;
  host_os: HostOS;
  runtime_mode: RuntimeMode;
  viewer_mode: ViewerMode;
  windows_fonts_present: number | null;
  windows_fonts_required: number | null;
  windows_fonts_complete: boolean | null;
}

export interface KernelItem {
  version: string;
  name: string;
  tier: "pro" | "free";
  platform: string;
  description: string;
  installed: boolean;
  is_active?: boolean;
  binary_path?: string | null;
  size_mb?: number | null;
  browser_type?: string;
}

export interface KernelListResponse {
  current_platform: string;
  current_tier: string;
  active_version?: string | null;
  installed: boolean;
  kernels: KernelItem[];
}

export interface KernelDownloadProgress {
  version?: string;
  tier?: string;
  browser_type?: string;
  stage: "connecting" | "downloading" | "verifying" | "extracting" | "completed" | "error";
  message: string;
  percent: number;
  downloaded_bytes?: number;
  total_bytes?: number;
  speed_mb?: number;
  binary_path?: string;
}

export interface KernelDownloadStatusResponse {
  active: boolean;
  task: KernelDownloadProgress | null;
}


export interface UpdateInfo {
  current: string;
  latest: string | null;
  update_available: boolean;
  release_url: string | null;
}

export interface ManagerSettings {
  license_key_set: boolean;
  license_key_masked: string | null;
  release_channel: string; // "stable" | "preview"
  licenses: {
    id: string;
    name: string;
    key_masked: string;
    is_default: boolean;
  }[];
}

export interface SettingsUpdate {
  license_key?: string | null; // omit = unchanged; "" = clear
  release_channel?: string | null;
  licenses?: {
    id: string;
    name: string;
    key: string;
    is_default: boolean;
  }[];
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    // Set when the backend returns a structured detail (e.g. a launch blocked
    // by a license/seat problem): "seat_limit" | "license", plus an upgrade URL.
    public reason?: string,
    public upgradeUrl?: string,
  ) {
    super(message);
  }
}

// Global 401 callback — set by App to trigger login page on auth failure
let _onUnauthorized: (() => void) | null = null;
export function setOnUnauthorized(cb: (() => void) | null) {
  _onUnauthorized = cb;
}

async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    if (res.status === 401 && _onUnauthorized) {
      _onUnauthorized();
      throw new ApiError(401, "Unauthorized");
    }
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    const detail = body.detail;
    // FastAPI detail is usually a string, but license/seat denials return an
    // object {message, reason, upgrade_url} so the UI can show a CTA.
    if (detail && typeof detail === "object") {
      throw new ApiError(
        res.status,
        detail.message || res.statusText,
        detail.reason,
        detail.upgrade_url,
      );
    }
    throw new ApiError(res.status, detail || res.statusText);
  }
  return res.json();
}

export const api = {
  authStatus: () =>
    request<{ auth_required: boolean; authenticated: boolean }>("/api/auth/status"),

  login: (token: string) =>
    request<{ ok: boolean }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ token }),
    }),

  logout: () =>
    request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),

  listProfiles: () => request<Profile[]>("/api/profiles"),

  reorderProfiles: (ids: string[]) =>
    request<{ ok: boolean }>("/api/profiles/reorder", {
      method: "POST",
      body: JSON.stringify({ ordered_ids: ids }),
    }),

  getProfile: (id: string) => request<Profile>(`/api/profiles/${id}`),

  createProfile: (data: ProfileCreateData) =>
    request<Profile>("/api/profiles", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  testProxy: (proxy?: string | null, proxy_type?: string | null) =>
    request<ProxyTestResult>("/api/profiles/test-proxy", {
      method: "POST",
      body: JSON.stringify({ proxy: proxy || null, proxy_type: proxy_type || (proxy ? undefined : "direct") }),
    }),

  updateProfile: (id: string, data: Partial<ProfileCreateData>) =>
    request<Profile>(`/api/profiles/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  deleteProfile: (id: string) =>
    request<{ ok: boolean }>(`/api/profiles/${id}`, { method: "DELETE" }),

  resetProfile: (id: string) =>
    request<Profile>(`/api/profiles/${id}/reset`, { method: "POST" }),

  duplicateProfile: (id: string, includeBrowserState = false) =>
    request<Profile>(`/api/profiles/${id}/duplicate`, {
      method: "POST",
      body: JSON.stringify({ include_browser_state: includeBrowserState }),
    }),

  launchProfile: (id: string) =>
    request<LaunchResult>(`/api/profiles/${id}/launch`, { method: "POST" }),

  stopProfile: (id: string) =>
    request<{ ok: boolean }>(`/api/profiles/${id}/stop`, { method: "POST" }),

  getStatus: () => request<SystemStatus>("/api/status"),

  checkUpdate: () => request<UpdateInfo>("/api/update-check"),

  openExternal: (url: string) =>
    request<{ ok: boolean }>("/api/open-external", {
      method: "POST",
      body: JSON.stringify({ url }),
    }),

  listExtensions: (browser_type?: string) => request<Extension[]>(`/api/extensions?browser_type=${encodeURIComponent(browser_type || "cloakbrowser")}`),

  getPopularExtensions: (browser_type: string = "cloakbrowser") => request<PopularExtension[]>(`/api/extensions/popular?browser_type=${encodeURIComponent(browser_type)}`),

  matchProxyGeo: (proxy: string, proxy_type?: string) =>
    request<ProxyTestResult>("/api/profiles/test-proxy", {
      method: "POST",
      body: JSON.stringify({ proxy, proxy_type }),
    }),

  installFromWebStore: (id_or_url: string, browser_type: string = "cloakbrowser") =>
    request<Extension>("/api/extensions/install-webstore", {
      method: "POST",
      body: JSON.stringify({ id_or_url, browser_type }),
    }),

  installFromWebStoreStream: (
    id_or_url: string,
    onProgress: (progress: DownloadProgress) => void,
    browser_type: string = "cloakbrowser"
  ): Promise<Extension> => {
    return new Promise((resolve, reject) => {
      const url = `/api/extensions/install-webstore-stream?id_or_url=${encodeURIComponent(id_or_url)}&browser_type=${encodeURIComponent(browser_type)}`;
      const eventSource = new EventSource(url);

      eventSource.onmessage = (event) => {
        try {
          const data: DownloadProgress = JSON.parse(event.data);
          onProgress(data);
          if (data.stage === "completed" && data.extension) {
            eventSource.close();
            resolve(data.extension);
          } else if (data.stage === "error") {
            eventSource.close();
            reject(new Error(data.message || "Failed to install extension"));
          }
        } catch (err) {
          eventSource.close();
          reject(err);
        }
      };

      eventSource.onerror = () => {
        eventSource.close();
        reject(new Error("网络错误: 无法连接到 Chrome 应用商店，请检查代理节点配置或网络连接"));
      };
    });
  },

  searchWebStore: (query: string, browser_type: string = "cloakbrowser") =>
    request<WebStoreSearchResult[]>(`/api/extensions/webstore/search?q=${encodeURIComponent(query)}&browser_type=${encodeURIComponent(browser_type)}`),

  uploadExtension: async (file: File, browser_type: string = "cloakbrowser"): Promise<Extension> => {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch(`/api/extensions/upload?browser_type=${encodeURIComponent(browser_type)}`, {
      method: "POST",
      body: formData,
    });
    if (!res.ok) {
      const text = await res.text();
      try {
        const data = JSON.parse(text);
        throw new ApiError(res.status, data.detail || "Failed to upload extension");
      } catch (e) {
        if (e instanceof ApiError) throw e;
        throw new ApiError(res.status, text || "Failed to upload extension");
      }
    }
    return res.json();
  },

  deleteExtension: (id: string) =>
    request<{ ok: boolean }>(`/api/extensions/${id}`, { method: "DELETE" }),

  checkExtensionUpdates: () =>
    request<ExtensionCheckUpdatesResult>("/api/extensions/check-updates", { method: "POST" }),

  shutdown: () =>
    request<{ ok: boolean; message?: string }>("/api/shutdown", { method: "POST" }),


  getSettings: () => request<ManagerSettings>("/api/settings"),

  updateSettings: (data: SettingsUpdate) =>
    request<SystemStatus>("/api/settings", {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  setClipboard: (id: string, text: string) =>
    request<{ ok: boolean }>(`/api/profiles/${id}/clipboard`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),

  getClipboard: (id: string) =>
    request<{ text: string }>(`/api/profiles/${id}/clipboard`),

  // Proxy & Subscription Management
  getSubscriptions: () => request<Subscription[]>("/api/proxies/subscriptions"),

  createSubscription: (data: SubscriptionCreate) =>
    request<Subscription>("/api/proxies/subscriptions", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  updateSubscription: (id: string, data: SubscriptionUpdate) =>
    request<Subscription>(`/api/proxies/subscriptions/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  deleteSubscription: (id: string) =>
    request<{ ok: boolean }>(`/api/proxies/subscriptions/${id}`, { method: "DELETE" }),

  refreshSubscription: (id: string) =>
    request<Subscription>(`/api/proxies/subscriptions/${id}/refresh`, { method: "POST" }),

  getProxyNodes: (params?: { subscription_id?: string; manual?: boolean }) => {
    const qs = new URLSearchParams();
    if (params?.subscription_id) qs.set("subscription_id", params.subscription_id);
    if (params?.manual) qs.set("manual", "true");
    const qStr = qs.toString() ? `?${qs.toString()}` : "";
    return request<ProxyNode[]>(`/api/proxies/nodes${qStr}`);
  },

  batchAddProxyNodes: (text: string, subscription_id?: string) =>
    request<ProxyNode[]>("/api/proxies/nodes/batch", {
      method: "POST",
      body: JSON.stringify({ text, subscription_id }),
    }),

  deleteProxyNode: (id: string) =>
    request<{ ok: boolean }>(`/api/proxies/nodes/${id}`, { method: "DELETE" }),

  testProxyNode: (id: string) =>
    request<BatchTestResult>(`/api/proxies/nodes/${id}/test`, { method: "POST" }),

  batchTestProxyNodes: (data: { node_ids?: string[]; subscription_id?: string; manual_only?: boolean }) =>
    request<BatchTestResult[]>("/api/proxies/nodes/test-batch", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  // Kernel Management
  listKernels: () => request<KernelListResponse>("/api/kernels"),

  getKernelDownloadStatus: () =>
    request<KernelDownloadStatusResponse>("/api/kernels/download-status"),

  downloadKernelStream: (
    version: string,
    tier: "pro" | "free" = "free",
    browser_type: string = "cloakbrowser",
    onProgress?: (progress: KernelDownloadProgress) => void,
    signal?: AbortSignal
  ): Promise<{ ok: boolean; binary_path?: string }> => {
    return new Promise((resolve, reject) => {
      if (signal?.aborted) {
        resolve({ ok: false });
        return;
      }

      const url = `/api/kernels/download-stream?version=${encodeURIComponent(version)}&tier=${encodeURIComponent(tier)}&browser_type=${encodeURIComponent(browser_type)}`;
      const eventSource = new EventSource(url);

      if (signal) {
        signal.addEventListener(
          "abort",
          () => {
            eventSource.close();
            resolve({ ok: false });
          },
          { once: true }
        );
      }

      eventSource.onmessage = (event) => {
        try {
          const data: KernelDownloadProgress = JSON.parse(event.data);
          onProgress?.(data);

          if (data.stage === "completed") {
            eventSource.close();
            resolve({ ok: true, binary_path: data.binary_path });
          } else if (data.stage === "error") {
            eventSource.close();
            reject(new Error(data.message || "下载内核失败"));
          }
        } catch (err) {
          eventSource.close();
          reject(err);
        }
      };

      eventSource.onerror = () => {
        eventSource.close();
        reject(new Error("网络错误: 无法连接到内核下载服务，请检查网络或稍后重试"));
      };
    });
  },

  deleteKernel: (version: string, browser_type: string = "cloakbrowser") =>
    request<{ ok: boolean; message?: string }>(`/api/kernels/${encodeURIComponent(version)}?browser_type=${encodeURIComponent(browser_type)}`, { method: "DELETE" }),

  getBackupConfig: () => request<BackupConfig>("/api/backup/config"),

  updateBackupConfig: (payload: BackupConfigUpdate) =>
    request<BackupConfig>("/api/backup/config", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  testBackupConnection: (payload?: BackupConfigUpdate) =>
    request<{ ok: boolean; error: string | null }>("/api/backup/test-connection", {
      method: "POST",
      body: JSON.stringify(payload || {}),
    }),

  triggerBackupNow: (include_browser_state?: boolean) =>
    request<{ task_id: string }>("/api/backup/now", {
      method: "POST",
      body: JSON.stringify({ include_browser_state }),
    }),

  listBackups: () => request<BackupFile[]>("/api/backup/list"),

  restoreBackup: (filename: string, decrypt_password?: string) =>
    request<{ task_id: string }>("/api/backup/restore", {
      method: "POST",
      body: JSON.stringify({ filename, decrypt_password }),
    }),

  deleteBackup: (filename: string) =>
    request<{ ok: boolean }>(`/api/backup/${encodeURIComponent(filename)}`, {
      method: "DELETE",
    }),

  subscribeBackupProgress: (
    taskId: string,
    onProgress: (ev: BackupProgressEvent) => void,
    signal?: AbortSignal
  ): Promise<BackupProgressEvent> => {
    return new Promise((resolve, reject) => {
      if (signal?.aborted) {
        reject(new Error("Aborted"));
        return;
      }

      const eventSource = new EventSource(`/api/backup/progress/${encodeURIComponent(taskId)}`);

      if (signal) {
        signal.addEventListener(
          "abort",
          () => {
            eventSource.close();
            reject(new Error("Aborted"));
          },
          { once: true }
        );
      }

      eventSource.onmessage = (event) => {
        try {
          const data: BackupProgressEvent = JSON.parse(event.data);
          onProgress(data);
          if (data.status === "completed") {
            eventSource.close();
            resolve(data);
          } else if (data.status === "error") {
            eventSource.close();
            reject(new Error(data.message || data.error || "Operation failed"));
          }
        } catch (err) {
          eventSource.close();
          reject(err);
        }
      };

      eventSource.onerror = () => {
        // If readyState is CONNECTING (0), browser EventSource is auto-reconnecting; do not abort prematurely
        if (eventSource.readyState === EventSource.CONNECTING) {
          return;
        }
        eventSource.close();
        reject(new Error("网络连接异常: 与备份任务的实时通道断开"));
      };
    });
  },
};

export interface Subscription {
  id: string;
  name: string;
  url: string;
  update_interval_hours: number;
  last_updated_at: string | null;
  node_count: number;
  created_at: string;
  updated_at: string;
}

export interface SubscriptionCreate {
  name: string;
  url: string;
  update_interval_hours?: number;
}

export interface SubscriptionUpdate {
  name?: string;
  url?: string;
  update_interval_hours?: number;
}

export interface ProxyNode {
  id: string;
  subscription_id: string | null;
  name: string;
  protocol: string;
  raw_uri: string;
  last_latency_ms: number | null;
  last_tested_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface BatchTestResult {
  node_id: string;
  latency_ms: number | null;
  ok: boolean;
  error?: string | null;
}

export type BackupBackend = "webdav" | "s3";

export interface BackupConfig {
  backend: BackupBackend | null;
  webdav_url: string | null;
  webdav_username: string | null;
  webdav_remote_path: string | null;
  webdav_skip_ssl: boolean;
  s3_endpoint_url: string | null;
  s3_access_key: string | null;
  s3_bucket: string | null;
  s3_prefix: string | null;
  s3_region: string | null;
  encrypt_enabled: boolean;
  encrypt_password_set: boolean;
  auto_backup_interval_hours: number;
  retain_count: number;
  include_browser_state: boolean;
  last_backup_at: string | null;
}

export interface BackupConfigUpdate {
  backend?: BackupBackend | null;
  webdav_url?: string | null;
  webdav_username?: string | null;
  webdav_password?: string | null;
  webdav_remote_path?: string | null;
  webdav_skip_ssl?: boolean;
  s3_endpoint_url?: string | null;
  s3_access_key?: string | null;
  s3_secret_key?: string | null;
  s3_bucket?: string | null;
  s3_prefix?: string | null;
  s3_region?: string | null;
  encrypt_enabled?: boolean;
  encrypt_password?: string | null;
  auto_backup_interval_hours?: number;
  retain_count?: number;
  include_browser_state?: boolean;
}

export interface BackupFile {
  name: string;
  size_bytes: number;
  created_at: string;
  mode: "config" | "full";
  encrypted: boolean;
  checksum: string | null;
}

export interface BackupProgressEvent {
  task_id: string;
  type: "backup" | "restore";
  stage: string;
  percent: number;
  message: string;
  status: "running" | "completed" | "error";
  error?: string | null;
  filename?: string | null;
}

