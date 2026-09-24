import { AlertTriangle, Check, ChevronDown, ChevronRight, ChevronUp, Copy, Globe, Loader2, Network, Plus, Puzzle, RotateCcw, Save, Search, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import type {
  Extension,
  HostOS,
  KernelItem,
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
  extensionsUpdated?: number;
  kernelsUpdated?: number;
  onOpenKernelManager?: () => void;
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

const ARG_PRESETS = [
  { label: "忽略扩展禁用", arg: "ignore: --disable-extensions", tip: "允许加载 Chrome 扩展插件（已勾选插件时会自动添加并生效）" },
  { label: "去除自动化特征", arg: "--disable-blink-features=AutomationControlled", tip: "避免被检测到 navigator.webdriver 等自动化特征" },
  { label: "跳过首次运行", arg: "--no-first-run", tip: "跳过首次启动向导与测试，防止首次运行特征暴露" },
  { label: "禁用默认浏览器检查", arg: "--no-default-browser-check", tip: "禁止弹出默认浏览器设置提示" },
  { label: "阻止后台网络探测", arg: "--disable-background-networking", tip: "防止浏览器后台发起自发性网络请求与上报" },
  { label: "阻止组件自动更新", arg: "--disable-component-update", tip: "保持浏览器组件版本与指纹一致" },
  { label: "禁用网页通知", arg: "--disable-notifications", tip: "阻止网页弹窗申请通知权限" },
  { label: "窗口最大化启动", arg: "--start-maximized", tip: "窗口最大化以模拟真实桌面用户行为" },
  { label: "静音所有标签", arg: "--mute-audio", tip: "静音浏览器所有声音输出" },
  { label: "禁用域可靠性监控", arg: "--disable-domain-reliability", tip: "防止向 Google 上报网络错误与可靠性监测" },
];

export function ProfileForm({
  profile,
  hostOs,
  viewerMode,
  onSave,
  onDelete,
  onReset,
  onDuplicate,
  onCancel,
  extensionsUpdated,
  kernelsUpdated,
  onOpenKernelManager,
}: ProfileFormProps) {
  const isEdit = profile !== null;

  const [form, setForm] = useState<ProfileCreateData>({
    name: "",
    browser_version: profile?.browser_version ?? null,
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
    search_engine_name: "Google",
    search_engine_keyword: "google.com",
    search_engine_url: "https://www.google.com/search?q=%s",
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
  const [proxyDropdownOpen, setProxyDropdownOpen] = useState(false);
  const [proxySearch, setProxySearch] = useState("");
  const [expandedSubIds, setExpandedSubIds] = useState<Set<string>>(new Set());
  const proxyDropdownRef = useRef<HTMLDivElement>(null);

  const toggleExpandGroup = (groupId: string) => {
    setExpandedSubIds((prev) => {
      const next = new Set(prev);
      if (next.has(groupId)) {
        next.delete(groupId);
      } else {
        next.add(groupId);
      }
      return next;
    });
  };

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
      if (proxyDropdownRef.current && !proxyDropdownRef.current.contains(e.target as Node)) {
        setProxyDropdownOpen(false);
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
  }, [extensionsUpdated]);

  const [installedKernels, setInstalledKernels] = useState<KernelItem[]>([]);
  const [kernelsLoading, setKernelsLoading] = useState(false);

  const loadInstalledKernels = useCallback(async () => {
    setKernelsLoading(true);
    try {
      const res = await api.listKernels();
      setInstalledKernels(res.kernels.filter((k) => k.installed));
    } catch (err) {
      console.error("Failed to load kernels in form:", err);
    } finally {
      setKernelsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadInstalledKernels();
  }, [loadInstalledKernels, kernelsUpdated]);

  const [licenses, setLicenses] = useState<{ id: string; name: string; is_default: boolean }[]>([]);
  useEffect(() => {
    api.getSettings().then((s) => {
      setLicenses(s.licenses || []);
      // Auto-select default license for new profiles if they don't have one set yet
      if (!isEdit && !form.license_id) {
        const def = (s.licenses || []).find(l => l.is_default);
        if (def) {
          setForm(prev => ({ ...prev, license_id: def.id }));
        }
      }
    }).catch((err) => console.error("Failed to load settings:", err));
  }, [isEdit]);

  const prevProfileIdRef = useRef<string | null | undefined>(undefined);

  useEffect(() => {
    if (profile) {
      if (prevProfileIdRef.current !== profile.id) {
        prevProfileIdRef.current = profile.id;
        setForm({
          name: profile.name,
          browser_version: profile.browser_version ?? null,
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
          search_engine_name: profile.search_engine_name ?? "Google",
          search_engine_keyword: profile.search_engine_keyword ?? "google.com",
          search_engine_url: profile.search_engine_url ?? "https://www.google.com/search?q=%s",
          capture_preview: profile.capture_preview,
          restore_session: profile.restore_session,
          launch_args: profile.launch_args ?? [],
          notes: profile.notes,
          tags: profile.tags,
          license_id: profile.license_id ?? null,
        });
        setProxyType(detectProxyType(profile.proxy));
        setPreviewError(false);
        setPreviewBuster(Date.now());
      }
    } else {
      if (prevProfileIdRef.current !== null) {
        prevProfileIdRef.current = null;
        setForm({
          name: "",
          browser_version: null,
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
          search_engine_name: "Google",
          search_engine_keyword: "google.com",
          search_engine_url: "https://www.google.com/search?q=%s",
          capture_preview: true,
          restore_session: true,
          extension_paths: installedExtensions.map((e) => e.path),
          launch_args: [],
        });
        setPreviewError(false);
        setPreviewBuster(Date.now());
      }
    }
  }, [profile?.id]);

  useEffect(() => {
    // If native mode forces host OS to mac/windows, reset any incompatible GPU selection
    if (hostOs === "macos" && form.gpu_family !== "auto") {
      setForm((previous) => ({ ...previous, gpu_family: "auto" }));
    }
  }, [hostOs]);

  const set = <K extends keyof ProfileCreateData>(key: K, value: ProfileCreateData[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const toggleExtension = (extPath: string) => {
    const current = form.extension_paths ?? [];
    let updatedPaths: string[];
    if (current.includes(extPath)) {
      updatedPaths = current.filter((p) => p !== extPath);
    } else {
      updatedPaths = [...current, extPath];
    }
    set("extension_paths", updatedPaths);

    // Keep --load-extension and ignore: --disable-extensions in launch_args in sync
    let currentArgs = form.launch_args ?? [];
    const hasLoadExt = currentArgs.some((a) => a.startsWith("--load-extension="));
    if (hasLoadExt) {
      if (updatedPaths.length > 0) {
        const newArg = `--load-extension=${updatedPaths.join(",")}`;
        currentArgs = currentArgs.map((a) => (a.startsWith("--load-extension=") ? newArg : a));
      } else {
        currentArgs = currentArgs.filter((a) => !a.startsWith("--load-extension=") && !a.startsWith("--disable-extensions-except="));
      }
    }
    if (updatedPaths.length > 0) {
      if (!currentArgs.includes("ignore: --disable-extensions")) {
        currentArgs = [...currentArgs, "ignore: --disable-extensions"];
      }
    } else {
      currentArgs = currentArgs.filter((a) => a !== "ignore: --disable-extensions");
    }
    set("launch_args", currentArgs);
  };

  const selectAllExtensions = () => {
    const allPaths = Array.from(
      new Set([...(form.extension_paths ?? []), ...installedExtensions.map((e) => e.path)])
    );
    set("extension_paths", allPaths);
    let currentArgs = form.launch_args ?? [];
    const hasLoadExt = currentArgs.some((a) => a.startsWith("--load-extension="));
    if (hasLoadExt && allPaths.length > 0) {
      const newArg = `--load-extension=${allPaths.join(",")}`;
      currentArgs = currentArgs.map((a) => (a.startsWith("--load-extension=") ? newArg : a));
    }
    if (allPaths.length > 0 && !currentArgs.includes("ignore: --disable-extensions")) {
      currentArgs = [...currentArgs, "ignore: --disable-extensions"];
    }
    set("launch_args", currentArgs);
  };

  const clearAllExtensions = () => {
    set("extension_paths", []);
    const currentArgs = form.launch_args ?? [];
    set(
      "launch_args",
      currentArgs.filter(
        (a) =>
          !a.startsWith("--load-extension=") &&
          !a.startsWith("--disable-extensions-except=") &&
          a !== "ignore: --disable-extensions"
      )
    );
  };

  const removeExtensionPath = (pathToRemove: string) => {
    toggleExtension(pathToRemove);
  };

  const [matchingGeo, setMatchingGeo] = useState(false);
  const [geoMatchMessage, setGeoMatchMessage] = useState<string | null>(null);

  const handleMatchProxyGeo = async () => {
    setMatchingGeo(true);
    setGeoMatchMessage(null);
    try {
      const res = await api.testProxy(form.proxy, form.proxy ? proxyType : "direct");
      setProxyTest(res);
      if (!res.ok) {
        alert(`无法获取网络 IP 信息: ${res.error || "连接失败"}`);
        return;
      }
      const newTz = res.timezone || null;
      const newLoc = res.locale || null;

      if (!newTz && !newLoc) {
        alert(`已解析出口 IP (${res.ip})，但未在 IP 数据库中查询到对应的时区或语言信息。`);
        return;
      }

      const hasExistingTz = Boolean(form.timezone && form.timezone.trim());
      const hasExistingLoc = Boolean(form.locale && form.locale.trim());

      if ((hasExistingTz && form.timezone !== newTz) || (hasExistingLoc && form.locale !== newLoc)) {
        const confirmMsg =
          `检测到已设置的时区/语言配置：\n` +
          `· 时区: ${form.timezone || "未设置"} -> ${newTz || "未匹配"}\n` +
          `· 语言: ${form.locale || "未设置"} -> ${newLoc || "未匹配"}\n\n` +
          `是否确认按出口 IP (${res.ip}) 覆盖现有设置？`;
        if (!window.confirm(confirmMsg)) {
          return;
        }
      }

      if (newTz) set("timezone", newTz);
      if (newLoc) set("locale", newLoc);
      setGeoMatchMessage(`已按出口 IP (${res.ip}) 匹配设置: 时区 ${newTz || "-"} / 语言 ${newLoc || "-"}`);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "匹配地理信息失败";
      alert(`匹配失败: ${message}`);
    } finally {
      setMatchingGeo(false);
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

  const isSelectedKernelMissing = Boolean(
    form.browser_version &&
    installedKernels.length > 0 &&
    !installedKernels.some((k) => k.version === form.browser_version)
  );

  const isOldKernel = Boolean(
    form.browser_version &&
    ["144.", "145.", "146.", "147."].some((prefix) => form.browser_version?.startsWith(prefix))
  );

  const hasInlineProxyAuthArg = (form.launch_args ?? []).some(
    (arg) => arg.startsWith("--proxy-server=") && arg.includes("@")
  );

  const addLaunchArg = (customArg?: string) => {
    const raw = (customArg || launchArgInput).trim();
    if (!raw) return;
    const current = form.launch_args ?? [];
    if (!current.includes(raw)) {
      set("launch_args", [...current, raw]);

      // If user adds --load-extension=<paths>, auto-select matching installed extensions
      if (raw.startsWith("--load-extension=")) {
        const rawPaths = raw.replace("--load-extension=", "").split(",").map((p) => p.trim());
        const validExtPaths = installedExtensions
          .filter((e) => rawPaths.some((p) => p === e.path || p.endsWith(e.id)))
          .map((e) => e.path);
        if (validExtPaths.length > 0) {
          const merged = Array.from(new Set([...(form.extension_paths ?? []), ...validExtPaths]));
          set("extension_paths", merged);
        }
      }
    }
    if (!customArg) setLaunchArgInput("");
  };

  const removeLaunchArg = (idx: number) => {
    const current = form.launch_args ?? [];
    const removed = current[idx];
    set("launch_args", current.filter((_, i) => i !== idx));

    // If user removes --load-extension, uncheck matching extensions in form
    if (removed && removed.startsWith("--load-extension=")) {
      const rawPaths = removed.replace("--load-extension=", "").split(",").map((p) => p.trim());
      const remainingExtPaths = (form.extension_paths ?? []).filter(
        (p) => !rawPaths.some((rp) => rp === p || rp.endsWith(p.split("/").pop() || ""))
      );
      set("extension_paths", remainingExtPaths);
    }
  };

  const selectedManagedNode = managedNodes.find((n) => n.raw_uri === form.proxy);

  const groupedSubscriptions = Array.from(subsMap.entries())
    .map(([subId, subName]) => ({
      id: subId,
      name: subName,
      nodes: managedNodes.filter((n) => n.subscription_id === subId),
    }))
    .filter((g) => g.nodes.length > 0);

  const manualNodes = managedNodes.filter((n) => !n.subscription_id);

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
              <label className="label">绑定 License 授权 (License Binding)</label>
              <select
                className="input"
                value={form.license_id ?? ""}
                onChange={(e) => set("license_id", e.target.value ? e.target.value : null)}
              >
                <option value="">Keyless (无授权) / 免费内核模式</option>
                {licenses.map(l => (
                  <option key={l.id} value={l.id}>
                    {l.name} {l.is_default ? "(默认)" : ""}
                  </option>
                ))}
              </select>
              <p className="text-[11px] text-gray-500 mt-1.5">
                可选择列表管理中的 License。如果没有选择，则回退到无 License (Keyless) 的免费内核模式。
              </p>
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
            <div className="col-span-2">
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center gap-2">
                  <label className="label mb-0">Chromium 内核版本 (Kernel Version)</label>
                  {kernelsLoading && <Loader2 className="h-3 w-3 animate-spin text-gray-500" />}
                </div>
                {onOpenKernelManager && (
                  <button
                    type="button"
                    onClick={onOpenKernelManager}
                    className="text-xs text-indigo-400 hover:text-indigo-300 font-medium flex items-center gap-1"
                  >
                    <Plus className="h-3 w-3" />
                    管理/下载更多内核
                  </button>
                )}
              </div>
              <select
                className="input"
                value={form.browser_version ?? ""}
                onChange={(e) => set("browser_version", e.target.value ? e.target.value : null)}
              >
                <option value="">默认推荐 (跟随系统默认/最新内核)</option>
                {isSelectedKernelMissing && (
                  <option value={form.browser_version!} disabled>
                    ⚠️ v{form.browser_version} (本地已删除 - 启动将自动回退)
                  </option>
                )}
                {installedKernels.map((k) => (
                  <option key={k.version} value={k.version}>
                    {k.name} (v{k.version}) - {k.tier === "free" ? "免费无限制" : "Pro 授权"}
                  </option>
                ))}
              </select>

              {isSelectedKernelMissing && (
                <div className="mt-2 p-2.5 rounded-lg bg-amber-950/40 border border-amber-600/50 flex items-start gap-2 text-xs text-amber-300">
                  <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400 mt-0.5" />
                  <div>
                    <p className="font-medium">
                      该环境绑定的内核版本 (v{form.browser_version}) 本地已被删除或不存在。
                    </p>
                    <p className="text-[11px] text-amber-400/80 mt-0.5">
                      启动时系统将遵循安全策略自动回退到默认可用内核，您也可以在此重新选择其它已安装内核。
                    </p>
                  </div>
                </div>
              )}

              <p className="text-[11px] text-gray-500 mt-1.5">
                官方稳定版 (v145) 为免费内核，不受 Pro 授权与席位并发限制；如需更高级指纹防护可选用 Pro 内核。
              </p>
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
                  <label className="label mb-0">Proxy Node</label>
                  <span className="text-[10px] text-gray-500 font-normal">
                    (代理管理已导入节点)
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => setIsProxyModalOpen(true)}
                  className="text-xs text-cyan-400 hover:text-cyan-300 underline font-medium flex items-center gap-1"
                >
                  <Plus className="h-3 w-3" />
                  管理代理
                </button>
              </div>

              {/* Unified Proxy Selector & Match Button */}
              <div className="flex gap-2 items-center">
                <div className="relative flex-1" ref={proxyDropdownRef}>
                  <button
                    type="button"
                    aria-label="Proxy node"
                    onClick={() => {
                      if (!proxyDropdownOpen) {
                        if (selectedManagedNode?.subscription_id) {
                          setExpandedSubIds(new Set([selectedManagedNode.subscription_id]));
                        } else if (selectedManagedNode && !selectedManagedNode.subscription_id) {
                          setExpandedSubIds(new Set(["__manual__"]));
                        }
                      }
                      setProxyDropdownOpen(!proxyDropdownOpen);
                    }}
                    className="w-full input flex items-center justify-between py-2 text-left cursor-pointer hover:border-gray-600 transition"
                  >
                    {!form.proxy ? (
                      <div className="flex items-center gap-2 min-w-0 flex-1">
                        <Globe className="h-4 w-4 text-emerald-400 shrink-0" />
                        <span className="text-xs text-gray-200 truncate">
                          🌐 纯直连 / Direct (强制跳过系统代理)
                        </span>
                      </div>
                    ) : selectedManagedNode ? (
                      <div className="flex items-center gap-2 min-w-0 flex-1">
                        <Network className="h-4 w-4 text-indigo-400 shrink-0" />
                        <div className="min-w-0 flex-1 truncate text-xs text-gray-200">
                          {selectedManagedNode.subscription_id && subsMap.get(selectedManagedNode.subscription_id) && (
                            <span className="text-indigo-300 font-medium mr-1.5">
                              [{subsMap.get(selectedManagedNode.subscription_id)}]
                            </span>
                          )}
                          <span>{selectedManagedNode.name}</span>
                        </div>
                      </div>
                    ) : (
                      <div className="flex items-center gap-2 min-w-0 flex-1">
                        <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0" />
                        <span className="text-xs text-amber-300 truncate">
                          自定义代理配置 (未导入代理管理)
                        </span>
                      </div>
                    )}

                    <div className="flex items-center gap-1.5 shrink-0 ml-2">
                      {!form.proxy ? (
                        <span className="text-emerald-400 font-medium text-[10px] bg-emerald-950/60 border border-emerald-800/50 rounded px-1.5 py-0.5">
                          直连模式
                        </span>
                      ) : selectedManagedNode ? (
                        <span className="text-indigo-400 font-semibold text-[10px] bg-indigo-950/60 border border-indigo-800/50 rounded px-1.5 py-0.5 uppercase">
                          {selectedManagedNode.protocol}
                        </span>
                      ) : (
                        <span className="text-amber-400 font-medium text-[10px] bg-amber-950/60 border border-amber-800/50 rounded px-1.5 py-0.5 uppercase">
                          {proxyType}
                        </span>
                      )}
                      {proxyDropdownOpen ? (
                        <ChevronUp className="h-4 w-4 text-gray-400 shrink-0" />
                      ) : (
                        <ChevronDown className="h-4 w-4 text-gray-400 shrink-0" />
                      )}
                    </div>
                  </button>

                  {/* Dropdown popup */}
                  {proxyDropdownOpen && (
                    <div className="absolute left-0 right-0 top-full mt-1.5 z-40 bg-gray-900 border border-gray-700 rounded-lg shadow-2xl p-2 max-h-80 flex flex-col">
                      {/* Search box & quick expand/collapse */}
                      <div className="flex items-center gap-2 pb-2 border-b border-gray-800">
                        <div className="relative flex-1">
                          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-500" />
                          <input
                            type="text"
                            placeholder="搜索节点名称、订阅或协议..."
                            value={proxySearch}
                            onChange={(e) => setProxySearch(e.target.value)}
                            className="input w-full pl-8 py-1.5 text-xs"
                            onClick={(e) => e.stopPropagation()}
                            autoFocus
                          />
                        </div>
                        {groupedSubscriptions.length > 1 && (
                          <button
                            type="button"
                            onClick={() => {
                              if (expandedSubIds.size > 0) {
                                setExpandedSubIds(new Set());
                              } else {
                                setExpandedSubIds(
                                  new Set([...groupedSubscriptions.map((g) => g.id), "__manual__"])
                                );
                              }
                            }}
                            className="text-[10px] text-indigo-400 hover:text-indigo-300 font-medium px-2 py-1 rounded hover:bg-gray-800 shrink-0 whitespace-nowrap"
                          >
                            {expandedSubIds.size > 0 ? "全部折叠" : "全部展开"}
                          </button>
                        )}
                      </div>

                      {/* Options list */}
                      <div className="flex-1 overflow-y-auto py-1 space-y-1">
                        {/* Direct connection option */}
                        <div
                          onClick={() => {
                            set("proxy", null);
                            setProxyTest(null);
                            setGeoMatchMessage(null);
                            setProxyDropdownOpen(false);
                          }}
                          className={`p-2 rounded-md cursor-pointer flex items-center justify-between gap-2 transition ${
                            !form.proxy
                              ? "bg-emerald-950/50 border border-emerald-800/40 text-white"
                              : "hover:bg-gray-800 text-gray-300"
                          }`}
                        >
                          <div className="flex items-center gap-2 min-w-0">
                            <Globe className="h-4 w-4 text-emerald-400 shrink-0" />
                            <div className="min-w-0">
                              <div className="text-xs font-medium text-emerald-300">
                                🌐 纯直连 / Direct
                              </div>
                              <div className="text-[10px] text-gray-400">
                                强制跳过系统代理 (--no-proxy-server)，使用本机真实网络直连
                              </div>
                            </div>
                          </div>
                          {!form.proxy && <Check className="h-4 w-4 text-emerald-400 shrink-0" />}
                        </div>

                        {/* Custom configuration indicator if unmanaged */}
                        {form.proxy && !selectedManagedNode && (
                          <div className="p-2 rounded-md bg-amber-950/40 border border-amber-800/40 flex items-center justify-between text-xs text-amber-300">
                            <div className="flex items-center gap-2 min-w-0">
                              <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0" />
                              <span className="truncate font-mono">⚠️ 自定义配置 ({proxyType})</span>
                            </div>
                            <Check className="h-4 w-4 text-amber-400 shrink-0" />
                          </div>
                        )}

                        {/* Subscription groups (collapsible accordion) */}
                        {groupedSubscriptions.map((group) => {
                          const query = proxySearch.trim().toLowerCase();
                          const filteredNodes = group.nodes.filter(
                            (n) =>
                              !query ||
                              n.name.toLowerCase().includes(query) ||
                              n.protocol.toLowerCase().includes(query) ||
                              group.name.toLowerCase().includes(query)
                          );
                          if (filteredNodes.length === 0) return null;
                          const isExpanded = query.length > 0 || expandedSubIds.has(group.id);
                          const containsSelected = group.nodes.some((n) => n.raw_uri === form.proxy);

                          return (
                            <div key={group.id} className="pt-1.5">
                              <div
                                onClick={() => toggleExpandGroup(group.id)}
                                className={`px-2.5 py-1.5 rounded cursor-pointer flex items-center justify-between transition select-none ${
                                  containsSelected
                                    ? "bg-indigo-950/40 text-indigo-200 hover:bg-indigo-950/60"
                                    : "hover:bg-gray-800 text-gray-300"
                                }`}
                              >
                                <div className="flex items-center gap-1.5 min-w-0 flex-1">
                                  {isExpanded ? (
                                    <ChevronDown className="h-3.5 w-3.5 text-gray-400 shrink-0" />
                                  ) : (
                                    <ChevronRight className="h-3.5 w-3.5 text-gray-400 shrink-0" />
                                  )}
                                  <span className="text-xs font-medium truncate">📁 订阅: {group.name}</span>
                                </div>
                                <div className="flex items-center gap-1.5 shrink-0 ml-2">
                                  {containsSelected && (
                                    <span className="text-[10px] text-indigo-400 bg-indigo-950 border border-indigo-800/60 px-1 py-0.2 rounded font-medium">
                                      当前选择
                                    </span>
                                  )}
                                  <span className="text-[10px] text-gray-500 bg-gray-800/80 px-1.5 py-0.5 rounded">
                                    {filteredNodes.length}个节点
                                  </span>
                                </div>
                              </div>

                              {isExpanded && (
                                <div className="pl-3.5 pr-1 py-0.5 space-y-0.5 border-l border-gray-800 ml-4 mt-0.5">
                                  {filteredNodes.map((n) => {
                                    const isSelected = form.proxy === n.raw_uri;
                                    return (
                                      <div
                                        key={n.id}
                                        onClick={() => {
                                          set("proxy", n.raw_uri);
                                          setProxyType(detectProxyType(n.raw_uri));
                                          setProxyTest(null);
                                          setGeoMatchMessage(null);
                                          setProxyDropdownOpen(false);
                                        }}
                                        className={`px-2.5 py-1.5 rounded cursor-pointer flex items-center justify-between gap-2 transition ${
                                          isSelected
                                            ? "bg-indigo-950/70 border border-indigo-800/60 text-white"
                                            : "hover:bg-gray-800/80 text-gray-300"
                                        }`}
                                      >
                                        <div className="flex items-center gap-2 min-w-0 flex-1">
                                          <span className="text-[10px] uppercase font-bold text-indigo-400 bg-indigo-950/80 px-1.5 py-0.5 rounded shrink-0">
                                            {n.protocol}
                                          </span>
                                          <span className="text-xs truncate">{n.name}</span>
                                        </div>
                                        {isSelected && (
                                          <Check className="h-3.5 w-3.5 text-indigo-400 shrink-0" />
                                        )}
                                      </div>
                                    );
                                  })}
                                </div>
                              )}
                            </div>
                          );
                        })}

                        {/* Manual nodes group (collapsible accordion) */}
                        {manualNodes.length > 0 && (() => {
                          const query = proxySearch.trim().toLowerCase();
                          const filteredManual = manualNodes.filter(
                            (n) =>
                              !query ||
                              n.name.toLowerCase().includes(query) ||
                              n.protocol.toLowerCase().includes(query)
                          );
                          if (filteredManual.length === 0) return null;
                          const isExpanded = query.length > 0 || expandedSubIds.has("__manual__");
                          const containsSelected = manualNodes.some((n) => n.raw_uri === form.proxy);

                          return (
                            <div className="pt-1.5">
                              <div
                                onClick={() => toggleExpandGroup("__manual__")}
                                className={`px-2.5 py-1.5 rounded cursor-pointer flex items-center justify-between transition select-none ${
                                  containsSelected
                                    ? "bg-indigo-950/40 text-indigo-200 hover:bg-indigo-950/60"
                                    : "hover:bg-gray-800 text-gray-300"
                                }`}
                              >
                                <div className="flex items-center gap-1.5 min-w-0 flex-1">
                                  {isExpanded ? (
                                    <ChevronDown className="h-3.5 w-3.5 text-gray-400 shrink-0" />
                                  ) : (
                                    <ChevronRight className="h-3.5 w-3.5 text-gray-400 shrink-0" />
                                  )}
                                  <span className="text-xs font-medium truncate">📌 手动导入节点</span>
                                </div>
                                <div className="flex items-center gap-1.5 shrink-0 ml-2">
                                  {containsSelected && (
                                    <span className="text-[10px] text-indigo-400 bg-indigo-950 border border-indigo-800/60 px-1 py-0.2 rounded font-medium">
                                      当前选择
                                    </span>
                                  )}
                                  <span className="text-[10px] text-gray-500 bg-gray-800/80 px-1.5 py-0.5 rounded">
                                    {filteredManual.length}个节点
                                  </span>
                                </div>
                              </div>

                              {isExpanded && (
                                <div className="pl-3.5 pr-1 py-0.5 space-y-0.5 border-l border-gray-800 ml-4 mt-0.5">
                                  {filteredManual.map((n) => {
                                    const isSelected = form.proxy === n.raw_uri;
                                    return (
                                      <div
                                        key={n.id}
                                        onClick={() => {
                                          set("proxy", n.raw_uri);
                                          setProxyType(detectProxyType(n.raw_uri));
                                          setProxyTest(null);
                                          setGeoMatchMessage(null);
                                          setProxyDropdownOpen(false);
                                        }}
                                        className={`px-2.5 py-1.5 rounded cursor-pointer flex items-center justify-between gap-2 transition ${
                                          isSelected
                                            ? "bg-indigo-950/70 border border-indigo-800/60 text-white"
                                            : "hover:bg-gray-800/80 text-gray-300"
                                        }`}
                                      >
                                        <div className="flex items-center gap-2 min-w-0 flex-1">
                                          <span className="text-[10px] uppercase font-bold text-indigo-400 bg-indigo-950/80 px-1.5 py-0.5 rounded shrink-0">
                                            {n.protocol}
                                          </span>
                                          <span className="text-xs truncate">{n.name}</span>
                                        </div>
                                        {isSelected && (
                                          <Check className="h-3.5 w-3.5 text-indigo-400 shrink-0" />
                                        )}
                                      </div>
                                    );
                                  })}
                                </div>
                              )}
                            </div>
                          );
                        })()}
                      </div>

                      {/* Footer action to open proxy manager */}
                      <div className="pt-2 mt-2 border-t border-gray-800">
                        <button
                          type="button"
                          onClick={() => {
                            setProxyDropdownOpen(false);
                            setIsProxyModalOpen(true);
                          }}
                          className="w-full text-left px-2 py-1.5 text-xs text-cyan-400 hover:text-cyan-300 hover:bg-cyan-950/30 rounded flex items-center gap-1.5 font-medium transition"
                        >
                          <Plus className="h-3.5 w-3.5" />
                          ➕ 添加节点 / 打开代理管理...
                        </button>
                      </div>
                    </div>
                  )}
                </div>

                {/* Match Proxy Geo button (also tests connection and latency) */}
                <button
                  type="button"
                  className="btn-secondary text-xs whitespace-nowrap disabled:opacity-60 disabled:cursor-not-allowed flex items-center gap-1.5 text-indigo-300 hover:text-indigo-200 shrink-0 h-[38px] px-3"
                  onClick={handleMatchProxyGeo}
                  disabled={matchingGeo}
                  title={
                    form.proxy
                      ? "根据当前代理节点的出口 IP 自动测试并匹配填入 Timezone 与 Locale"
                      : "测试本机真实直连出口 IP 并自动匹配填入 Timezone 与 Locale (强制跳过系统代理)"
                  }
                >
                  {matchingGeo ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "⚡ 按 IP 匹配设置"}
                </button>
              </div>

              {/* Legacy custom proxy textarea / input fallback if unmanaged */}
              {form.proxy && !selectedManagedNode && (
                <div className="mt-2 space-y-1.5">
                  <div className="flex items-center justify-between text-[11px] text-gray-400">
                    <span>自定义代理地址 (Custom Raw Proxy):</span>
                    <button
                      type="button"
                      onClick={() => setIsProxyModalOpen(true)}
                      className="underline text-amber-200 hover:text-white font-medium"
                    >
                      导入到代理管理
                    </button>
                  </div>
                  {proxyType === "singbox_json" ? (
                    <textarea
                      className="input w-full font-mono text-xs h-28 resize-y"
                      value={form.proxy ?? ""}
                      onChange={(e) => {
                        set("proxy", e.target.value || null);
                        setProxyTest(null);
                      }}
                      placeholder={`{\n  "outbounds": [\n    {\n      "type": "vless",\n      "tag": "my-proxy",\n      "server": "example.com",\n      "server_port": 443,\n      "uuid": "your-uuid",\n      "tls": { "enabled": true }\n    }\n  ]\n}`}
                    />
                  ) : (
                    <input
                      className="input w-full font-mono text-xs"
                      value={form.proxy ?? ""}
                      onChange={(e) => {
                        set("proxy", e.target.value || null);
                        setProxyTest(null);
                        setGeoMatchMessage(null);
                      }}
                      placeholder="http://user:pass@host:port"
                    />
                  )}
                </div>
              )}

              {/* Test & Latency results */}
              {proxyTest && (
                <p
                  className={`text-xs mt-1.5 ${proxyTest.ok ? "text-emerald-400" : "text-red-400"}`}
                >
                  {proxyTest.ok
                    ? `✓ ${proxyTest.ip}` +
                      (proxyTest.city || proxyTest.country
                        ? ` · ${[proxyTest.city, proxyTest.country].filter(Boolean).join(", ")}`
                        : "") +
                      (proxyTest.latency_ms != null ? ` · ${proxyTest.latency_ms}ms` : "") +
                      (proxyTest.cached ? " (cached)" : "")
                    : proxyTest.error || "网络测速/连接失败"}
                </p>
              )}

              {/* Geo matching notification */}
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

        {/* Compatibility & Search Engine */}
        <section>
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Compatibility & Search Engine</h3>
          <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
            <input
              type="checkbox"
              checked={form.allow_3p_cookies ?? false}
              onChange={(e) => set("allow_3p_cookies", e.target.checked)}
              className="rounded border-border bg-surface-2"
            />
            Allow third-party cookies for login, SSO, and challenge flows
          </label>

          <div className="mt-4 pt-3 border-t border-border/50">
            <label className="flex items-start gap-2 text-sm text-gray-300 cursor-pointer">
              <input
                type="checkbox"
                checked={form.set_google_default ?? true}
                onChange={(e) => set("set_google_default", e.target.checked)}
                className="rounded border-border bg-surface-2 mt-0.5"
              />
              <div>
                <span className="font-medium text-gray-200">启用默认搜索引擎设置</span>
                <span className="block text-xs text-gray-500">
                  首次启动或修改时自动配置（后台静默完成，启动后不会弹出设置页面），地址栏直接搜索。
                </span>
              </div>
            </label>

            {(form.set_google_default ?? true) && (
              <div className="mt-3 ml-6 p-3 rounded-lg bg-surface-2 border border-border/60 space-y-3">
                <div>
                  <label className="text-[11px] font-medium text-gray-400 block mb-1.5">预设搜索引擎（点击快速填充）：</label>
                  <div className="flex flex-wrap gap-1.5">
                    {[
                      { label: "Google", name: "Google", keyword: "google.com", url: "https://www.google.com/search?q=%s" },
                      { label: "Bing", name: "Bing", keyword: "bing.com", url: "https://www.bing.com/search?q=%s" },
                      { label: "百度 (Baidu)", name: "百度", keyword: "baidu.com", url: "https://www.baidu.com/s?wd=%s" },
                      { label: "DuckDuckGo", name: "DuckDuckGo", keyword: "duckduckgo.com", url: "https://duckduckgo.com/?q=%s" },
                    ].map((preset) => {
                      const currentName = form.search_engine_name || "Google";
                      const currentUrl = form.search_engine_url || "https://www.google.com/search?q=%s";
                      const isSelected = currentName === preset.name && currentUrl === preset.url;
                      return (
                        <button
                          key={preset.label}
                          type="button"
                          onClick={() => {
                            setForm((prev) => ({
                              ...prev,
                              search_engine_name: preset.name,
                              search_engine_keyword: preset.keyword,
                              search_engine_url: preset.url,
                            }));
                          }}
                          className={`text-xs px-2.5 py-1 rounded transition flex items-center gap-1 ${
                            isSelected
                              ? "bg-indigo-600 text-white font-medium"
                              : "bg-surface-3 text-gray-300 hover:text-white hover:bg-surface-4"
                          }`}
                        >
                          {isSelected && <Check className="h-3 w-3" />}
                          {preset.label}
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-2.5 pt-1">
                  <div>
                    <label className="text-[11px] text-gray-400 block mb-1">引擎名称 (Name)</label>
                    <input
                      type="text"
                      className="input text-xs w-full py-1.5"
                      value={form.search_engine_name ?? "Google"}
                      onChange={(e) => set("search_engine_name", e.target.value)}
                      placeholder="Google"
                    />
                  </div>
                  <div>
                    <label className="text-[11px] text-gray-400 block mb-1">快捷字词 (Shortcut / Keyword)</label>
                    <input
                      type="text"
                      className="input text-xs w-full py-1.5 font-mono"
                      value={form.search_engine_keyword ?? "google.com"}
                      onChange={(e) => set("search_engine_keyword", e.target.value)}
                      placeholder="google.com"
                    />
                  </div>
                  <div>
                    <label className="text-[11px] text-gray-400 block mb-1">查询网址 (URL with %s)</label>
                    <input
                      type="text"
                      className="input text-xs w-full py-1.5 font-mono"
                      value={form.search_engine_url ?? "https://www.google.com/search?q=%s"}
                      onChange={(e) => set("search_engine_url", e.target.value)}
                      placeholder="https://www.google.com/search?q=%s"
                    />
                  </div>
                </div>
              </div>
            )}
          </div>
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

          {isOldKernel && (
            <div className="mb-3 p-2.5 rounded-lg bg-blue-950/40 border border-blue-600/50 flex items-start gap-2 text-xs text-blue-300">
              <AlertTriangle className="h-4 w-4 shrink-0 text-blue-400 mt-0.5" />
              <div>
                <p className="font-medium">
                  当前选中的内核版本 (v{form.browser_version}) 原生不支持命令行内联代理凭证。
                </p>
                <p className="text-[11px] text-blue-300/80 mt-0.5">
                  请直接在上方「Network (网络代理)」中配置代理节点，系统会自动通过 CDP 协议安全无缝注入鉴权，切勿在此处手动添加带账号密码的 <code>--proxy-server=http://user:pass@host</code> 参数。
                </p>
              </div>
            </div>
          )}

          {hasInlineProxyAuthArg && (
            <div className="mb-3 p-2.5 rounded-lg bg-rose-950/50 border border-rose-600/60 flex items-start gap-2 text-xs text-rose-300">
              <AlertTriangle className="h-4 w-4 shrink-0 text-rose-400 mt-0.5" />
              <div>
                <p className="font-medium">
                  检测到包含账号密码的内联代理参数：<code>--proxy-server=...</code>
                </p>
                <p className="text-[11px] text-rose-300/80 mt-0.5">
                  在 Chromium 148 以下内核中使用此参数会导致浏览器启动失败。请移除该命令行参数并在「Network」配置项中设置代理。
                </p>
              </div>
            </div>
          )}

          {/* Preset recommendations */}
          <div className="mb-3">
            <div className="text-[11px] font-medium text-gray-400 mb-1.5">
              常用安全与防关联推荐参数（点击添加 / 移除）：
            </div>
            <div className="flex flex-wrap gap-1.5">
              {ARG_PRESETS.map((preset) => {
                const isActive = (form.launch_args ?? []).includes(preset.arg);
                return (
                  <button
                    key={preset.arg}
                    type="button"
                    title={`${preset.arg} - ${preset.tip}`}
                    onClick={() => {
                      if (isActive) {
                        const idx = (form.launch_args ?? []).indexOf(preset.arg);
                        if (idx !== -1) removeLaunchArg(idx);
                      } else {
                        addLaunchArg(preset.arg);
                      }
                    }}
                    className={`inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full transition ${
                      isActive
                        ? "bg-indigo-950/80 border border-indigo-600 text-indigo-300 font-medium"
                        : "bg-surface-2 hover:bg-surface-3 border border-border text-gray-400 hover:text-gray-200"
                    }`}
                  >
                    <span>{isActive ? "✓" : "+"}</span>
                    <span>{preset.label}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Ignored Default Arguments Section */}
          <div className="mb-4 p-3 rounded-lg bg-surface-2/70 border border-border/70 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-semibold text-gray-300 uppercase tracking-wider flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-amber-400"></span>
                已忽略的默认参数 (Ignored Default Arguments)
              </span>
              <span className="text-[10px] text-gray-500">
                Playwright 默认参数抑制，防止暴露自动化特征或阻塞插件加载
              </span>
            </div>
            <div className="flex flex-wrap gap-2 pt-1">
              <span
                className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-md font-mono border ${
                  (form.extension_paths ?? []).length > 0 || (form.launch_args ?? []).includes("ignore: --disable-extensions")
                    ? "bg-amber-950/60 border-amber-600/60 text-amber-200"
                    : "bg-surface-3/50 border-border/50 text-gray-500 line-through"
                }`}
                title={(form.extension_paths ?? []).length > 0 ? "由于勾选了插件，已自动忽略 --disable-extensions" : "未勾选插件"}
              >
                <span className="font-semibold text-amber-400">ignore:</span> --disable-extensions
                <span className="text-[10px] px-1 rounded bg-amber-900/50 text-amber-300 font-sans">
                  {(form.extension_paths ?? []).length > 0 ? "插件加载已激活" : "未激活"}
                </span>
              </span>

              <span
                className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-md font-mono border bg-emerald-950/50 border-emerald-700/50 text-emerald-200"
                title="CloakBrowser 核心默认忽略，避免暴露 navigator.webdriver"
              >
                <span className="font-semibold text-emerald-400">ignore:</span> --enable-automation
                <span className="text-[10px] px-1 rounded bg-emerald-900/50 text-emerald-300 font-sans">
                  系统内置防关联
                </span>
              </span>

              <span
                className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-md font-mono border bg-emerald-950/50 border-emerald-700/50 text-emerald-200"
                title="CloakBrowser 核心默认忽略，避免暴露 SwiftShader WebGL 渲染特征"
              >
                <span className="font-semibold text-emerald-400">ignore:</span> --enable-unsafe-swiftshader
                <span className="text-[10px] px-1 rounded bg-emerald-900/50 text-emerald-300 font-sans">
                  系统内置防关联
                </span>
              </span>

              {(form.launch_args ?? [])
                .filter((a) => a.startsWith("ignore:") && a !== "ignore: --disable-extensions")
                .map((arg, i) => (
                  <span
                    key={`custom-ignore-${i}`}
                    className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-md font-mono border bg-indigo-950/60 border-indigo-600/60 text-indigo-200"
                  >
                    <span className="font-semibold text-indigo-400">ignore:</span> {arg.slice(7).trim()}
                    <span className="text-[10px] px-1 rounded bg-indigo-900/50 text-indigo-300 font-sans">
                      自定义忽略
                    </span>
                  </span>
                ))}
            </div>
          </div>

          {(form.launch_args ?? []).length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-3">
              {(form.launch_args ?? []).map((arg, index) => {
                const isIgnore = arg.startsWith("ignore:");
                return (
                  <span
                    key={`${arg}-${index}`}
                    className={`inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full font-mono ${
                      isIgnore
                        ? "bg-amber-950/60 text-amber-200 border border-amber-800/60"
                        : "bg-surface-3 text-gray-300"
                    }`}
                  >
                    {isIgnore && <span className="text-[10px] text-amber-400 font-bold">IGNORE</span>}
                    {isIgnore ? arg.slice(7).trim() : arg}
                    <button type="button" onClick={() => removeLaunchArg(index)} className="hover:opacity-70">
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                );
              })}
            </div>
          )}
          <div className="flex gap-2">
            <input
              className="input flex-1 font-mono"
              value={launchArgInput}
              onChange={(e) => setLaunchArgInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addLaunchArg(); } }}
              placeholder="--disable-features=Foo 或 ignore: --arg"
            />
            <button type="button" onClick={() => addLaunchArg()} className="btn-secondary text-xs">Add</button>
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
      onClose={() => {
        setIsProxyModalOpen(false);
        loadManagedProxies();
      }}
      onNodesChanged={loadManagedProxies}
    />
  </>
  );
}
