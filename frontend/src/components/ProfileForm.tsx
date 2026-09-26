import { AlertTriangle, Check, ChevronDown, ChevronRight, ChevronUp, Clock, Copy, Cpu, Globe, HardDrive, Key, Languages, Loader2, Monitor, Network, Plus, Puzzle, RotateCcw, Save, Search, ShieldCheck, Sliders, Sparkles, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import {
  TIMEZONE_GROUPS,
  LOCALE_OPTIONS,
  getDefaultLocaleForTimezone,
} from "../lib/geoData";
import { ProxyManagerModal } from "./ProxyManagerModal";
import { CustomSelect, CustomSelectOption, BadgeVariant } from "./common/CustomSelect";
import { SystemProxyWarningBanner } from "./SystemProxyWarningBanner";
import { useSystemProxyStatus } from "../hooks/useSystemProxyStatus";

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

let _cachedInstalledKernels: KernelItem[] | null = null;

export function setCachedInstalledKernels(kernels: KernelItem[] | null) {
  _cachedInstalledKernels = kernels;
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
  settingsUpdated?: number;
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

const CHROMIUM_ARG_PRESETS = [
  { label: "忽略扩展禁用", arg: "ignore: --disable-extensions", tip: "允许加载 Chrome 扩展插件（已勾选插件时会自动添加并生效）" },
  { label: "去除自动化特征", arg: "--disable-blink-features=AutomationControlled", tip: "避免被检测到 navigator.webdriver 等自动化特征" },
  { label: "跳过首次运行", arg: "--no-first-run", tip: "跳过首次启动向导与测试，防止首次运行特征暴露" },
  { label: "禁用默认浏览器检查", arg: "--no-default-browser-check", tip: "禁止弹出默认浏览器设置提示" },
  { label: "阻止后台网络探测", arg: "--disable-background-networking", tip: "防止浏览器后台发起自发性网络请求与上报" },
  { label: "阻止组件自动更新", arg: "--disable-component-update", tip: "保持浏览器组件版本与指纹一致" },
  { label: "禁用网页通知", arg: "--disable-notifications", tip: "阻止网页弹窗申请通知权限" },
  { label: "窗口最大化启动", arg: "--start-maximized", tip: "窗口最大化以模拟真实桌面用户行为" },
  { label: "静音所有标签", arg: "--mute-audio", tip: "静音浏览器所有声音输出" },
  { label: "禁用密码提示与钥匙串", arg: "--password-store=basic", tip: "防止弹出系统级密码与钥匙串授权提示" },
];

const FIREFOX_ARG_PRESETS = [
  { label: "静音所有标签", arg: "-mute-audio", tip: "静音 Firefox 浏览器所有声音输出" },
  { label: "隐私无痕模式", arg: "-private-window", tip: "以隐私浏览模式启动，不保留临时历史记录" },
  { label: "独立进程隔离", arg: "-no-remote", tip: "强制启动独立的 Firefox 进程，不复用已有实例" },
  { label: "全屏展台模式", arg: "--kiosk", tip: "以全屏 Kiosk 展台模式启动" },
  { label: "启动时打开开发者工具", arg: "-devtools", tip: "启动时自动唤出开发者工具面板" },
];

const WEBGL_PRESETS: { label: string; vendor: string | null; renderer: string | null }[] = [
  { label: "自动跟随系统 / 种子推导 (Auto)", vendor: null, renderer: null },
  // Apple Silicon 系列 (macOS 真实设备)
  { label: "Apple Silicon (Apple M1)", vendor: "Apple", renderer: "Apple M1" },
  { label: "Apple Silicon (Apple M2)", vendor: "Apple", renderer: "Apple M2" },
  { label: "Apple Silicon (Apple M3)", vendor: "Apple", renderer: "Apple M3" },
  { label: "Apple Silicon (Apple M3 Pro)", vendor: "Apple", renderer: "Apple M3 Pro" },
  { label: "Apple Silicon (Apple M4)", vendor: "Apple", renderer: "Apple M4" },
  // AMD Radeon 系列 (独显与核显)
  { label: "AMD Radeon Graphics (核显)", vendor: "AMD", renderer: "AMD Radeon(TM) Graphics" },
  { label: "AMD Radeon RX 580", vendor: "AMD", renderer: "Radeon RX 580 Series" },
  { label: "AMD Radeon RX 6700 XT", vendor: "AMD", renderer: "AMD Radeon RX 6700 XT" },
  { label: "AMD Radeon RX 7800 XT", vendor: "AMD", renderer: "AMD Radeon RX 7800 XT" },
  // Intel 系列 (核显/主流办公本与独显)
  { label: "Intel Arc A770 Graphics", vendor: "Intel Inc.", renderer: "Intel(R) Arc(TM) A770 Graphics" },
  { label: "Intel Iris Xe Graphics", vendor: "Intel Inc.", renderer: "Intel(R) Iris(R) Xe Graphics" },
  { label: "Intel UHD Graphics 630", vendor: "Intel Inc.", renderer: "Intel(R) UHD Graphics 630" },
  { label: "Intel UHD Graphics 770", vendor: "Intel Inc.", renderer: "Intel(R) UHD Graphics 770" },
  // NVIDIA 系列 (桌面/游戏主流，全球市场份额极高)
  { label: "NVIDIA GeForce GTX 1660 Ti", vendor: "NVIDIA Corporation", renderer: "NVIDIA GeForce GTX 1660 Ti/PCIe/SSE2" },
  { label: "NVIDIA GeForce RTX 2060", vendor: "NVIDIA Corporation", renderer: "NVIDIA GeForce RTX 2060/PCIe/SSE2" },
  { label: "NVIDIA GeForce RTX 3060", vendor: "NVIDIA Corporation", renderer: "NVIDIA GeForce RTX 3060/PCIe/SSE2" },
  { label: "NVIDIA GeForce RTX 3080", vendor: "NVIDIA Corporation", renderer: "NVIDIA GeForce RTX 3080/PCIe/SSE2" },
  { label: "NVIDIA GeForce RTX 4060", vendor: "NVIDIA Corporation", renderer: "NVIDIA GeForce RTX 4060/PCIe/SSE2" },
  { label: "NVIDIA GeForce RTX 4070", vendor: "NVIDIA Corporation", renderer: "NVIDIA GeForce RTX 4070/PCIe/SSE2" },
  { label: "NVIDIA GeForce RTX 4090", vendor: "NVIDIA Corporation", renderer: "NVIDIA GeForce RTX 4090/PCIe/SSE2" },
];

const BROWSER_TYPE_OPTIONS: CustomSelectOption<string>[] = [
  {
    value: "cloakbrowser",
    label: "CloakBrowser (基于 Chromium)",
    sublabel: "多开防关联，支持扩展管理与指纹注入",
    badge: "Chromium",
    badgeVariant: "blue",
    icon: <Globe className="h-4 w-4 text-blue-400" />,
  },
  {
    value: "camoufox",
    label: "Camoufox (基于 Firefox)",
    sublabel: "内核级 C++ 反指纹伪装，极致防追踪",
    badge: "Firefox",
    badgeVariant: "amber",
    icon: <ShieldCheck className="h-4 w-4 text-amber-400" />,
  },
];

const CPU_OPTIONS: CustomSelectOption<number | null>[] = [
  { value: null, label: "自动 (跟随指纹种子推导)", sublabel: "根据种子生成匹配硬件核心数", badge: "推荐", badgeVariant: "emerald" },
  { value: 2, label: "2 核心 (2 Cores)", sublabel: "低配双核" },
  { value: 4, label: "4 核心 (4 Cores)", sublabel: "主流办公四核" },
  { value: 6, label: "6 核心 (6 Cores)", sublabel: "主流六核" },
  { value: 8, label: "8 核心 (8 Cores)", sublabel: "主流八核", badge: "推荐", badgeVariant: "blue" },
  { value: 12, label: "12 核心 (12 Cores)", sublabel: "高性能多核" },
  { value: 16, label: "16 核心 (16 Cores)", sublabel: "工作站配置" },
  { value: 24, label: "24 核心 (24 Cores)", sublabel: "高端工作站" },
  { value: 32, label: "32 核心 (32 Cores)", sublabel: "服务器级多核" },
];

const MEMORY_OPTIONS: CustomSelectOption<number | null>[] = [
  { value: null, label: "自动 (跟随指纹种子推导)", sublabel: "根据种子生成匹配内存容量", badge: "推荐", badgeVariant: "emerald" },
  { value: 2, label: "2 GB", sublabel: "入门低配" },
  { value: 4, label: "4 GB", sublabel: "轻量配置" },
  { value: 8, label: "8 GB", sublabel: "最常见标准配置", badge: "推荐", badgeVariant: "blue" },
  { value: 16, label: "16 GB", sublabel: "主流高性能" },
  { value: 32, label: "32 GB", sublabel: "专业级开发配置" },
  { value: 64, label: "64 GB", sublabel: "顶级大内存" },
];

const HUMAN_PRESET_OPTIONS: CustomSelectOption<string>[] = [
  {
    value: "default",
    label: "Default (normal speed)",
    sublabel: "自然模拟真人鼠标移动、滚动与输入节奏",
    badge: "推荐",
    badgeVariant: "emerald",
  },
  {
    value: "careful",
    label: "Careful (slower, deliberate)",
    sublabel: "更慢速、谨慎的操作节奏，适合严格风控",
    badge: "慢速",
    badgeVariant: "amber",
  },
];

export function compareKernelVersions(a: string, b: string): number {
  if (a === b) return 0;
  const cleanA = a.replace(/^v/i, "");
  const cleanB = b.replace(/^v/i, "");

  const regex = /(\d+|\D+)/g;
  const tokensA = cleanA.match(regex) || [];
  const tokensB = cleanB.match(regex) || [];

  const maxLen = Math.max(tokensA.length, tokensB.length);
  for (let i = 0; i < maxLen; i++) {
    const tA = tokensA[i];
    const tB = tokensB[i];

    if (tA === undefined) return -1;
    if (tB === undefined) return 1;

    const numA = Number(tA);
    const numB = Number(tB);
    const isNumA = !isNaN(numA);
    const isNumB = !isNaN(numB);

    if (isNumA && isNumB) {
      if (numA !== numB) {
        return numA - numB;
      }
    } else if (tA !== tB) {
      return tA.localeCompare(tB);
    }
  }
  return 0;
}

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
  settingsUpdated,
  onOpenKernelManager,
}: ProfileFormProps) {
  const isEdit = profile !== null;

  const [form, setForm] = useState<ProfileCreateData>({
    name: profile?.name ?? "",
    browser_version: profile?.browser_version ?? null,
    browser_type: profile?.browser_type ?? "cloakbrowser",
    proxy: profile?.proxy ?? null,
    timezone: profile?.timezone ?? null,
    locale: profile?.locale ?? null,
    screen_width: profile?.screen_width ?? 1920,
    screen_height: profile?.screen_height ?? 1080,
    gpu_family: profile?.gpu_family ?? "auto",
    humanize: profile?.humanize ?? false,
    human_preset: profile?.human_preset ?? "default",
    geoip: profile?.geoip ?? true,
    clipboard_sync: profile?.clipboard_sync ?? true,
    auto_launch: profile?.auto_launch ?? false,
    allow_3p_cookies: profile?.allow_3p_cookies ?? true,
    set_google_default: profile?.set_google_default ?? true,
    search_engine_name: "Google",
    search_engine_keyword: "google.com",
    search_engine_url: "https://www.google.com/search?q=%s",
    capture_preview: true,
    restore_session: true,
    extension_paths: profile?.extension_paths ?? [],
    launch_args: profile?.launch_args ?? [],
    tags: [],
    cpu_cores: profile?.cpu_cores ?? null,
    memory_gb: profile?.memory_gb ?? null,
    webgl_vendor: profile?.webgl_vendor ?? null,
    webgl_renderer: profile?.webgl_renderer ?? null,
    canvas_noise: profile?.canvas_noise ?? true,
    audio_noise: profile?.audio_noise ?? true,
    do_not_track: profile?.do_not_track ?? false,
    firefox_user_prefs: profile?.firefox_user_prefs ?? null,
    extra_launch_args: profile?.extra_launch_args ?? null,
  });

  const engineExtensionsRef = useRef<Record<string, string[]>>({
    [profile?.browser_type ?? "cloakbrowser"]: profile?.extension_paths ?? [],
  });

  const [prefKeyInput, setPrefKeyInput] = useState("");
  const [prefValInput, setPrefValInput] = useState("");
  const [prefTypeInput, setPrefTypeInput] = useState<"boolean" | "number" | "string">("string");

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

  const {
    status: systemProxyStatus,
    loading: systemProxyLoading,
    refresh: refreshSystemProxyStatus,
  } = useSystemProxyStatus();

  const [tzDropdownOpen, setTzDropdownOpen] = useState(false);
  const [tzSearch, setTzSearch] = useState("");
  const tzDropdownRef = useRef<HTMLDivElement>(null);

  const [localeDropdownOpen, setLocaleDropdownOpen] = useState(false);
  const [localeSearch, setLocaleSearch] = useState("");
  const localeDropdownRef = useRef<HTMLDivElement>(null);

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
      if (tzDropdownRef.current && !tzDropdownRef.current.contains(e.target as Node)) {
        setTzDropdownOpen(false);
      }
      if (localeDropdownRef.current && !localeDropdownRef.current.contains(e.target as Node)) {
        setLocaleDropdownOpen(false);
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

  const loadInstalledExtensions = async (browserType: string) => {
    try {
      const list = await api.listExtensions(browserType);
      setInstalledExtensions(list);

      setForm((f) => {
        const currentPaths = f.extension_paths ?? [];
        if (!profile) {
          // New profile: default all installed extensions to checked
          const allExts = list.map((e) => e.path);
          engineExtensionsRef.current[browserType] = allExts;
          return { ...f, extension_paths: allExts };
        } else {
          // Existing profile: if we had cached paths for this browserType in engineExtensionsRef, use them
          const cached = engineExtensionsRef.current[browserType];
          const basePaths = cached !== undefined ? cached : currentPaths;
          const validPaths = new Set(list.map((e) => e.path));
          const filteredPaths = basePaths.filter((p) => validPaths.has(p));

          const updated = new Set(filteredPaths);
          const prevKnown = prevLibraryPathsRef.current;
          list.forEach((ext) => {
            if (!prevKnown.has(ext.path) && prevKnown.size > 0) {
              updated.add(ext.path);
            }
          });
          const nextExts = Array.from(updated);
          engineExtensionsRef.current[browserType] = nextExts;
          return { ...f, extension_paths: nextExts };
        }
      });

      prevLibraryPathsRef.current = new Set(list.map((e) => e.path));
    } catch (err) {
      console.error("Failed to load extensions in form:", err);
    }
  };

  useEffect(() => {
    loadInstalledExtensions(form.browser_type || "cloakbrowser");
  }, [extensionsUpdated, form.browser_type]);

  const [installedKernels, setInstalledKernels] = useState<KernelItem[]>(
    () => _cachedInstalledKernels ?? []
  );
  const [kernelsLoaded, setKernelsLoaded] = useState(
    () => _cachedInstalledKernels !== null
  );
  const [kernelsLoading, setKernelsLoading] = useState(
    () => _cachedInstalledKernels === null
  );

  const currentTypeInstalledKernels = useMemo(() => {
    return installedKernels
      .filter((k) => (k.browser_type || "cloakbrowser") === (form.browser_type || "cloakbrowser"))
      .sort((a, b) => compareKernelVersions(b.version, a.version));
  }, [installedKernels, form.browser_type]);

  const loadInstalledKernels = useCallback(async () => {
    setKernelsLoading(true);
    try {
      const res = await api.listKernels();
      const installed = res.kernels.filter((k) => k.installed);
      _cachedInstalledKernels = installed;
      setInstalledKernels(installed);
      setKernelsLoaded(true);
    } catch (err) {
      console.error("Failed to load kernels in form:", err);
    } finally {
      setKernelsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadInstalledKernels();
  }, [loadInstalledKernels, kernelsUpdated]);

  // Synchronize browser_version with available installed kernels:
  // - If no version is selected yet, default to the latest installed version.
  // - If the selected version is deleted from disk / not found, automatically update to the highest available version (or null if none).
  useEffect(() => {
    if (!kernelsLoaded || installedKernels.length === 0) return;

    const highestVersion = currentTypeInstalledKernels[0]?.version ?? null;

    if (currentTypeInstalledKernels.length === 0) {
      if (form.browser_version !== null) {
        setForm((prev) => ({ ...prev, browser_version: null }));
      }
      return;
    }

    const isCurrentValid = currentTypeInstalledKernels.some((k) => k.version === form.browser_version);
    if (!form.browser_version || !isCurrentValid) {
      setForm((prev) => ({ ...prev, browser_version: highestVersion }));
    }
  }, [kernelsLoaded, form.browser_type, form.browser_version, currentTypeInstalledKernels, installedKernels.length]);

  const handleBrowserTypeChange = (newType: string) => {
    const matching = installedKernels
      .filter((k) => (k.browser_type || "cloakbrowser") === newType)
      .sort((a, b) => compareKernelVersions(b.version, a.version));
    const newVersion = matching[0]?.version ?? null;

    const oldType = form.browser_type || "cloakbrowser";
    // Preserve extension paths for the old engine
    engineExtensionsRef.current[oldType] = form.extension_paths ?? [];
    const restoredExts = engineExtensionsRef.current[newType] ?? [];

    // Preserve launch args for the old engine
    const currentExtra = { ...(form.extra_launch_args ?? {}) };
    currentExtra[oldType] = form.launch_args ?? [];
    const nextArgs = currentExtra[newType] ?? [];

    setForm((prev) => ({
      ...prev,
      browser_type: newType,
      browser_version: newVersion,
      extension_paths: restoredExts,
      launch_args: nextArgs,
      extra_launch_args: currentExtra,
    }));
  };

  const addFirefoxPref = () => {
    const k = prefKeyInput.trim();
    if (!k) return;
    let v: any = prefValInput.trim();
    if (prefTypeInput === "boolean") {
      v = v === "true" || v === "1";
    } else if (prefTypeInput === "number") {
      v = Number(v) || 0;
    }
    setForm((prev) => ({
      ...prev,
      firefox_user_prefs: {
        ...(prev.firefox_user_prefs ?? {}),
        [k]: v,
      },
    }));
    setPrefKeyInput("");
    setPrefValInput("");
  };

  const removeFirefoxPref = (keyToRemove: string) => {
    setForm((prev) => {
      const copy = { ...(prev.firefox_user_prefs ?? {}) };
      delete copy[keyToRemove];
      return {
        ...prev,
        firefox_user_prefs: Object.keys(copy).length > 0 ? copy : null,
      };
    });
  };

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
  }, [isEdit, settingsUpdated]);

  const prevProfileIdRef = useRef<string | null | undefined>(undefined);

  useEffect(() => {
    if (profile) {
      if (prevProfileIdRef.current !== profile.id) {
        prevProfileIdRef.current = profile.id;
        setForm({
          name: profile.name,
          browser_version: profile.browser_version ?? null,
          browser_type: profile.browser_type ?? "cloakbrowser",
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
          cpu_cores: profile.cpu_cores ?? null,
          memory_gb: profile.memory_gb ?? null,
          webgl_vendor: profile.webgl_vendor ?? null,
          webgl_renderer: profile.webgl_renderer ?? null,
          canvas_noise: profile.canvas_noise ?? true,
          audio_noise: profile.audio_noise ?? true,
          do_not_track: profile.do_not_track ?? false,
          firefox_user_prefs: profile.firefox_user_prefs ?? null,
          extra_launch_args: profile.extra_launch_args ?? null,
        });
        engineExtensionsRef.current = {
          [profile.browser_type || "cloakbrowser"]: profile.extension_paths ?? [],
        };
        setProxyType(detectProxyType(profile.proxy));
        setPreviewError(false);
        setPreviewBuster(Date.now());
        setProxyTest(null);
        setTzDropdownOpen(false);
        setTzSearch("");
        setLocaleDropdownOpen(false);
        setLocaleSearch("");
        setTagInput("");
        setLaunchArgInput("");
        setPrefKeyInput("");
        setPrefValInput("");
      }
    } else {
      if (prevProfileIdRef.current !== null) {
        prevProfileIdRef.current = null;
        engineExtensionsRef.current = {};
        setForm({
          name: "",
          browser_version: null,
          browser_type: "cloakbrowser",
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
          tags: [],
          license_id: null,
          cpu_cores: null,
          memory_gb: null,
          webgl_vendor: null,
          webgl_renderer: null,
          canvas_noise: true,
          audio_noise: true,
          do_not_track: false,
          firefox_user_prefs: null,
          extra_launch_args: null,
        });
        setPreviewError(false);
        setPreviewBuster(Date.now());
        setProxyTest(null);
        setTzDropdownOpen(false);
        setTzSearch("");
        setLocaleDropdownOpen(false);
        setLocaleSearch("");
        setTagInput("");
        setLaunchArgInput("");
        setPrefKeyInput("");
        setPrefValInput("");
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

  const [testingProxy, setTestingProxy] = useState(false);

  const handleTestProxy = async () => {
    setTestingProxy(true);
    try {
      if (!form.proxy) {
        refreshSystemProxyStatus();
      }
      const res = await api.testProxy(form.proxy, form.proxy ? proxyType : "direct");
      setProxyTest(res);
      if (!res.ok) {
        alert(`网络连接测试失败: ${res.error || "无法连接"}`);
        return;
      }
      // If user is in manual mode, offer optional quick sync
      if (!form.geoip) {
        const newTz = res.timezone || null;
        const newLoc = res.locale || null;
        if (newTz || newLoc) {
          const confirmMsg =
            `检测到当前网络出口 (${res.ip}) 的地理信息：\n` +
            `· 时区: ${newTz || "未匹配"}\n` +
            `· 语言: ${newLoc || "未匹配"}\n\n` +
            `您当前处于【手动模式】，是否将下拉框快速填充为该出口的时区与语言？`;
          if (window.confirm(confirmMsg)) {
            if (newTz) set("timezone", newTz);
            if (newLoc) set("locale", newLoc);
          }
        }
      }
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "测试代理连接失败";
      alert(`测试失败: ${message}`);
    } finally {
      setTestingProxy(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name.trim()) return;
    setSaving(true);
    try {
      const curType = form.browser_type || "cloakbrowser";
      const finalExtra = { ...(form.extra_launch_args ?? {}), [curType]: form.launch_args ?? [] };

      const derivedGpuFamily = (vendor: string | null | undefined): "auto" | "nvidia" | "intel" => {
        if (!vendor) return form.gpu_family ?? "auto";
        const lower = vendor.toLowerCase();
        if (lower.includes("nvidia")) return "nvidia";
        if (lower.includes("intel")) return "intel";
        return "auto";
      };

      await onSave({
        ...form,
        gpu_family: derivedGpuFamily(form.webgl_vendor),
        timezone: form.geoip ? null : (form.timezone || null),
        locale: form.geoip ? null : (form.locale || null),
        extra_launch_args: finalExtra,
      });
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
    kernelsLoaded &&
    form.browser_version &&
    currentTypeInstalledKernels.length > 0 &&
    !currentTypeInstalledKernels.some((k) => k.version === form.browser_version)
  );

  const browserVersionOptions = useMemo<CustomSelectOption<string | null>[]>(() => {
    if (!kernelsLoaded && !form.browser_version) {
      return [{ value: null, label: "正在检测已安装内核...", disabled: true }];
    }
    if (!kernelsLoaded && form.browser_version && !currentTypeInstalledKernels.some((k) => k.version === form.browser_version)) {
      return [{ value: form.browser_version, label: `v${form.browser_version}`, sublabel: "正在加载内核...", badge: "Loading", badgeVariant: "gray" }];
    }
    if (kernelsLoaded && currentTypeInstalledKernels.length === 0) {
      return [{ value: null, label: "未检测到已安装内核 (请先下载)", disabled: true, badge: "未安装", badgeVariant: "amber" }];
    }

    const list: CustomSelectOption<string | null>[] = [];
    if (isSelectedKernelMissing && form.browser_version) {
      list.push({
        value: form.browser_version,
        label: `⚠️ v${form.browser_version}`,
        sublabel: "本地已删除或类型不匹配 - 启动将自动回退",
        badge: "缺失回退",
        badgeVariant: "rose",
      });
    }
    currentTypeInstalledKernels.forEach((k) => {
      list.push({
        value: k.version,
        label: `${k.name} (v${k.version})`,
        sublabel: k.is_active ? "当前运行内核" : k.description || undefined,
        badge: k.tier === "pro" ? "Pro 授权" : "官方内核",
        badgeVariant: k.tier === "pro" ? "purple" : "blue",
      });
    });
    return list;
  }, [kernelsLoaded, form.browser_version, currentTypeInstalledKernels, isSelectedKernelMissing]);

  const licenseOptions = useMemo<CustomSelectOption<string | null>[]>(() => [
    {
      value: null,
      label: "Keyless (无授权) / 免费内核模式",
      sublabel: "无需授权码，使用基础功能",
      badge: "免费版",
      badgeVariant: "gray",
      icon: <Key className="h-4 w-4 text-gray-400" />,
    },
    ...licenses.map((l) => ({
      value: l.id,
      label: l.name,
      sublabel: l.is_default ? "系统默认全局授权" : undefined,
      badge: l.is_default ? "默认授权" : "已绑定",
      badgeVariant: (l.is_default ? "emerald" : "blue") as BadgeVariant,
      icon: <Key className="h-4 w-4 text-emerald-400" />,
    })),
  ], [licenses]);

  const resolutionOptions = useMemo<CustomSelectOption<string>[]>(() => [
    ...Object.entries(RESOLUTION_PRESETS).map(([name, res]) => ({
      value: name,
      label: name,
      sublabel: `${res.width} × ${res.height}`,
      badge: name.includes("Full HD") ? "最常用" : "常用预设",
      badgeVariant: (name.includes("Full HD") ? "blue" : "gray") as BadgeVariant,
      icon: <Monitor className="h-4 w-4 text-indigo-400" />,
    })),
    {
      value: "custom",
      label: "自定义分辨率 (Custom)",
      sublabel: "手动指定宽和高",
      badge: "自定义",
      badgeVariant: "amber",
      icon: <Monitor className="h-4 w-4 text-amber-400" />,
    },
  ], []);

  const currentWebglPresetLabel = useMemo(() => {
    return WEBGL_PRESETS.find(
      (p) => p.vendor === (form.webgl_vendor ?? null) && p.renderer === (form.webgl_renderer ?? null)
    )?.label ?? "custom";
  }, [form.webgl_vendor, form.webgl_renderer]);

  const webglPresetOptions = useMemo<CustomSelectOption<string>[]>(() => [
    ...WEBGL_PRESETS.map((p) => {
      let badgeVariant: BadgeVariant = "gray";
      if (p.label.includes("NVIDIA")) badgeVariant = "emerald";
      else if (p.label.includes("Apple")) badgeVariant = "purple";
      else if (p.label.includes("Intel")) badgeVariant = "blue";
      else if (p.label.includes("AMD")) badgeVariant = "rose";

      return {
        value: p.label,
        label: p.label,
        sublabel: p.renderer ? p.renderer : "由指纹种子自动推导并保持系统一致",
        badge: p.vendor ? p.vendor.replace("Google Inc. (", "").replace(")", "") : "Auto",
        badgeVariant,
        icon: <Cpu className="h-4 w-4 text-purple-400" />,
      };
    }),
    {
      value: "custom",
      label: "自定义输入 (Custom)",
      sublabel: "手动输入 Vendor 与 Renderer 字符串",
      badge: "自定义",
      badgeVariant: "amber",
      icon: <Cpu className="h-4 w-4 text-amber-400" />,
    },
  ], []);

  const isOldKernel = Boolean(
    form.browser_version &&
    ["144.", "145.", "146.", "147."].some((prefix) => form.browser_version?.startsWith(prefix))
  );

  const hasInlineProxyAuthArg = (form.launch_args ?? []).some(
    (arg) => arg.startsWith("--proxy-server=") && arg.includes("@")
  );

  const selectedTzInfo = useMemo(() => {
    if (!form.timezone) return null;
    for (const group of TIMEZONE_GROUPS) {
      const match = group.options.find((opt) => opt.value === form.timezone);
      if (match) return match;
    }
    return { value: form.timezone, label: "自定义时区", offset: "" };
  }, [form.timezone]);

  const selectedLocaleInfo = useMemo(() => {
    if (!form.locale) return null;
    const match = LOCALE_OPTIONS.find((loc) => loc.value === form.locale);
    if (match) return match;
    return { value: form.locale, label: "自定义语言", nativeName: "" };
  }, [form.locale]);

  const filteredTimezoneGroups = useMemo(() => {
    const q = tzSearch.trim().toLowerCase();
    if (!q) return TIMEZONE_GROUPS;
    return TIMEZONE_GROUPS.map((group) => {
      const isGroupMatch = group.region.toLowerCase().includes(q);
      const filteredOptions = group.options.filter(
        (opt) =>
          isGroupMatch ||
          opt.value.toLowerCase().includes(q) ||
          opt.label.toLowerCase().includes(q) ||
          opt.offset.toLowerCase().includes(q)
      );
      return { ...group, options: filteredOptions };
    }).filter((group) => group.options.length > 0);
  }, [tzSearch]);

  const isExactTzMatch = useMemo(() => {
    const q = tzSearch.trim().toLowerCase();
    if (!q) return true;
    for (const group of TIMEZONE_GROUPS) {
      if (group.options.some((o) => o.value.toLowerCase() === q)) return true;
    }
    return false;
  }, [tzSearch]);

  const filteredLocales = useMemo(() => {
    const q = localeSearch.trim().toLowerCase();
    if (!q) return LOCALE_OPTIONS;
    return LOCALE_OPTIONS.filter(
      (loc) =>
        loc.value.toLowerCase().includes(q) ||
        loc.label.toLowerCase().includes(q) ||
        (loc.nativeName && loc.nativeName.toLowerCase().includes(q))
    );
  }, [localeSearch]);

  const isExactLocaleMatch = useMemo(() => {
    const q = localeSearch.trim().toLowerCase();
    if (!q) return true;
    return LOCALE_OPTIONS.some((l) => l.value.toLowerCase() === q);
  }, [localeSearch]);

  const addLaunchArg = (customArg?: string) => {
    const raw = (customArg || launchArgInput).trim();
    if (!raw) return;
    const current = form.launch_args ?? [];
    if (!current.includes(raw)) {
      const nextArgs = [...current, raw];
      const curType = form.browser_type || "cloakbrowser";
      const nextExtra = { ...(form.extra_launch_args ?? {}), [curType]: nextArgs };
      setForm((prev) => ({
        ...prev,
        launch_args: nextArgs,
        extra_launch_args: nextExtra,
      }));

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
    const nextArgs = current.filter((_, i) => i !== idx);
    const curType = form.browser_type || "cloakbrowser";
    const nextExtra = { ...(form.extra_launch_args ?? {}), [curType]: nextArgs };
    setForm((prev) => ({
      ...prev,
      launch_args: nextArgs,
      extra_launch_args: nextExtra,
    }));

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

            {form.browser_type === "cloakbrowser" && (
              <div className="col-span-2">
                <label className="label">绑定 License 授权 (License Binding)</label>
                <CustomSelect
                  id="license_id"
                  value={form.license_id ?? null}
                  options={licenseOptions}
                  onChange={(val) => set("license_id", val)}
                  placeholder="Keyless (无授权) / 免费内核模式"
                />
                <p className="text-[11px] text-gray-500 mt-1.5">
                  可选择列表管理中的 License。如果没有选择，则回退到无 License (Keyless) 的免费内核模式。
                </p>
              </div>
            )}

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
              <div className="flex items-center justify-between mt-4 mb-1">
                <label htmlFor="browser_type" className="text-sm font-medium text-slate-300">
                  内核类型 (Browser Type)
                </label>
              </div>
              <CustomSelect
                id="browser_type"
                value={form.browser_type ?? "cloakbrowser"}
                options={BROWSER_TYPE_OPTIONS}
                onChange={(val) => handleBrowserTypeChange(val || "cloakbrowser")}
              />

              <div className="flex items-center justify-between mt-4 mb-1">
                <label htmlFor="browser_version" className="text-sm font-medium text-slate-300">
                  内核版本 (Browser Version)
                </label>
              </div>
              <CustomSelect
                id="browser_version"
                value={form.browser_version ?? null}
                options={browserVersionOptions}
                onChange={(val) => set("browser_version", val)}
                placeholder="-- 选择或检测内核版本 --"
                triggerClassName={
                  kernelsLoaded && currentTypeInstalledKernels.length === 0
                    ? "border-amber-500/50 bg-amber-950/10 text-amber-300"
                    : ""
                }
              />

              {kernelsLoaded && currentTypeInstalledKernels.length === 0 && (
                <div className="mt-2 p-2.5 rounded-lg bg-amber-950/40 border border-amber-600/50 flex items-center justify-between gap-2 text-xs text-amber-300">
                  <div className="flex items-center gap-2">
                    <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400" />
                    <span>
                      未检测到已安装的 {form.browser_type === "camoufox" ? "Camoufox (Firefox)" : "CloakBrowser (Chromium)"} 内核，请先下载内核。
                    </span>
                  </div>
                  {onOpenKernelManager && (
                    <button
                      type="button"
                      onClick={onOpenKernelManager}
                      className="px-2.5 py-1 rounded bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 font-medium text-xs border border-amber-500/40 shrink-0 transition cursor-pointer"
                    >
                      前往下载
                    </button>
                  )}
                </div>
              )}

              {isSelectedKernelMissing && currentTypeInstalledKernels.length > 0 && (
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
                {form.browser_type === "camoufox"
                  ? "Camoufox 为开源免授权 Firefox 指纹浏览器内核，具备全平台指纹随机化防护能力。"
                  : "官方稳定版 (v145) 为免费内核，不受 Pro 授权与席位并发限制；如需更高级指纹防护可选用 Pro 内核。"}
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

                {/* Test Proxy / Network Connection button */}
                <button
                  type="button"
                  className="btn-secondary text-xs whitespace-nowrap disabled:opacity-60 disabled:cursor-not-allowed flex items-center gap-1.5 text-gray-300 hover:text-white shrink-0 h-[38px] px-3"
                  onClick={handleTestProxy}
                  disabled={testingProxy}
                  title="测试当前代理节点（或本机直连）的网络连通性、出口 IP、地理位置与延迟"
                >
                  {testingProxy ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-accent" />
                  ) : (
                    <HardDrive className="h-3.5 w-3.5 text-accent" />
                  )}
                  <span>测试连接</span>
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

              {/* System Proxy / VPN Warning Banner when direct connection is active */}
              {!form.proxy && (
                <SystemProxyWarningBanner
                  status={systemProxyStatus}
                  onRefresh={refreshSystemProxyStatus}
                  loading={systemProxyLoading}
                />
              )}
            </div>

            {/* GeoIP & Timezone/Locale Card */}
            <div className="p-3.5 bg-surface-1/40 border border-border rounded-lg space-y-3">
              {/* Main Switch / Checkbox */}
              <div className="flex items-start justify-between gap-3">
                <label className="flex items-start gap-2.5 text-xs text-gray-200 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={form.geoip ?? true}
                    onChange={(e) => set("geoip", e.target.checked)}
                    className="rounded border-border bg-surface-2 text-accent focus:ring-accent mt-0.5"
                  />
                  <div>
                    <span className="font-semibold text-gray-100 flex items-center gap-1.5">
                      <Sparkles className="w-3.5 h-3.5 text-purple-400" />
                      基于网络出口 IP 自动匹配时区与语言 (GeoIP · 推荐)
                    </span>
                    <p className="text-[11px] text-gray-400 mt-0.5 leading-relaxed">
                      启动浏览器时根据实际网络出口 IP 动态设置，彻底杜绝 IP 与时区矛盾。无论是使用代理还是直连，切换节点时时区自动保持一致。
                    </p>
                  </div>
                </label>
              </div>

              {/* Status Banner when Auto-detect is enabled */}
              {form.geoip ? (
                <div className="p-2.5 rounded border border-purple-500/20 bg-purple-500/5 text-xs flex items-center justify-between flex-wrap gap-2">
                  <div className="flex items-center gap-2 text-purple-300">
                    <span className="w-2 h-2 rounded-full bg-purple-400 animate-pulse shrink-0" />
                    <span>
                      {proxyTest?.ok && (proxyTest.timezone || proxyTest.locale) ? (
                        <span>
                          实时探测出口：
                          <strong className="text-white font-medium">
                            {[proxyTest.city, proxyTest.country].filter(Boolean).join(", ")}
                          </strong>
                          {" → "}
                          匹配 IANA 标准时区：
                          <strong className="text-purple-200 font-mono">
                            {proxyTest.timezone || "未解析"}
                          </strong>
                          {proxyTest.locale ? (
                            <span className="text-purple-300 font-mono"> ({proxyTest.locale})</span>
                          ) : null}
                          {" · 启动时将自动生效"}
                        </span>
                      ) : (
                        "自动探测已激活 · 启动浏览器时将根据实时出口 IP 自动注入时区与语言"
                      )}
                    </span>
                  </div>
                  {proxyTest?.country && (
                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-200 shrink-0">
                      出口节点: {[proxyTest.city, proxyTest.country].filter(Boolean).join(", ")}
                    </span>
                  )}
                </div>
              ) : (
                <div className="p-2.5 rounded border border-amber-500/20 bg-amber-500/5 text-[11px] text-amber-300 flex items-center gap-2">
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0 text-amber-400" />
                  <span>
                    手动固定模式已启用：请务必确保选定的时区/语言与实际网络出口匹配，避免产生时区与 IP 不一致的指纹特征。
                  </span>
                </div>
              )}

              {/* Timezone and Locale Selectors */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
                {/* Timezone Selector */}
                <div className="relative" ref={tzDropdownRef}>
                  <div className="flex items-center justify-between mb-1">
                    <label className="label mb-0 text-xs">
                      时区 (Timezone)
                      {form.geoip && (
                        <span className="text-[10px] text-gray-500 ml-1.5 font-normal">
                          (由出口 IP 自动接管)
                        </span>
                      )}
                    </label>
                    {!form.geoip && (
                      <span className="text-[10px] text-gray-400 font-mono">
                        {form.timezone || "未选择"}
                      </span>
                    )}
                  </div>

                  {form.geoip ? (
                    <div>
                      <div className="w-full input flex items-center justify-between py-2 text-left bg-surface-2/40 opacity-60 cursor-not-allowed">
                        <div className="flex items-center gap-2 min-w-0 flex-1">
                          <Clock className="h-4 w-4 text-purple-400/60 shrink-0" />
                          <span className="text-xs text-gray-200 truncate font-mono">
                            {proxyTest?.ok && proxyTest.timezone
                              ? proxyTest.timezone
                              : "自动跟随网络出口 (Auto GeoIP)"}
                          </span>
                        </div>
                        <span className="text-[10px] text-purple-300 font-medium bg-purple-950/60 border border-purple-800/50 rounded px-1.5 py-0.5 shrink-0 ml-2">
                          自动接管
                        </span>
                      </div>
                      {proxyTest?.ok && proxyTest.timezone && proxyTest.city && (
                        <p className="text-[10px] text-gray-400 mt-1">
                          💡 注：{proxyTest.city} 位于该区域，遵循全球 IANA 标准归属于 {proxyTest.timezone} 时区
                        </p>
                      )}
                    </div>
                  ) : (
                    <div>
                      <button
                        type="button"
                        aria-label="Timezone selector"
                        onClick={() => {
                          setLocaleDropdownOpen(false);
                          setProxyDropdownOpen(false);
                          setTzDropdownOpen(!tzDropdownOpen);
                        }}
                        className="w-full input flex items-center justify-between py-2 text-left cursor-pointer hover:border-gray-600 transition"
                      >
                        <div className="flex items-center gap-2 min-w-0 flex-1">
                          <Clock className="h-4 w-4 text-purple-400 shrink-0" />
                          <div className="min-w-0 flex-1 truncate text-xs text-gray-200">
                            {form.timezone ? (
                              <span className="font-mono">
                                {selectedTzInfo?.value}
                                {selectedTzInfo?.label && selectedTzInfo.label !== "自定义时区" ? (
                                  <span className="text-gray-400 font-sans ml-1.5">({selectedTzInfo.label})</span>
                                ) : null}
                              </span>
                            ) : (
                              <span className="text-gray-400">-- 请选择标准时区 (支持搜索) --</span>
                            )}
                          </div>
                        </div>

                        <div className="flex items-center gap-1.5 shrink-0 ml-2">
                          {selectedTzInfo?.offset && (
                            <span className="text-gray-300 font-mono text-[10px] bg-gray-800/90 border border-gray-700 rounded px-1.5 py-0.5">
                              {selectedTzInfo.offset}
                            </span>
                          )}
                          {tzDropdownOpen ? (
                            <ChevronUp className="h-4 w-4 text-gray-400 shrink-0" />
                          ) : (
                            <ChevronDown className="h-4 w-4 text-gray-400 shrink-0" />
                          )}
                        </div>
                      </button>

                      {/* Timezone Dropdown Popup */}
                      {tzDropdownOpen && (
                        <div className="absolute left-0 right-0 top-full mt-1.5 z-40 bg-gray-900 border border-gray-700 rounded-lg shadow-2xl p-2 max-h-80 flex flex-col">
                          {/* Search Input */}
                          <div className="relative pb-2 border-b border-gray-800">
                            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-500" />
                            <input
                              type="text"
                              placeholder="搜索时区名称、代表城市或区域..."
                              value={tzSearch}
                              onChange={(e) => setTzSearch(e.target.value)}
                              className="input w-full pl-8 py-1.5 text-xs"
                              onClick={(e) => e.stopPropagation()}
                              autoFocus
                            />
                          </div>

                          {/* Options list */}
                          <div className="flex-1 overflow-y-auto py-1 space-y-1">
                            {/* Empty / default option */}
                            <div
                              onClick={() => {
                                set("timezone", null);
                                setTzDropdownOpen(false);
                                setTzSearch("");
                              }}
                              className={`p-2 rounded-md cursor-pointer flex items-center justify-between gap-2 transition ${
                                !form.timezone
                                  ? "bg-purple-950/70 border border-purple-800/60 text-white"
                                  : "hover:bg-gray-800 text-gray-300"
                              }`}
                            >
                              <div className="flex items-center gap-2 min-w-0">
                                <Clock className="h-4 w-4 text-gray-400 shrink-0" />
                                <span className="text-xs">-- 留空 / 默认未设置 (Default) --</span>
                              </div>
                              {!form.timezone && <Check className="h-3.5 w-3.5 text-purple-400 shrink-0" />}
                            </div>

                            {/* Grouped Timezone Options */}
                            {filteredTimezoneGroups.map((group) => (
                              <div key={group.region} className="pt-1.5">
                                <div className="px-2 py-1 text-[11px] font-semibold text-gray-400 flex items-center justify-between">
                                  <span>{group.region}</span>
                                  <span className="text-[10px] text-gray-500 font-normal">{group.options.length} 个时区</span>
                                </div>
                                <div className="space-y-0.5">
                                  {group.options.map((opt) => {
                                    const isSelected = form.timezone === opt.value;
                                    return (
                                      <div
                                        key={opt.value}
                                        onClick={() => {
                                          set("timezone", opt.value);
                                          const recLocale = getDefaultLocaleForTimezone(opt.value);
                                          if (recLocale) {
                                            set("locale", recLocale);
                                          }
                                          setTzDropdownOpen(false);
                                          setTzSearch("");
                                        }}
                                        className={`px-2.5 py-1.5 rounded cursor-pointer flex items-center justify-between gap-2 transition ${
                                          isSelected
                                            ? "bg-purple-950/70 border border-purple-800/60 text-white"
                                            : "hover:bg-gray-800 text-gray-300"
                                        }`}
                                      >
                                        <div className="min-w-0 flex-1">
                                          <div className="text-xs font-mono font-medium flex items-center gap-1.5">
                                            <span>{opt.value}</span>
                                          </div>
                                          <div className="text-[11px] text-gray-400 truncate">
                                            {opt.label}
                                          </div>
                                        </div>
                                        <div className="flex items-center gap-1.5 shrink-0 ml-2">
                                          <span className="text-[10px] text-gray-400 font-mono bg-gray-800 px-1.5 py-0.5 rounded">
                                            {opt.offset}
                                          </span>
                                          {isSelected && (
                                            <Check className="h-3.5 w-3.5 text-purple-400 shrink-0" />
                                          )}
                                        </div>
                                      </div>
                                    );
                                  })}
                                </div>
                              </div>
                            ))}

                            {/* Custom timezone fallback */}
                            {!isExactTzMatch && tzSearch.trim().length > 0 && (
                              <div
                                onClick={() => {
                                  const customTz = tzSearch.trim();
                                  set("timezone", customTz);
                                  const recLocale = getDefaultLocaleForTimezone(customTz);
                                  if (recLocale) set("locale", recLocale);
                                  setTzDropdownOpen(false);
                                  setTzSearch("");
                                }}
                                className="p-2 mt-1 rounded cursor-pointer border border-dashed border-purple-500/40 hover:bg-purple-950/40 text-purple-300 text-xs flex items-center justify-between transition"
                              >
                                <div className="flex items-center gap-1.5 min-w-0">
                                  <Plus className="w-3.5 h-3.5 text-purple-400 shrink-0" />
                                  <span className="truncate">使用自定义时区：<strong className="font-mono text-white">{tzSearch.trim()}</strong></span>
                                </div>
                                <span className="text-[10px] text-purple-300 bg-purple-900/40 px-1.5 py-0.5 rounded shrink-0">点击应用</span>
                              </div>
                            )}

                            {filteredTimezoneGroups.length === 0 && isExactTzMatch && (
                              <div className="p-3 text-center text-xs text-gray-500">
                                未找到匹配的时区
                              </div>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* Locale Selector */}
                <div className="relative" ref={localeDropdownRef}>
                  <div className="flex items-center justify-between mb-1">
                    <label className="label mb-0 text-xs">
                      语言 (Locale)
                      {form.geoip && (
                        <span className="text-[10px] text-gray-500 ml-1.5 font-normal">
                          (由出口 IP 自动接管)
                        </span>
                      )}
                    </label>
                    {!form.geoip && (
                      <span className="text-[10px] text-gray-400 font-mono">
                        {form.locale || "未选择"}
                      </span>
                    )}
                  </div>

                  {form.geoip ? (
                    <div>
                      <div className="w-full input flex items-center justify-between py-2 text-left bg-surface-2/40 opacity-60 cursor-not-allowed">
                        <div className="flex items-center gap-2 min-w-0 flex-1">
                          <Languages className="h-4 w-4 text-blue-400/60 shrink-0" />
                          <span className="text-xs text-gray-200 truncate font-mono">
                            {proxyTest?.ok && proxyTest.locale
                              ? proxyTest.locale
                              : "自动跟随网络出口 (Auto GeoIP)"}
                          </span>
                        </div>
                        <span className="text-[10px] text-blue-300 font-medium bg-blue-950/60 border border-blue-800/50 rounded px-1.5 py-0.5 shrink-0 ml-2">
                          自动接管
                        </span>
                      </div>
                      {proxyTest?.ok && proxyTest.locale && proxyTest.country && (
                        <p className="text-[10px] text-gray-400 mt-1">
                          💡 注：根据网络出口国家/地区 ({proxyTest.country}) 匹配首选标准语言 {proxyTest.locale}
                        </p>
                      )}
                    </div>
                  ) : (
                    <div>
                      <button
                        type="button"
                        aria-label="Locale selector"
                        onClick={() => {
                          setTzDropdownOpen(false);
                          setProxyDropdownOpen(false);
                          setLocaleDropdownOpen(!localeDropdownOpen);
                        }}
                        className="w-full input flex items-center justify-between py-2 text-left cursor-pointer hover:border-gray-600 transition"
                      >
                        <div className="flex items-center gap-2 min-w-0 flex-1">
                          <Languages className="h-4 w-4 text-blue-400 shrink-0" />
                          <div className="min-w-0 flex-1 truncate text-xs text-gray-200">
                            {form.locale ? (
                              <span className="font-mono">
                                {selectedLocaleInfo?.value}
                                {selectedLocaleInfo?.label && selectedLocaleInfo.label !== "自定义语言" ? (
                                  <span className="text-gray-400 font-sans ml-1.5">({selectedLocaleInfo.label})</span>
                                ) : null}
                              </span>
                            ) : (
                              <span className="text-gray-400">-- 请选择标准语言 (支持搜索) --</span>
                            )}
                          </div>
                        </div>

                        <div className="flex items-center gap-1.5 shrink-0 ml-2">
                          {selectedLocaleInfo?.nativeName && (
                            <span className="text-gray-300 text-[10px] bg-gray-800/90 border border-gray-700 rounded px-1.5 py-0.5">
                              {selectedLocaleInfo.nativeName}
                            </span>
                          )}
                          {localeDropdownOpen ? (
                            <ChevronUp className="h-4 w-4 text-gray-400 shrink-0" />
                          ) : (
                            <ChevronDown className="h-4 w-4 text-gray-400 shrink-0" />
                          )}
                        </div>
                      </button>

                      {/* Locale Dropdown Popup */}
                      {localeDropdownOpen && (
                        <div className="absolute left-0 right-0 top-full mt-1.5 z-40 bg-gray-900 border border-gray-700 rounded-lg shadow-2xl p-2 max-h-80 flex flex-col">
                          {/* Search Input */}
                          <div className="relative pb-2 border-b border-gray-800">
                            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-500" />
                            <input
                              type="text"
                              placeholder="搜索语言代码、名称或母语 (如 zh-CN, English, 日本語)..."
                              value={localeSearch}
                              onChange={(e) => setLocaleSearch(e.target.value)}
                              className="input w-full pl-8 py-1.5 text-xs"
                              onClick={(e) => e.stopPropagation()}
                              autoFocus
                            />
                          </div>

                          {/* Options list */}
                          <div className="flex-1 overflow-y-auto py-1 space-y-1">
                            {/* Empty / default option */}
                            <div
                              onClick={() => {
                                set("locale", null);
                                setLocaleDropdownOpen(false);
                                setLocaleSearch("");
                              }}
                              className={`p-2 rounded-md cursor-pointer flex items-center justify-between gap-2 transition ${
                                !form.locale
                                  ? "bg-blue-950/70 border border-blue-800/60 text-white"
                                  : "hover:bg-gray-800 text-gray-300"
                              }`}
                            >
                              <div className="flex items-center gap-2 min-w-0">
                                <Languages className="h-4 w-4 text-gray-400 shrink-0" />
                                <span className="text-xs">-- 留空 / 默认未设置 (Default) --</span>
                              </div>
                              {!form.locale && <Check className="h-3.5 w-3.5 text-blue-400 shrink-0" />}
                            </div>

                            {/* Locale Options */}
                            <div className="space-y-0.5">
                              {filteredLocales.map((loc) => {
                                const isSelected = form.locale === loc.value;
                                return (
                                  <div
                                    key={loc.value}
                                    onClick={() => {
                                      set("locale", loc.value);
                                      setLocaleDropdownOpen(false);
                                      setLocaleSearch("");
                                    }}
                                    className={`px-2.5 py-1.5 rounded cursor-pointer flex items-center justify-between gap-2 transition ${
                                      isSelected
                                        ? "bg-blue-950/70 border border-blue-800/60 text-white"
                                        : "hover:bg-gray-800 text-gray-300"
                                    }`}
                                  >
                                    <div className="min-w-0 flex-1">
                                      <div className="text-xs font-mono font-medium flex items-center gap-1.5">
                                        <span>{loc.value}</span>
                                        <span className="text-gray-400 font-sans font-normal text-[11px] truncate">({loc.label})</span>
                                      </div>
                                    </div>
                                    <div className="flex items-center gap-1.5 shrink-0 ml-2">
                                      {loc.nativeName && (
                                        <span className="text-[10px] text-gray-400 bg-gray-800 px-1.5 py-0.5 rounded">
                                          {loc.nativeName}
                                        </span>
                                      )}
                                      {isSelected && (
                                        <Check className="h-3.5 w-3.5 text-blue-400 shrink-0" />
                                      )}
                                    </div>
                                  </div>
                                );
                              })}
                            </div>

                            {/* Custom locale fallback */}
                            {!isExactLocaleMatch && localeSearch.trim().length > 0 && (
                              <div
                                onClick={() => {
                                  set("locale", localeSearch.trim());
                                  setLocaleDropdownOpen(false);
                                  setLocaleSearch("");
                                }}
                                className="p-2 mt-1 rounded cursor-pointer border border-dashed border-blue-500/40 hover:bg-blue-950/40 text-blue-300 text-xs flex items-center justify-between transition"
                              >
                                <div className="flex items-center gap-1.5 min-w-0">
                                  <Plus className="w-3.5 h-3.5 text-blue-400 shrink-0" />
                                  <span className="truncate">使用自定义语言代码：<strong className="font-mono text-white">{localeSearch.trim()}</strong></span>
                                </div>
                                <span className="text-[10px] text-blue-300 bg-blue-900/40 px-1.5 py-0.5 rounded shrink-0">点击应用</span>
                              </div>
                            )}

                            {filteredLocales.length === 0 && isExactLocaleMatch && (
                              <div className="p-3 text-center text-xs text-gray-500">
                                未找到匹配的语言
                              </div>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Hardware & Advanced Fingerprints */}
        <section className="rounded-md border border-border bg-surface-1 p-4 space-y-4">
          <div className="flex items-center justify-between border-b border-border/60 pb-3">
            <div className="flex items-center gap-2">
              <Sliders className="h-4 w-4 text-indigo-400" />
              <h3 className="text-xs font-semibold text-gray-300 uppercase tracking-wider">
                高级硬件与隐私指纹 (Hardware & Advanced Fingerprints)
              </h3>
            </div>
            <span className="text-[10px] text-gray-400 font-normal">
              屏幕分辨率 / CPU / 内存 / WebGL GPU / 防追踪噪点
            </span>
          </div>
          <p className="text-xs text-gray-400 -mt-1">
            统一配置底层硬件指标与隐私噪点微扰。默认均为「自动跟随指纹种子推导」，与操作系统和浏览器身份保持高度一致。
          </p>

          <div className="space-y-4">
            {/* Screen Resolution */}
            <div className="space-y-2">
              <label className="text-xs font-medium text-gray-300 block mb-1">
                屏幕分辨率 (Screen Resolution)
              </label>
              <CustomSelect
                id="screen_resolution"
                value={currentResolution}
                options={resolutionOptions}
                onChange={(val) => {
                  const preset = RESOLUTION_PRESETS[val];
                  if (preset) {
                    set("screen_width", preset.width);
                    set("screen_height", preset.height);
                  }
                }}
              />
              {currentResolution === "custom" && (
                <div className="grid grid-cols-2 gap-3 pt-2">
                  <div>
                    <label className="text-[11px] text-gray-400 block mb-1">Width (宽度 - 像素)</label>
                    <input
                      className="input w-full text-xs font-mono"
                      type="number"
                      value={form.screen_width ?? 1920}
                      onChange={(e) => set("screen_width", Number(e.target.value))}
                    />
                  </div>
                  <div>
                    <label className="text-[11px] text-gray-400 block mb-1">Height (高度 - 像素)</label>
                    <input
                      className="input w-full text-xs font-mono"
                      type="number"
                      value={form.screen_height ?? 1080}
                      onChange={(e) => set("screen_height", Number(e.target.value))}
                    />
                  </div>
                </div>
              )}
            </div>

            {/* CPU & Memory */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2 border-t border-border/50">
              <div>
                <label className="text-xs font-medium text-gray-300 block mb-1">
                  CPU 核心数 (Hardware Concurrency)
                </label>
                <CustomSelect
                  id="cpu_cores"
                  value={form.cpu_cores ?? null}
                  options={CPU_OPTIONS}
                  onChange={(val) => set("cpu_cores", val)}
                  placeholder="自动 (跟随指纹种子推导)"
                />
                <span className="block text-[11px] text-gray-500 mt-1">
                  控制 <code>navigator.hardwareConcurrency</code>。
                </span>
              </div>
              <div>
                <label className="text-xs font-medium text-gray-300 block mb-1">
                  物理内存容量 (Device Memory)
                </label>
                <CustomSelect
                  id="memory_gb"
                  value={form.memory_gb ?? null}
                  options={MEMORY_OPTIONS}
                  onChange={(val) => set("memory_gb", val)}
                  placeholder="自动 (跟随指纹种子推导)"
                />
                <span className="block text-[11px] text-gray-500 mt-1">
                  控制 <code>navigator.deviceMemory</code> (Chromium)。
                </span>
              </div>
            </div>

            {/* WebGL GPU Preset Selector & Custom Inputs */}
            <div className="pt-2 border-t border-border/50 space-y-3">
              <div>
                <label className="text-xs font-medium text-gray-300 block mb-1">
                  WebGL GPU 厂商与渲染器预设 (Vendor & Renderer)
                </label>
                <CustomSelect
                  id="webgl_preset"
                  value={currentWebglPresetLabel}
                  options={webglPresetOptions}
                  onChange={(label) => {
                    const selected = WEBGL_PRESETS.find((p) => p.label === label);
                    if (selected) {
                      const vendor = selected.vendor;
                      const lower = vendor ? vendor.toLowerCase() : "";
                      const derivedGpu = lower.includes("nvidia") ? "nvidia" : lower.includes("intel") ? "intel" : "auto";
                      setForm((prev) => ({
                        ...prev,
                        webgl_vendor: selected.vendor,
                        webgl_renderer: selected.renderer,
                        gpu_family: derivedGpu,
                      }));
                    }
                  }}
                />
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-[11px] text-gray-400">
                      WebGL Vendor (厂商提供商)
                    </label>
                    <span className="text-[10px] text-gray-500">可自动推导或手动覆盖</span>
                  </div>
                  <input
                    type="text"
                    className="input w-full text-xs font-mono"
                    placeholder="默认留空由种子推导，或输入 NVIDIA Corporation / Apple / Intel Inc."
                    value={form.webgl_vendor ?? ""}
                    onChange={(e) => {
                      const val = e.target.value || null;
                      const lower = (val || "").toLowerCase();
                      const derivedGpu = lower.includes("nvidia") ? "nvidia" : lower.includes("intel") ? "intel" : "auto";
                      setForm((prev) => ({
                        ...prev,
                        webgl_vendor: val,
                        gpu_family: derivedGpu,
                      }));
                    }}
                  />
                </div>
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-[11px] text-gray-400">
                      WebGL Renderer (渲染器 / GPU 型号)
                    </label>
                    <span className="text-[10px] text-gray-500">直接输入 GPU 型号即可</span>
                  </div>
                  <input
                    type="text"
                    className="input w-full text-xs font-mono"
                    placeholder="输入 GPU 型号，如 NVIDIA GeForce RTX 4060 或 Apple M2"
                    value={form.webgl_renderer ?? ""}
                    onChange={(e) => {
                      const val = e.target.value || null;
                      let updatedVendor = form.webgl_vendor;
                      if (val && (!updatedVendor || updatedVendor === "auto")) {
                        const lower = val.toLowerCase();
                        if (lower.includes("nvidia") || lower.includes("geforce") || lower.includes("rtx") || lower.includes("gtx")) {
                          updatedVendor = "NVIDIA Corporation";
                        } else if (lower.includes("intel") || lower.includes("iris") || lower.includes("arc")) {
                          updatedVendor = "Intel Inc.";
                        } else if (lower.includes("amd") || lower.includes("radeon")) {
                          updatedVendor = "AMD";
                        } else if (lower.includes("apple") || lower.startsWith("m1") || lower.startsWith("m2") || lower.startsWith("m3") || lower.startsWith("m4")) {
                          updatedVendor = "Apple";
                        }
                      }
                      const vendorLower = (updatedVendor || "").toLowerCase();
                      const derivedGpu = vendorLower.includes("nvidia") ? "nvidia" : vendorLower.includes("intel") ? "intel" : "auto";
                      setForm((prev) => ({
                        ...prev,
                        webgl_renderer: val,
                        webgl_vendor: updatedVendor,
                        gpu_family: derivedGpu,
                      }));
                    }}
                  />
                </div>
              </div>
              <p className="text-[10px] text-gray-500">
                💡 提示：在【自定义输入】时，直接在渲染器中填入 GPU 型号（如 <code className="text-gray-400">NVIDIA GeForce RTX 4060</code> 或 <code className="text-gray-400">Apple M2</code>），系统会自动推导填充对应的 Vendor 提供商并注入底层内核。
              </p>
            </div>

            {/* Fingerprint Noise & Privacy */}
            <div className="pt-2 border-t border-border/50 space-y-2">
              <div className="text-[11px] font-medium text-gray-400">指纹微扰与防追踪：</div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <label className="flex items-start gap-2 text-xs text-gray-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={form.canvas_noise ?? true}
                    onChange={(e) => set("canvas_noise", e.target.checked)}
                    className="rounded border-border bg-surface-2 mt-0.5"
                  />
                  <div>
                    <span className="font-medium text-gray-200">Canvas 噪点保护</span>
                    <span className="block text-[10px] text-gray-500">
                      注入轻微噪点，扰乱跨站画布哈希追踪
                    </span>
                  </div>
                </label>

                <label className="flex items-start gap-2 text-xs text-gray-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={form.audio_noise ?? true}
                    onChange={(e) => set("audio_noise", e.target.checked)}
                    className="rounded border-border bg-surface-2 mt-0.5"
                  />
                  <div>
                    <span className="font-medium text-gray-200">AudioContext 音频噪点</span>
                    <span className="block text-[10px] text-gray-500">
                      混淆声学生成特征，阻止音频指纹
                    </span>
                  </div>
                </label>

                <label className="flex items-start gap-2 text-xs text-gray-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={form.do_not_track ?? false}
                    onChange={(e) => set("do_not_track", e.target.checked)}
                    className="rounded border-border bg-surface-2 mt-0.5"
                  />
                  <div>
                    <span className="font-medium text-gray-200">请勿追踪 (Do Not Track)</span>
                    <span className="block text-[10px] text-gray-500">
                      发送 DNT: 1 并置 navigator.doNotTrack
                    </span>
                  </div>
                </label>
              </div>
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
                <CustomSelect
                  id="human_preset"
                  value={form.human_preset ?? "default"}
                  options={HUMAN_PRESET_OPTIONS}
                  onChange={(val) => set("human_preset", String(val || "default"))}
                />
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
              {form.browser_type === "cloakbrowser" ? "Chrome Extensions / 扩展插件" : "Firefox Addons / 扩展插件"}
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

        {/* Firefox User Preferences (about:config) - Only shown for Camoufox */}
        {form.browser_type === "camoufox" && (
          <details className="rounded-md border border-border bg-surface-1 p-3">
            <summary className="cursor-pointer text-xs font-semibold text-gray-400 uppercase tracking-wider flex items-center justify-between">
              <span>Firefox 首选项配置 (User Preferences / about:config)</span>
              <span className="text-[10px] text-gray-500 font-normal">
                {Object.keys(form.firefox_user_prefs ?? {}).length} 个自定义项
              </span>
            </summary>
            <p className="text-xs text-gray-500 my-3">
              直接定制 Camoufox Firefox 内核的 <code>about:config</code> 底层首选项参数（如代理控制、网络协议、渲染参数等）。
            </p>

            {/* Existing Preferences Table */}
            {Object.keys(form.firefox_user_prefs ?? {}).length > 0 ? (
              <div className="border border-border/70 rounded-lg overflow-hidden mb-3">
                <table className="w-full text-xs text-left">
                  <thead className="bg-surface-2 text-gray-400 text-[11px] uppercase border-b border-border/70">
                    <tr>
                      <th className="py-2 px-3">首选项名称 (Preference Name)</th>
                      <th className="py-2 px-3">类型</th>
                      <th className="py-2 px-3">值 (Value)</th>
                      <th className="py-2 px-3 text-right">操作</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/50">
                    {Object.entries(form.firefox_user_prefs ?? {}).map(([key, val]) => {
                      const valType = typeof val;
                      return (
                        <tr key={key} className="hover:bg-surface-2/40">
                          <td className="py-2 px-3 font-mono text-gray-200">{key}</td>
                          <td className="py-2 px-3">
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-3 text-gray-300 font-mono">
                              {valType}
                            </span>
                          </td>
                          <td className="py-2 px-3 font-mono text-indigo-300">
                            {String(val)}
                          </td>
                          <td className="py-2 px-3 text-right">
                            <button
                              type="button"
                              onClick={() => removeFirefoxPref(key)}
                              className="text-gray-400 hover:text-rose-400 transition"
                              title="删除此配置"
                            >
                              <Trash2 className="h-3.5 w-3.5 inline" />
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="text-xs text-gray-500 italic p-3 bg-surface-2/40 rounded-lg mb-3 border border-border/40">
                暂无自定义 about:config 首选项。可使用下方表单添加。
              </div>
            )}

            {/* Add Preference Inputs */}
            <div className="p-2.5 rounded-lg bg-surface-2 border border-border/60 space-y-2">
              <div className="text-[11px] font-medium text-gray-400">添加首选项：</div>
              <div className="grid grid-cols-1 md:grid-cols-12 gap-2 items-center">
                <div className="md:col-span-6">
                  <input
                    type="text"
                    className="input w-full text-xs font-mono py-1.5"
                    placeholder="例如: media.peerconnection.enabled"
                    value={prefKeyInput}
                    onChange={(e) => setPrefKeyInput(e.target.value)}
                  />
                </div>
                <div className="md:col-span-2">
                  <select
                    className="input w-full text-xs py-1.5"
                    value={prefTypeInput}
                    onChange={(e) => setPrefTypeInput(e.target.value as "boolean" | "number" | "string")}
                  >
                    <option value="string">String</option>
                    <option value="boolean">Boolean</option>
                    <option value="number">Number</option>
                  </select>
                </div>
                <div className="md:col-span-3">
                  {prefTypeInput === "boolean" ? (
                    <select
                      className="input w-full text-xs py-1.5 font-mono"
                      value={prefValInput || "true"}
                      onChange={(e) => setPrefValInput(e.target.value)}
                    >
                      <option value="true">true</option>
                      <option value="false">false</option>
                    </select>
                  ) : (
                    <input
                      type={prefTypeInput === "number" ? "number" : "text"}
                      className="input w-full text-xs font-mono py-1.5"
                      placeholder="值 (Value)"
                      value={prefValInput}
                      onChange={(e) => setPrefValInput(e.target.value)}
                    />
                  )}
                </div>
                <div className="md:col-span-1">
                  <button
                    type="button"
                    onClick={addFirefoxPref}
                    className="btn-secondary w-full text-xs py-1.5 flex justify-center items-center"
                    title="添加"
                  >
                    <Plus className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            </div>
          </details>
        )}

        {/* Advanced Launch Arguments */}
        <details className="rounded-md border border-border bg-surface-1 p-3">
          <summary className="cursor-pointer text-xs font-semibold text-gray-400 uppercase tracking-wider flex items-center justify-between">
            <span>
              高级启动参数 (Launch Arguments - {form.browser_type === "camoufox" ? "Firefox" : "Chromium"})
            </span>
            <span className="text-[10px] text-gray-500 font-normal">
              {(form.launch_args ?? []).length} 个已配置参数
            </span>
          </summary>
          <p className="text-xs text-gray-500 my-3">
            {form.browser_type === "camoufox"
              ? "针对 Camoufox (Firefox) 内核的 CLI 启动参数（如 -mute-audio, -private-window 等）。"
              : "针对 Chromium 内核的自定义 CLI 启动标志。注意：已安全剔除 --disable-gpu 等降低反爬可信度的参数。"}
          </p>

          {form.browser_type !== "camoufox" && isOldKernel && (
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

          {form.browser_type !== "camoufox" && hasInlineProxyAuthArg && (
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
              {(form.browser_type === "camoufox" ? FIREFOX_ARG_PRESETS : CHROMIUM_ARG_PRESETS).map((preset) => {
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

          {/* Ignored Default Arguments Section - Only relevant for Chromium */}
          {form.browser_type !== "camoufox" && (
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
          )}

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
              placeholder={form.browser_type === "camoufox" ? "-mute-audio 或 -private-window" : "--disable-features=Foo 或 ignore: --arg"}
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
