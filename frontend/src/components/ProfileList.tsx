import { Plus, Search, Monitor, Copy, Check, ExternalLink } from "lucide-react";
import { useState } from "react";
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { api, type Profile, type SystemStatus } from "../lib/api";
import { StatusIndicator } from "./StatusIndicator";

interface ProfileListProps {
  profiles: Profile[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onReorder: (orderedIds: string[]) => void;
  systemStatus?: SystemStatus | null;
}

interface RowProps {
  profile: Profile;
  selected: boolean;
  draggable: boolean;
  onSelect: (id: string) => void;
}

export function getProxyProtocol(raw: string | null | undefined): string | null {
  if (!raw) return null;
  const trimmed = raw.trim();
  if (!trimmed) return null;

  if (trimmed.startsWith("{") && trimmed.endsWith("}")) {
    try {
      const obj = JSON.parse(trimmed);
      const outbounds = obj.outbounds || [];
      if (Array.isArray(outbounds) && outbounds.length > 0) {
        const type = outbounds[0]?.type;
        if (type) return type.toUpperCase();
      }
    } catch {
      // ignore
    }
    return "JSON";
  }

  const lower = trimmed.toLowerCase();
  if (lower.startsWith("vless://")) return "VLESS";
  if (lower.startsWith("vmess://")) return "VMESS";
  if (lower.startsWith("trojan://")) return "Trojan";
  if (lower.startsWith("hysteria2://") || lower.startsWith("hy2://")) return "Hysteria2";
  if (lower.startsWith("tuic://")) return "TUIC";
  if (lower.startsWith("ss://") || lower.startsWith("shadowsocks://")) return "SS";
  if (lower.startsWith("wireguard://") || lower.startsWith("wg://")) return "WireGuard";
  if (lower.startsWith("anytls://")) return "AnyTLS";
  if (lower.startsWith("ssh://")) return "SSH";
  if (lower.startsWith("socks5://") || lower.startsWith("socks5h://")) return "SOCKS5";
  if (lower.startsWith("socks4://") || lower.startsWith("socks4a://")) return "SOCKS4";
  if (lower.startsWith("https://")) return "HTTPS";
  if (lower.startsWith("http://")) return "HTTP";

  if (/^([^:@]+:[^:@]+@)?[\w.-]+:\d+$/.test(trimmed)) {
    return "HTTP";
  }

  return "Proxy";
}

export function formatKernelVersion(raw: string | null | undefined): string | null {
  if (!raw) return null;
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const clean = trimmed.replace(/^v+/i, "");
  const major = clean.split(".")[0];
  return major ? `v${major}` : null;
}

function SortableProfileRow({ profile, selected, draggable, onSelect }: RowProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: profile.id, disabled: !draggable });

  const proxyProtocol = getProxyProtocol(profile.proxy);
  const kernelVersion = formatKernelVersion(profile.browser_version);

  return (
    <button
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      onClick={() => onSelect(profile.id)}
      {...attributes}
      {...listeners}
      className={`w-full text-left px-3 py-2.5 rounded-md mb-1 transition-colors ${
        draggable ? "cursor-grab active:cursor-grabbing" : ""
      } ${isDragging ? "opacity-50" : ""} ${
        selected
          ? "bg-surface-3 border border-border-hover"
          : "hover:bg-surface-2 border border-transparent"
      }`}
    >
      <div className="flex items-center gap-2">
        <StatusIndicator status={profile.status} />
        <span className="text-sm font-medium truncate">{profile.name}</span>
      </div>
      {(proxyProtocol || kernelVersion) && (
        <div className="flex items-center gap-1.5 mt-1 ml-4 flex-wrap">
          {proxyProtocol && (
            <span
              className="text-[10px] px-1.5 py-0.2 rounded bg-surface-2 text-cyan-300 font-mono border border-border uppercase font-semibold"
              title={`代理协议: ${proxyProtocol}`}
            >
              {proxyProtocol}
            </span>
          )}
          {kernelVersion && (
            <span
              className="text-[10px] px-1.5 py-0.2 rounded bg-surface-2 text-indigo-300 font-mono border border-border"
              title={`内核版本: ${profile.browser_version}`}
            >
              {kernelVersion}
            </span>
          )}
        </div>
      )}
      {profile.tags.length > 0 && (
        <div className="flex gap-1 mt-1.5 ml-4 flex-wrap">
          {profile.tags.map((t) => (
            <span
              key={t.tag}
              className="text-[10px] px-1.5 py-0.5 rounded-full bg-surface-4 text-gray-400"
              style={t.color ? { backgroundColor: `${t.color}20`, color: t.color } : undefined}
            >
              {t.tag}
            </span>
          ))}
        </div>
      )}
    </button>
  );
}

