import { Check, ChevronDown, ChevronUp, Copy, Loader2, Puzzle, RotateCcw, Save, Search, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import type {
  Extension,
  HostOS,
  Profile,
  ProfileCreateData,
  ProxyNode,
  ProxyTestResult,
  ViewerMode,
} from "../lib/api";
import { ProxyManagerModal } from "./ProxyManagerModal";

function detectProxyType(raw: string | null | undefined): "standard" | "singbox_uri" | "singbox_sub" | "singbox_json" {
  if (!raw) return "standard";
  const trimmed = raw.trim();
  if (trimmed.startsWith("{") && trimmed.endsWith("}")) return "singbox_json";
  if (
    trimmed.startsWith("vless://") ||
    trimmed.startsWith("vmess://") ||
    trimmed.startsWith("trojan://") ||
    trimmed.startsWith("ss://") ||
    trimmed.startsWith("shadowsocks://") ||
    trimmed.startsWith("hysteria2://") ||
    trimmed.startsWith("hy2://") ||
    trimmed.startsWith("tuic://") ||
    trimmed.startsWith("anytls://") ||
    trimmed.startsWith("wireguard://")
  ) {
    return "singbox_uri";
  }
  if (trimmed.includes("/sub/") || trimmed.includes("subscribe")) {
    return "singbox_sub";
  }
  return "standard";
}

interface ProfileFormProps {
  profile: Profile | null; // null = create mode
  hostOs: HostOS | null;
  viewerMode: ViewerMode | null;
  onSave: (data: ProfileCreateData) => Promise<void>;
  onDelete?: () => Promise<void>;
  onReset?: () => Promise<void>;
  onDuplicate?: (includeBrowserState: boolean) => Promise<void>;
  onCancel: () => void;
}

const RESOLUTION_PRESETS: Record<string, { width: number; height: number }> = {
  "1920 × 1080 (Full HD)": { width: 1920, height: 1080 },
  "2560 × 1440 (QHD)": { width: 2560, height: 1440 },
  "1366 × 768 (HD)": { width: 1366, height: 768 },
  "1440 × 900": { width: 1440, height: 900 },
  "1536 × 864": { width: 1536, height: 864 },
  "1280 × 720 (720p)": { width: 1280, height: 720 },
};

const TAG_COLORS = [
  "#6366f1", // indigo
  "#22c55e", // green
  "#f59e0b", // amber
  "#ef4444", // red
  "#06b6d4", // cyan
  "#a855f7", // purple
  "#f97316", // orange
  "#ec4899", // pink
];

export function ProfileForm({ profile, hostOs, viewerMode, onSave, onDelete, onReset, onDuplicate, onCancel }: ProfileFormProps) {
  const isEdit = profile !== null;

  const [form, setForm] = useState<ProfileCreateData>({
    name: "",
    screen_width: 1920,
    screen_height: 1080,
    gpu_family: "auto",
    humanize: false,
    human_preset: "default",
    geoip: true,
    clipboard_sync: true,
    auto_launch: false,
    allow_3p_cookies: true,
    set_google_default: true,
    capture_preview: true,
    restore_session: true,
    extension_paths: [],
    launch_args: [],
    tags: [],
  });

  const [proxyType, setProxyType] = useState<"standard" | "singbox_uri" | "singbox_sub" | "singbox_json">(() =>
    detectProxyType(profile?.proxy)
  );
  const [installedExtensions, setInstalledExtensions] = useState<Extension[]>([]);
  const [extDropdownOpen, setExtDropdownOpen] = useState(false);
  const [extSearch, setExtSearch] = useState("");
  const extDropdownRef = useRef<HTMLDivElement>(null);
  const prevLibraryPathsRef = useRef<Set<string>>(new Set());

  const [managedNodes, setManagedNodes] = useState<ProxyNode[]>([]);
  const [subsMap, setSubsMap] = useState<Map<string, string>>(new Map());
  const [isProxyModalOpen, setIsProxyModalOpen] = useState(false);

  const loadManagedProxies = useCallback(async () => {
    try {
      const [subs, nodes] = await Promise.all([
        api.getSubscriptions(),
        api.getProxyNodes(),
      ]);
      setSubsMap(new Map(subs.map((s) => [s.id, s.name])));
      setManagedNodes(nodes);
    } catch (e) {
      console.error("Failed to load managed proxies", e);
    }
  }, []);

  useEffect(() => {
    loadManagedProxies();
  }, [loadManagedProxies]);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (extDropdownRef.current && !extDropdownRef.current.contains(e.target as Node)) {
        setExtDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const [previewError, setPreviewError] = useState(false);
  const [previewBuster, setPreviewBuster] = useState(0);

  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [resetDone, setResetDone] = useState(false);
  const [duplicating, setDuplicating] = useState(false);
  const [duplicateMenuOpen, setDuplicateMenuOpen] = useState(false);
  const duplicateMenuRef = useRef<HTMLDivElement>(null);
  const duplicateTriggerRef = useRef<HTMLButtonElement>(null);
  const [testingProxy, setTestingProxy] = useState(false);
  const [proxyTest, setProxyTest] = useState<ProxyTestResult | null>(null);
  const savedTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const resetTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => () => {
    clearTimeout(savedTimer.current);
    clearTimeout(resetTimer.current);
  }, []);
  const [tagInput, setTagInput] = useState("");
  const [tagColor, setTagColor] = useState<string | null>("#6366f1");
  const [launchArgInput, setLaunchArgInput] = useState("");

  const loadInstalledExtensions = async () => {
    try {
      const list = await api.listExtensions();
      setInstalledExtensions(list);

      setForm((f) => {
        const currentPaths = f.extension_paths ?? [];
        if (!profile) {
          // New profile: default all installed extensions to checked
          return { ...f, extension_paths: list.map((e) => e.path) };
        } else {
          // Existing profile: if there are newly installed extensions in the library, auto-select them
          const updated = new Set(currentPaths);
          const prevKnown = prevLibraryPathsRef.current;
          list.forEach((ext) => {
            if (!prevKnown.has(ext.path) && prevKnown.size > 0) {
              updated.add(ext.path);
            }
          });
          return { ...f, extension_paths: Array.from(updated) };
        }
      });

      prevLibraryPathsRef.current = new Set(list.map((e) => e.path));
    } catch (err) {
      console.error("Failed to load extensions in form:", err);
    }
  };

  useEffect(() => {
    loadInstalledExtensions();
  }, []);

  useEffect(() => {
    if (profile) {
      setForm({
        name: profile.name,
        fingerprint_seed: profile.fingerprint_seed,
        proxy: profile.proxy,
        timezone: profile.timezone,
        locale: profile.locale,
        screen_width: profile.screen_width,
        screen_height: profile.screen_height,
        gpu_family: profile.gpu_family,
        humanize: profile.humanize,
        human_preset: profile.human_preset,
        geoip: profile.geoip,
        clipboard_sync: profile.clipboard_sync,
        auto_launch: profile.auto_launch,
        extension_paths: profile.extension_paths ?? [],
        allow_3p_cookies: profile.allow_3p_cookies,
        set_google_default: profile.set_google_default,
        capture_preview: profile.capture_preview,
        restore_session: profile.restore_session,
        launch_args: profile.launch_args ?? [],
        notes: profile.notes,
        tags: profile.tags ?? [],
      });
      setProxyType(detectProxyType(profile.proxy));
    } else {
      // New profile: default all installed extensions to checked
      setForm((f) => ({
        ...f,
        extension_paths: installedExtensions.map((e) => e.path),
      }));
    }
    // Re-fetch the preview for the newly selected profile (bust the cache).
    setPreviewError(false);
    setPreviewBuster(Date.now());
  }, [profile?.id, installedExtensions.length]);

  useEffect(() => {
    if (hostOs === "macos") {
      setForm((previous) => ({ ...previous, gpu_family: "auto" }));
    }
  }, [hostOs]);

  const set = <K extends keyof ProfileCreateData>(key: K, value: ProfileCreateData[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const toggleExtension = (extPath: string) => {
    const current = form.extension_paths ?? [];
    if (current.includes(extPath)) {
      set("extension_paths", current.filter((p) => p !== extPath));
    } else {
      set("extension_paths", [...current, extPath]);
    }
  };

  const selectAllExtensions = () => {
    const allPaths = Array.from(
      new Set([...(form.extension_paths ?? []), ...installedExtensions.map((e) => e.path)])
    );
    set("extension_paths", allPaths);
  };

  const clearAllExtensions = () => {
    set("extension_paths", []);
  };

  const removeExtensionPath = (pathToRemove: string) => {
    const current = form.extension_paths ?? [];
    set("extension_paths", current.filter((p) => p !== pathToRemove));
  };

  const [matchingGeo, setMatchingGeo] = useState(false);
  const [geoMatchMessage, setGeoMatchMessage] = useState<string | null>(null);

  const handleMatchProxyGeo = async () => {
    if (!form.proxy) return;
    setMatchingGeo(true);
    setGeoMatchMessage(null);
    try {
      const res = await api.testProxy(form.proxy, proxyType);
      setProxyTest(res);
      if (!res.ok) {
        alert(`无法获取代理 IP 信息: ${res.error || "连接失败"}`);
        return;
      }
      const newTz = res.timezone || null;
      const newLoc = res.locale || null;

      if (!newTz && !newLoc) {
        alert(`已解析代理出口 IP (${res.ip})，但未在 IP 数据库中查询到对应的时区或语言信息。`);
        return;
      }

      const hasExistingTz = Boolean(form.timezone && form.timezone.trim());
      const hasExistingLoc = Boolean(form.locale && form.locale.trim());

      if ((hasExistingTz && form.timezone !== newTz) || (hasExistingLoc && form.locale !== newLoc)) {
        const confirmMsg =
          `检测到已设置的时区/语言配置：\n` +
          `· 时区: ${form.timezone || "未设置"} -> ${newTz || "未匹配"}\n` +
          `· 语言: ${form.locale || "未设置"} -> ${newLoc || "未匹配"}\n\n` +
          `是否确认按代理出口 IP (${res.ip}) 覆盖现有设置？`;
        if (!window.confirm(confirmMsg)) {
          return;
        }
      }

      if (newTz) set("timezone", newTz);
      if (newLoc) set("locale", newLoc);
      setGeoMatchMessage(`已按出口 IP (${res.ip}) 匹配设置: 时区 ${newTz || "-"} / 语言 ${newLoc || "-"}`);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "匹配代理地理信息失败";
      alert(`匹配失败: ${message}`);
    } finally {
      setMatchingGeo(false);
    }
  };

  const handleTestProxy = async () => {
    if (!form.proxy) return;
    setProxyTest(null);
    setTestingProxy(true);
    try {
      const res = await api.testProxy(form.proxy, proxyType);
      setProxyTest(res);
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : "Proxy test failed";
      setProxyTest({ ok: false, error: message });
    } finally {
      setTestingProxy(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name.trim()) return;
    setSaving(true);
    try {
      await onSave(form);
      setSaved(true);
      clearTimeout(savedTimer.current);
      savedTimer.current = setTimeout(() => setSaved(false), 1500);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!onDelete) return;
    if (!confirm("Delete this profile? Browser data will be permanently removed.")) return;
    setDeleting(true);
    try {
      await onDelete();
    } finally {
      setDeleting(false);
    }
  };

  const handleReset = async () => {
    if (!onReset) return;
    if (
      !confirm(
        "Reset this profile? Cookies, history and site data will be wiped and a " +
          "new fingerprint generated. Bookmarks, settings and default search are kept.",
      )
    )
      return;
    setResetting(true);
    try {
      await onReset();
      setResetDone(true);
      clearTimeout(resetTimer.current);
      resetTimer.current = setTimeout(() => setResetDone(false), 1500);
    } finally {
      setResetting(false);
    }
  };

  useEffect(() => {
    if (!duplicateMenuOpen) return;
    const onPointerDown = (e: MouseEvent) => {
      if (!duplicateMenuRef.current?.contains(e.target as Node)) setDuplicateMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setDuplicateMenuOpen(false);
      // A focused menu item is about to unmount; hand focus back to the trigger
      // so keyboard users are not dropped onto the document body.
      duplicateTriggerRef.current?.focus();
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [duplicateMenuOpen]);

  const handleDuplicate = async (includeBrowserState: boolean) => {
    setDuplicateMenuOpen(false);
    if (!onDuplicate) return;
    const message = includeBrowserState
      ? "Duplicate this profile with its browser state? A new profile with the " +
        "same settings, fingerprint, cookies and logged-in sessions is created."
      : "Duplicate this profile? A new profile with the same settings and " +
        "fingerprint is created. Browser state (cookies, history) is not copied.";
    if (!confirm(message)) return;
    setDuplicating(true);
    try {
      await onDuplicate(includeBrowserState);
    } finally {
      setDuplicating(false);
    }
  };

  const randomizeSeed = () => {
    set("fingerprint_seed", Math.floor(Math.random() * 90000) + 10000);
  };

  const currentResolution = Object.entries(RESOLUTION_PRESETS).find(
    ([, v]) => v.width === form.screen_width && v.height === form.screen_height,
  )?.[0] ?? "custom";

  const addTag = () => {
    const tag = tagInput.trim();
    if (!tag) return;
    if (form.tags?.some((t) => t.tag === tag)) return;
    set("tags", [...(form.tags ?? []), { tag, color: tagColor }]);
    setTagInput("");
  };

  const removeTag = (tag: string) => {
    set("tags", (form.tags ?? []).filter((t) => t.tag !== tag));
  };

  const addLaunchArg = () => {
    const arg = launchArgInput.trim();
    if (!arg) return;
    if ((form.launch_args ?? []).includes(arg)) return;
    set("launch_args", [...(form.launch_args ?? []), arg]);
    setLaunchArgInput("");
  };

  const removeLaunchArg = (idx: number) => {
    set("launch_args", (form.launch_args ?? []).filter((_, i) => i !== idx));
  };

  return (
    <>
      <form onSubmit={handleSubmit} className="p-6 max-w-3xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold">
            {isEdit ? "Edit Profile" : "New Profile"}
          </h2>
          {isEdit && onDuplicate && (
            <div ref={duplicateMenuRef} className="relative flex items-stretch">
              <button
                type="button"
                onClick={() => handleDuplicate(false)}
                disabled={duplicating}
                title="Duplicate settings and fingerprint only"
                className="btn-secondary flex items-center gap-1.5 rounded-r-none"
              >
                <Copy className="h-3.5 w-3.5" />
                <span>{duplicating ? "Duplicating..." : "Duplicate"}</span>
              </button>
              <button
                ref={duplicateTriggerRef}
                type="button"
                onClick={() => setDuplicateMenuOpen((open) => !open)}
                disabled={duplicating}
                aria-haspopup="menu"
                aria-expanded={duplicateMenuOpen}
                aria-label="Duplicate options"
                className="btn-secondary flex items-center rounded-l-none border-l border-border px-2"
              >
                <ChevronDown className="h-3.5 w-3.5" />
              </button>
              {duplicateMenuOpen && (
                <div
                  role="menu"
                  className="absolute left-0 top-full z-20 mt-1 w-64 rounded-md border border-border bg-surface-2 py-1 shadow-lg"
                >
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => handleDuplicate(false)}
                    className="w-full px-3 py-2 text-left hover:bg-surface-3"
                  >
                    <div className="text-sm text-gray-200">Settings and fingerprint only</div>
                    <div className="text-xs text-gray-500">Starts with empty browser state</div>
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    disabled={profile?.status !== "stopped"}
                    onClick={() => handleDuplicate(true)}
                    className="w-full px-3 py-2 text-left hover:bg-surface-3 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-transparent"
                  >
                    <div className="text-sm text-gray-200">With browser state</div>
                    <div className="text-xs text-gray-500">
                      {profile?.status === "stopped"
                        ? "Cookies, logged-in sessions and history"
                        : "Stop the profile first"}
                    </div>
                  </button>
                </div>
              )}
            </div>
          )}
          {isEdit && onReset && (
            <button
              type="button"
              onClick={handleReset}
              disabled={resetting || resetDone}
              className="btn-secondary flex items-center gap-1.5"
            >
              {resetDone ? <Check className="h-3.5 w-3.5" /> : <RotateCcw className="h-3.5 w-3.5" />}
              <span>{resetDone ? "Reset done" : resetting ? "Resetting..." : "Reset"}</span>
            </button>
          )}
          {isEdit && onDelete && (
            <button
              type="button"
              onClick={handleDelete}
              disabled={deleting}
              className="btn-danger flex items-center gap-1.5"
            >
              <Trash2 className="h-3.5 w-3.5" />
              <span>{deleting ? "Deleting..." : "Delete"}</span>
            </button>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={onCancel} className="btn-secondary">
            Cancel
          </button>
          <button type="submit" disabled={saving || saved} className="btn-primary flex items-center gap-1.5">
            {saved ? <Check className="h-3.5 w-3.5" /> : <Save className="h-3.5 w-3.5" />}
            <span>{saved ? "Saved" : saving ? "Saving..." : isEdit ? "Save" : "Create"}</span>
          </button>
        </div>
      </div>

      <div className="space-y-5">
        {/* Last preview — the last frame captured before the browser stopped */}
        {isEdit && !previewError && (
          <section>
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Last preview</h3>
            <img
              src={`/api/profiles/${profile!.id}/screenshot?t=${previewBuster}`}
              onError={() => setPreviewError(true)}
              alt="Last browser preview"
              className="w-full rounded-md border border-border bg-surface-1 object-contain max-h-72"
            />
          </section>
        )}

        {/* Basic */}
        <section>
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Basic</h3>
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <label className="label">Profile Name</label>
              <input
                className="input"
                value={form.name}
                onChange={(e) => set("name", e.target.value)}
                placeholder="e.g. Amazon Seller #1"
                required
              />
            </div>
            <div className="col-span-2">
              <label className="label">Fingerprint Seed</label>
              <div className="flex gap-2">
                <input
                  className="input flex-1 no-spin"
                  type="number"
                  value={form.fingerprint_seed ?? ""}
                  onChange={(e) => set("fingerprint_seed", e.target.value ? Number(e.target.value) : null)}
                  placeholder="Auto (random)"
                />
                <button
                  type="button"
                  onClick={randomizeSeed}
                  className="btn-secondary px-2.5"
                  title="Randomize seed"
                >
                  <svg className="h-5 w-5" viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round">
                    {/* Right face - lightest */}
                    <polygon points="28,10 16,16 16,28 28,22" fill="currentColor" opacity="0.06" />
                    <polygon points="28,10 16,16 16,28 28,22" />
                    {/* Left face - medium shade */}
                    <polygon points="4,10 16,16 16,28 4,22" fill="currentColor" opacity="0.2" />
                    <polygon points="4,10 16,16 16,28 4,22" />
                    {/* Top face - brightest */}
                    <polygon points="16,3 28,10 16,16 4,10" fill="currentColor" opacity="0.1" />
                    <polygon points="16,3 28,10 16,16 4,10" />
                    {/* Dots on top face (3 - diagonal) */}
                    <circle cx="11.5" cy="8.5" r="1" fill="currentColor" opacity="0.7" />
                    <circle cx="16" cy="9.5" r="1" fill="currentColor" opacity="0.7" />
                    <circle cx="20.5" cy="10.5" r="1" fill="currentColor" opacity="0.7" />
                    {/* Dots on left face (5 - dice pattern) */}
                    <circle cx="7.5" cy="14" r="0.9" fill="currentColor" opacity="0.6" />
                    <circle cx="12.5" cy="16.5" r="0.9" fill="currentColor" opacity="0.6" />
                    <circle cx="10" cy="19" r="0.9" fill="currentColor" opacity="0.6" />
                    <circle cx="7.5" cy="22" r="0.9" fill="currentColor" opacity="0.6" />
                    <circle cx="12.5" cy="24.5" r="0.9" fill="currentColor" opacity="0.6" />
                    {/* Dots on right face (2 - diagonal) */}
                    <circle cx="20" cy="15" r="0.9" fill="currentColor" opacity="0.5" />
                    <circle cx="24" cy="20" r="0.9" fill="currentColor" opacity="0.5" />
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </section>

        {/* Network */}
        <section>
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Network</h3>
          <div className="space-y-3">
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center gap-2">
                  <label className="label mb-0">Proxy Protocol</label>
                  <button
                    type="button"
                    onClick={() => setIsProxyModalOpen(true)}
                    className="text-xs text-cyan-400 hover:text-cyan-300 underline font-medium flex items-center gap-1"
                  >
                    管理代理
                  </button>
                </div>
                <select
                  className="bg-gray-800 border border-gray-700 text-gray-200 text-xs rounded px-2 py-1 focus:outline-none focus:border-indigo-500 max-w-[260px] truncate"
                  value={
                    managedNodes.find((n) => n.raw_uri === form.proxy)
                      ? `node:${managedNodes.find((n) => n.raw_uri === form.proxy)!.id}`
                      : proxyType
                  }
                  onChange={(e) => {
                    const val = e.target.value;
                    if (val.startsWith("node:")) {
                      const nodeId = val.slice(5);
                      const node = managedNodes.find((n) => n.id === nodeId);
                      if (node) {
                        set("proxy", node.raw_uri);
                        setProxyType(detectProxyType(node.raw_uri));
                        setProxyTest(null);
                      }
                    } else {
                      setProxyType(val as any);
                      setProxyTest(null);
                    }
                  }}
                >
                  <optgroup label="自定义协议 / Custom">
                    <option value="standard">Standard (HTTP/SOCKS5)</option>
                    <option value="singbox_uri">Sing-box Node URI (VLESS/VMess/Hysteria2/TUIC)</option>
                    <option value="singbox_sub">Sing-box Subscription URL</option>
                    <option value="singbox_json">Sing-box Native JSON</option>
                  </optgroup>
                  {managedNodes.length > 0 && (
                    <optgroup label="已保存的节点 / Managed Nodes">
                      {managedNodes.map((n) => {
                        const subName = n.subscription_id ? subsMap.get(n.subscription_id) : null;
                        const prefix = subName ? `[${subName}]` : "[手动]";
                        return (
                          <option key={n.id} value={`node:${n.id}`}>
                            {prefix} {n.name} ({n.protocol.toUpperCase()})
                          </option>
                        );
                      })}
                    </optgroup>
                  )}
                </select>
              </div>

              {proxyType === "singbox_json" ? (
                <div className="space-y-2">
                  <textarea
                    className="input w-full font-mono text-xs h-28 resize-y"
                    value={form.proxy ?? ""}
                    onChange={(e) => {
                      set("proxy", e.target.value || null);
                      setProxyTest(null);
                    }}
                    placeholder={`{\n  "outbounds": [\n    {\n      "type": "vless",\n      "tag": "my-proxy",\n      "server": "example.com",\n      "server_port": 443,\n      "uuid": "your-uuid",\n      "tls": { "enabled": true }\n    }\n  ]\n}`}
                  />
                  <div className="flex justify-end gap-2">
                    <button
                      type="button"
                      className="btn-secondary text-xs whitespace-nowrap disabled:opacity-60 disabled:cursor-not-allowed flex items-center gap-1.5 text-indigo-300 hover:text-indigo-200"
                      onClick={handleMatchProxyGeo}
                      disabled={!form.proxy || matchingGeo || testingProxy}
                      title="根据当前代理节点的出口 IP 自动匹配并填入 Timezone 与 Locale"
                    >
                      {matchingGeo ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "⚡ 按 IP 匹配设置"}
                    </button>
                    <button
                      type="button"
                      className="btn-secondary text-xs whitespace-nowrap disabled:opacity-60 disabled:cursor-not-allowed flex items-center gap-1.5"
                      onClick={handleTestProxy}
                      disabled={!form.proxy || testingProxy || matchingGeo}
                    >
                      {testingProxy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                      Test
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex gap-2">
                  <input
                    className="input flex-1 font-mono text-xs"
                    value={form.proxy ?? ""}
                    onChange={(e) => {
                      set("proxy", e.target.value || null);
                      setProxyTest(null);
                      setGeoMatchMessage(null);
                    }}
                    placeholder={
                      proxyType === "singbox_uri"
                        ? "vless://uuid@host:443?type=ws&security=tls#node"
                        : proxyType === "singbox_sub"
                        ? "https://my-proxy-provider.com/sub/token"
                        : "http://user:pass@host:port"
                    }
                  />
                  <button
                    type="button"
                    className="btn-secondary text-xs whitespace-nowrap disabled:opacity-60 disabled:cursor-not-allowed flex items-center gap-1.5 text-indigo-300 hover:text-indigo-200"
                    onClick={handleMatchProxyGeo}
                    disabled={!form.proxy || matchingGeo || testingProxy}
                    title="根据当前代理节点的出口 IP 自动匹配并填入 Timezone 与 Locale"
                  >
                    {matchingGeo ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "⚡ 按 IP 匹配设置"}
                  </button>
                  <button
                    type="button"
                    className="btn-secondary text-xs whitespace-nowrap disabled:opacity-60 disabled:cursor-not-allowed flex items-center gap-1.5"
                    onClick={handleTestProxy}
                    disabled={!form.proxy || testingProxy || matchingGeo}
                  >
                    {testingProxy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                    Test
                  </button>
                </div>
              )}

              {proxyTest && !testingProxy && (
                <p
                  className={`text-xs mt-1 ${proxyTest.ok ? "text-emerald-400" : "text-red-400"}`}
                >
                  {proxyTest.ok
                    ? `✓ ${proxyTest.ip}` +
                      (proxyTest.city || proxyTest.country
                        ? ` · ${[proxyTest.city, proxyTest.country].filter(Boolean).join(", ")}`
                        : "") +
                      (proxyTest.latency_ms != null ? ` · ${proxyTest.latency_ms}ms` : "") +
                      (proxyTest.cached ? " (cached)" : "")
                    : proxyTest.error || "Proxy test failed"}
                </p>
              )}

              {geoMatchMessage && (
                <p className="text-xs mt-1 text-indigo-400 flex items-center gap-1">
                  <span>✓</span>
                  <span>{geoMatchMessage}</span>
                </p>
              )}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">Timezone</label>
                <input
                  className="input"
                  value={form.timezone ?? ""}
                  onChange={(e) => set("timezone", e.target.value || null)}
                  placeholder="America/New_York"
                />
              </div>
              <div>
                <label className="label">Locale</label>
                <input
                  className="input"
                  value={form.locale ?? ""}
                  onChange={(e) => set("locale", e.target.value || null)}
                  placeholder="en-US"
                />
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
              <input
                type="checkbox"
                checked={form.geoip ?? false}
                onChange={(e) => set("geoip", e.target.checked)}
                className="rounded border-border bg-surface-2"
              />
              Auto-detect timezone/locale from the proxy exit, or host public IP without a proxy (GeoIP)
            </label>
          </div>
        </section>

        {/* Hardware */}
        <section>
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Hardware</h3>
          <div className="space-y-3">
            <div>
              <label className="label">Screen Resolution</label>
              <select
                className="input"
                value={currentResolution}
                onChange={(e) => {
                  const preset = RESOLUTION_PRESETS[e.target.value];
                  if (preset) {
                    set("screen_width", preset.width);
                    set("screen_height", preset.height);
                  }
                }}
              >
                {Object.keys(RESOLUTION_PRESETS).map((name) => (
                  <option key={name} value={name}>{name}</option>
                ))}
                <option value="custom">Custom</option>
              </select>
            </div>
            {currentResolution === "custom" && (
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Width</label>
                  <input
                    className="input"
                    type="number"
                    value={form.screen_width ?? 1920}
                    onChange={(e) => set("screen_width", Number(e.target.value))}
                  />
                </div>
                <div>
                  <label className="label">Height</label>
                  <input
                    className="input"
                    type="number"
                    value={form.screen_height ?? 1080}
                    onChange={(e) => set("screen_height", Number(e.target.value))}
                  />
                </div>
              </div>
            )}
            <div>
              <label className="label">GPU Family</label>
              {hostOs === "macos" ? (
                <select className="input" value="auto" disabled>
                  <option value="auto">Apple Silicon (automatic)</option>
                </select>
              ) : hostOs === null ? (
                <select className="input" value="auto" disabled>
                  <option value="auto">Automatic (detecting runtime…)</option>
                </select>
              ) : (
                <select
                  className="input"
                  value={form.gpu_family ?? "auto"}
                  onChange={(e) => set("gpu_family", e.target.value as "auto" | "nvidia" | "intel")}
                >
                  <option value="auto">Auto (from seed)</option>
                  <option value="nvidia">NVIDIA</option>
                  <option value="intel">Intel</option>
                </select>
              )}
              <p className="text-xs text-gray-500 mt-1">
                {hostOs === "macos"
                  ? "The seed selects a coherent Apple Silicon model and matching hardware profile."
                  : "The seed selects a coherent GPU model, CPU, memory, and screen profile within the family."}
              </p>
            </div>
          </div>
        </section>

        {/* Behavior */}
        <section>
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Behavior</h3>
          <div className="space-y-3">
            <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
              <input
                type="checkbox"
                checked={form.humanize ?? false}
                onChange={(e) => set("humanize", e.target.checked)}
                className="rounded border-border bg-surface-2"
              />
              Human-like mouse, keyboard, and scroll behavior
            </label>
            {form.humanize && (
              <div>
                <label className="label">Human Preset</label>
                <select
                  className="input"
                  value={form.human_preset}
                  onChange={(e) => set("human_preset", e.target.value)}
                >
                  <option value="default">Default (normal speed)</option>
                  <option value="careful">Careful (slower, deliberate)</option>
                </select>
              </div>
            )}
            {viewerMode === "vnc" && (
              <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.clipboard_sync ?? true}
                  onChange={(e) => set("clipboard_sync", e.target.checked)}
                  className="rounded border-border bg-surface-2"
                />
                Enable clipboard sync by default in VNC viewer
              </label>
            )}
            <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
              <input
                type="checkbox"
                checked={form.auto_launch ?? false}
                onChange={(e) => set("auto_launch", e.target.checked)}
                className="rounded border-border bg-surface-2"
              />
              Launch automatically when Manager starts
            </label>
            <label className="flex items-start gap-2 text-sm text-gray-300 cursor-pointer">
              <input
                type="checkbox"
                checked={form.capture_preview ?? true}
                onChange={(e) => set("capture_preview", e.target.checked)}
                className="rounded border-border bg-surface-2 mt-0.5"
              />
              <span>
                Save a preview screenshot of the browser
                <span className="block text-xs text-gray-500">
                  Captures the page periodically while running, shown here after the profile stops.
                </span>
              </span>
            </label>
            <label className="flex items-start gap-2 text-sm text-gray-300 cursor-pointer">
              <input
                type="checkbox"
                checked={form.restore_session ?? true}
                onChange={(e) => set("restore_session", e.target.checked)}
                className="rounded border-border bg-surface-2 mt-0.5"
              />
              <span>
                Restore previous tabs on launch
                <span className="block text-xs text-gray-500">
                  Reopens the tabs that were open when this profile was last stopped.
                </span>
              </span>
            </label>
          </div>
        </section>

        {/* Compatibility */}
        <section>
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Compatibility</h3>
          <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
            <input
              type="checkbox"
              checked={form.allow_3p_cookies ?? false}
              onChange={(e) => set("allow_3p_cookies", e.target.checked)}
              className="rounded border-border bg-surface-2"
            />
            Allow third-party cookies for login, SSO, and challenge flows
          </label>
          <label className="flex items-start gap-2 text-sm text-gray-300 cursor-pointer mt-3">
            <input
              type="checkbox"
              checked={form.set_google_default ?? true}
              onChange={(e) => set("set_google_default", e.target.checked)}
              className="rounded border-border bg-surface-2 mt-0.5"
            />
            <span>
              Set Google as the default search engine
              <span className="block text-xs text-gray-500">
                Adds a few seconds to the profile's first launch (one-time setup).
              </span>
            </span>
          </label>
        </section>

        {/* Tags */}
        <section>
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Tags</h3>
          {(form.tags ?? []).length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-3">
              {(form.tags ?? []).map((t) => (
                <span
                  key={t.tag}
                  className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-surface-3 text-gray-300"
                  style={t.color ? { backgroundColor: `${t.color}20`, color: t.color } : undefined}
                >
                  {t.tag}
                  <button
                    type="button"
                    onClick={() => removeTag(t.tag)}
                    className="hover:opacity-70"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
            </div>
          )}
          <div className="flex gap-2 items-center">
            <div className="flex gap-1">
              {TAG_COLORS.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setTagColor(c)}
                  className="w-4 h-4 rounded-full border-2 transition-transform"
                  style={{
                    backgroundColor: c,
                    borderColor: tagColor === c ? "#fff" : "transparent",
                    transform: tagColor === c ? "scale(1.2)" : undefined,
                  }}
                />
              ))}
            </div>
            <input
              className="input flex-1"
              value={tagInput}
              onChange={(e) => setTagInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTag(); } }}
              placeholder="Add tag..."
            />
            <button type="button" onClick={addTag} className="btn-secondary text-xs">
              Add
            </button>
          </div>
        </section>

        {/* Extensions */}
        <section>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
              Chrome Extensions / 扩展插件
            </h3>
            <span className="text-[11px] text-gray-500">
              {installedExtensions.length > 0
                ? `${(form.extension_paths ?? []).length} / ${installedExtensions.length} selected`
                : "No extensions in library"}
            </span>
          </div>

          <p className="text-xs text-gray-500 mb-3">
            默认全选所有已安装插件，可点击下拉框取消添加或自定义勾选。
          </p>

          {/* Multi-select dropdown */}
          <div className="relative mb-3" ref={extDropdownRef}>
            <button
              type="button"
              onClick={() => setExtDropdownOpen(!extDropdownOpen)}
              className="w-full input flex items-center justify-between py-2 text-left cursor-pointer hover:border-gray-600 transition"
            >
              <div className="flex items-center gap-2 min-w-0 flex-1">
                <Puzzle className="h-4 w-4 text-amber-400 shrink-0" />
                <span className="text-xs text-gray-200 truncate">
                  {(form.extension_paths ?? []).length > 0
                    ? `已勾选 ${(form.extension_paths ?? []).length} 个插件 (点击展开选择)`
                    : "未选择任何插件 (点击展开选择)"}
                </span>
              </div>
              {extDropdownOpen ? (
                <ChevronUp className="h-4 w-4 text-gray-400 shrink-0" />
              ) : (
                <ChevronDown className="h-4 w-4 text-gray-400 shrink-0" />
              )}
            </button>

            {extDropdownOpen && (
              <div className="absolute left-0 right-0 top-full mt-1.5 z-40 bg-gray-900 border border-gray-700 rounded-lg shadow-2xl p-2 max-h-72 flex flex-col">
                {/* Search & quick actions */}
                <div className="flex items-center gap-2 pb-2 border-b border-gray-800">
                  <div className="relative flex-1">
                    <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-gray-500" />
                    <input
                      type="text"
                      placeholder="Filter extensions..."
                      value={extSearch}
                      onChange={(e) => setExtSearch(e.target.value)}
                      className="input w-full pl-7 py-1 text-xs"
                      onClick={(e) => e.stopPropagation()}
                    />
                  </div>
                  <button
                    type="button"
                    onClick={selectAllExtensions}
                    className="text-[10px] text-indigo-400 hover:text-indigo-300 font-medium px-1.5 py-1 rounded hover:bg-gray-800"
                  >
                    全选
                  </button>
                  <button
                    type="button"
                    onClick={clearAllExtensions}
                    className="text-[10px] text-gray-400 hover:text-gray-200 font-medium px-1.5 py-1 rounded hover:bg-gray-800"
                  >
                    清空
                  </button>
                </div>

                {/* List of installed extensions */}
                <div className="flex-1 overflow-y-auto py-1 space-y-1">
                  {installedExtensions.length === 0 ? (
                    <div className="text-center py-4 text-gray-500 text-xs">
                      插件库暂无扩展，请在顶部导航栏点击 🧩 管理扩展 进行安装。
                    </div>
                  ) : (
                    installedExtensions
                      .filter(
                        (e) =>
                          e.name.toLowerCase().includes(extSearch.toLowerCase()) ||
                          (e.description || "").toLowerCase().includes(extSearch.toLowerCase())
                      )
                      .map((ext) => {
                        const isSelected = (form.extension_paths ?? []).includes(ext.path);
                        return (
                          <div
                            key={ext.id}
                            onClick={() => toggleExtension(ext.path)}
                            className={`p-2 rounded-md cursor-pointer flex items-center justify-between gap-2 transition ${
                              isSelected
                                ? "bg-indigo-950/50 text-white"
                                : "hover:bg-gray-800 text-gray-300"
                            }`}
                          >
                            <div className="flex items-center gap-2.5 min-w-0 flex-1">
                              <input
                                type="checkbox"
                                checked={isSelected}
                                onChange={() => {}}
                                className="rounded border-gray-700 text-indigo-600 focus:ring-0"
                              />
                              {ext.icon_url ? (
                                <img
                                  src={ext.icon_url}
                                  alt={ext.name}
                                  className="h-5 w-5 rounded object-contain shrink-0"
                                />
                              ) : (
                                <div className="h-5 w-5 rounded bg-indigo-950 flex items-center justify-center text-[10px] font-bold text-indigo-300 shrink-0">
                                  🧩
                                </div>
                              )}
                              <div className="min-w-0 flex-1">
                                <div className="text-xs font-medium truncate">{ext.name}</div>
                                <div className="text-[10px] text-gray-400 truncate">v{ext.version}</div>
                              </div>
                            </div>
                          </div>
                        );
                      })
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Selected extension chips */}
          {(form.extension_paths ?? []).length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-3">
              {(form.extension_paths ?? []).map((path) => {
                const ext = installedExtensions.find((e) => e.path === path);
                const displayName = ext ? ext.name : path.split("/").pop() || path;
                return (
                  <span
                    key={path}
                    className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full bg-indigo-950/60 border border-indigo-800/50 text-indigo-200"
                  >
                    {ext?.icon_url ? (
                      <img src={ext.icon_url} alt="" className="h-3.5 w-3.5 object-contain" />
                    ) : (
                      <Puzzle className="h-3 w-3 text-indigo-400" />
                    )}
                    <span className="truncate max-w-[160px]">{displayName}</span>
                    <button
                      type="button"
                      onClick={() => removeExtensionPath(path)}
                      className="hover:text-white transition"
                      title="Remove"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                );
              })}
            </div>
          )}
        </section>

        {/* Advanced */}
        <details className="rounded-md border border-border bg-surface-1 p-3">
          <summary className="cursor-pointer text-xs font-semibold text-gray-400 uppercase tracking-wider">
            Advanced launch arguments
          </summary>
          <p className="text-xs text-gray-500 my-3">
            Unrestricted Chromium flags. Advanced arguments can override Manager-controlled behavior.
          </p>
          {(form.launch_args ?? []).length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-3">
              {(form.launch_args ?? []).map((arg, index) => (
                <span
                  key={`${arg}-${index}`}
                  className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-surface-3 text-gray-300 font-mono"
                >
                  {arg}
                  <button type="button" onClick={() => removeLaunchArg(index)} className="hover:opacity-70">
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
            </div>
          )}
          <div className="flex gap-2">
            <input
              className="input flex-1 font-mono"
              value={launchArgInput}
              onChange={(e) => setLaunchArgInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addLaunchArg(); } }}
              placeholder="--disable-features=Foo"
            />
            <button type="button" onClick={addLaunchArg} className="btn-secondary text-xs">Add</button>
          </div>
        </details>

        {/* Notes */}
        <section>
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Notes</h3>
          <textarea
            className="input min-h-[80px] resize-y"
            value={form.notes ?? ""}
            onChange={(e) => set("notes", e.target.value || null)}
            placeholder="Optional notes about this profile..."
          />
        </section>
      </div>

    </form>
    <ProxyManagerModal
      isOpen={isProxyModalOpen}
      onClose={() => setIsProxyModalOpen(false)}
      onNodesChanged={loadManagedProxies}
    />
  </>
  );
}