export function ProfileList({
  profiles,
  selectedId,
  onSelect,
  onNew,
  onReorder,
  systemStatus,
}: ProfileListProps) {
  const [search, setSearch] = useState("");
  const [copied, setCopied] = useState(false);

  const filtered = profiles.filter((p) =>
    p.name.toLowerCase().includes(search.toLowerCase()),
  );

  const runningCount = profiles.filter((p) => p.status === "running").length;

  const fallbackCopy = (text: string) => {
    try {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      document.body.removeChild(textarea);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore
    }
  };

  const handleCopyAccessUrl = () => {
    const host = systemStatus?.server_host || "127.0.0.1";
    const port = systemStatus?.server_port ?? 52341;
    const url = systemStatus?.server_url || `http://${host}:${port}`;
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(url).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }).catch(() => {
        fallbackCopy(url);
      });
    } else {
      fallbackCopy(url);
    }
  };

  const handleOpenAccessUrl = () => {
    const host = systemStatus?.server_host || "127.0.0.1";
    const port = systemStatus?.server_port ?? 52341;
    const url = systemStatus?.server_url || `http://${host}:${port}`;
    api.openExternal(url).catch(() => {
      window.open(url, "_blank", "noopener,noreferrer");
    });
  };

  // Reordering is disabled while a search filter is active — dragging within a
  // filtered subset is ambiguous. Empty search means filtered === profiles order.
  const dragEnabled = search === "";

  // A small activation distance so a plain click still selects (no accidental drag).
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  );

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const ids = profiles.map((p) => p.id);
    const from = ids.indexOf(String(active.id));
    const to = ids.indexOf(String(over.id));
    if (from === -1 || to === -1) return;
    onReorder(arrayMove(ids, from, to));
  };

  const serverHost = systemStatus?.server_host || "127.0.0.1";
  const serverPort = systemStatus?.server_port ?? 52341;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="p-4 border-b border-border">
        <div className="flex items-center gap-2 mb-3">
          <Monitor className="h-4 w-4 text-accent" />
          <h1 className="text-sm font-semibold tracking-tight">AntiBrowser-Manager</h1>
        </div>
        {runningCount > 0 && (
          <div className="text-xs text-gray-500 mb-3">
            {runningCount} running
          </div>
        )}
        {/* Search */}
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-500" />
          <input
            type="text"
            placeholder="Search profiles..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="input pl-8 py-1.5 text-xs"
          />
        </div>
      </div>

      {/* Profile list */}
      <div className="flex-1 overflow-y-auto p-2">
        {filtered.length === 0 && (
          <div className="text-center text-gray-500 text-xs py-8">
            {profiles.length === 0 ? "No profiles yet" : "No matches"}
          </div>
        )}
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <SortableContext items={filtered.map((p) => p.id)} strategy={verticalListSortingStrategy}>
            {filtered.map((profile) => (
              <SortableProfileRow
                key={profile.id}
                profile={profile}
                selected={selectedId === profile.id}
                draggable={dragEnabled}
                onSelect={onSelect}
              />
            ))}
          </SortableContext>
        </DndContext>
      </div>

      {/* Footer: New profile button & address badge */}
      <div className="p-3 border-t border-border space-y-2">
        <button onClick={onNew} className="btn-secondary w-full flex items-center justify-center gap-1.5">
          <Plus className="h-3.5 w-3.5" />
          <span>New Profile</span>
        </button>

        <div className="pt-1 flex flex-col gap-1.5">
          <div className="flex items-center gap-1.5 w-full">
            <button
              type="button"
              onClick={handleOpenAccessUrl}
              className="flex-1 flex items-center gap-1.5 px-2.5 py-1.5 bg-surface-2 hover:bg-surface-3 rounded border border-border text-[11px] text-gray-300 hover:text-white transition-colors group cursor-pointer min-w-0"
              title="在浏览器中打开 / Open in browser"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse shrink-0" />
              <span className="truncate font-mono">
                {serverHost}:{serverPort}
              </span>
              <ExternalLink className="h-3 w-3 ml-auto opacity-60 group-hover:opacity-100 transition-opacity shrink-0" />
            </button>
            <button
              type="button"
              onClick={handleCopyAccessUrl}
              className="p-1.5 bg-surface-2 hover:bg-surface-3 rounded border border-border text-gray-400 hover:text-gray-200 transition-colors shrink-0 cursor-pointer"
              title={copied ? "已复制" : "复制访问地址 / Copy address"}
            >
              {copied ? (
                <Check className="h-3.5 w-3.5 text-emerald-400" />
              ) : (
                <Copy className="h-3.5 w-3.5" />
              )}
            </button>
          </div>
          <div className="text-[10px] text-gray-500 text-center font-mono select-none">
            v{systemStatus?.app_version || "0.1.0"}
          </div>
        </div>
      </div>
    </div>
  );
}
