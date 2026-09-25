import { useEffect, useState } from "react";
import {
  Loader2,
  X,
  Plus,
  Trash2,
  CheckCircle2,
  ShieldCheck,
  ExternalLink,
  Cpu,
  Info,
  FolderTree,
  Key,
  Cloud,
} from "lucide-react";
import { api, type SystemStatus, type SettingsUpdate } from "../lib/api";
import { BackupRestorePanel } from "./BackupRestorePanel";

interface SettingsPanelProps {
  onClose: () => void;
  onSaved: (status: SystemStatus) => void;
  onOpenKernelManager?: () => void;
  systemStatus?: SystemStatus | null;
}

export function SettingsPanel({
  onClose,
  onSaved,
  onOpenKernelManager,
  systemStatus,
}: SettingsPanelProps) {
  const [activeTab, setActiveTab] = useState<"cloakbrowser" | "camoufox" | "general" | "backup">("cloakbrowser");
  const [licenses, setLicenses] = useState<
    { id: string; name: string; key: string; placeholder?: string; is_default: boolean }[]
  >([]);
  const [channel, setChannel] = useState<"stable" | "preview">("stable");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getSettings()
      .then((s) => {
        setChannel(s.release_channel === "preview" ? "preview" : "stable");
        setLicenses(
          s.licenses?.map((l) => ({
            id: l.id,
            name: l.name,
            key: "", // Keep empty to avoid accidental overwriting; placeholder holds masked value
            placeholder: l.key_masked,
            is_default: l.is_default,
          })) || []
        );
      })
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load settings")
      );
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const payloadLicenses = licenses.map((l) => ({
        id: l.id,
        name: l.name,
        key: l.key,
        is_default: l.is_default,
      }));

      const payload: SettingsUpdate = {
        release_channel: channel,
        licenses: payloadLicenses,
      };

      const status = await api.updateSettings(payload);
      onSaved(status);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save settings");
    } finally {
      setSaving(false);
    }
  };

  const addLicense = () => {
    setLicenses([
      ...licenses,
      {
        id: `lic-${Date.now()}`,
        name: `License ${licenses.length + 1}`,
        key: "",
        is_default: licenses.length === 0,
      },
    ]);
  };

  const removeLicense = (id: string) => {
    const newLicenses = licenses.filter((l) => l.id !== id);
    if (newLicenses.length > 0 && !newLicenses.some((l) => l.is_default)) {
      const first = newLicenses[0];
      if (first) {
        newLicenses[0] = { ...first, is_default: true };
      }
    }
    setLicenses(newLicenses);
  };

  const setDefault = (id: string) => {
    setLicenses(licenses.map((l) => ({ ...l, is_default: l.id === id })));
  };

  const updateLicense = (
    id: string,
    field: "name" | "key",
    value: string
  ) => {
    setLicenses(
      licenses.map((l) => (l.id === id ? { ...l, [field]: value } : l))
    );
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl rounded-xl border border-border bg-surface-1 shadow-2xl flex flex-col max-h-[90vh] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-3.5 bg-surface-1 shrink-0">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold text-gray-100">设置 / Settings</h2>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-200 transition-colors p-1 rounded-md hover:bg-surface-2"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Engine Tabs */}
        <div className="flex border-b border-border px-5 pt-2 bg-surface-0/60 shrink-0 gap-2">
          <button
            type="button"
            onClick={() => setActiveTab("cloakbrowser")}
            className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 transition-colors ${
              activeTab === "cloakbrowser"
                ? "border-blue-500 text-blue-400"
                : "border-transparent text-gray-400 hover:text-gray-200 hover:border-gray-700"
            }`}
          >
            <span className="w-2 h-2 rounded-full bg-blue-500 inline-block" />
            CloakBrowser (Chromium)
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("camoufox")}
            className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 transition-colors ${
              activeTab === "camoufox"
                ? "border-orange-500 text-orange-400"
                : "border-transparent text-gray-400 hover:text-gray-200 hover:border-gray-700"
            }`}
          >
            <span className="w-2 h-2 rounded-full bg-orange-500 inline-block" />
            Camoufox (Firefox)
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("general")}
            className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 transition-colors ${
              activeTab === "general"
                ? "border-accent text-accent"
                : "border-transparent text-gray-400 hover:text-gray-200 hover:border-gray-700"
            }`}
          >
            <Info className="w-3.5 h-3.5" />
            通用信息 (General)
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("backup")}
            className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 transition-colors ${
              activeTab === "backup"
                ? "border-purple-500 text-purple-400"
                : "border-transparent text-gray-400 hover:text-gray-200 hover:border-gray-700"
            }`}
          >
            <Cloud className="w-3.5 h-3.5" />
            备份与恢复 (Backup & Restore)
          </button>
        </div>

        {/* Content Area */}
        <div className="p-5 space-y-6 overflow-y-auto flex-1">
          {/* TAB 1: CloakBrowser */}
          {activeTab === "cloakbrowser" && (
            <div className="space-y-6">
              {/* Tab Header Card */}
              <div className="flex items-center justify-between p-3 rounded-lg border border-blue-500/20 bg-blue-500/5">
                <div className="flex items-center gap-2.5">
                  <div className="w-8 h-8 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400">
                    <Key className="w-4 h-4" />
                  </div>
                  <div>
                    <h3 className="text-xs font-semibold text-gray-200">
                      CloakBrowser 专有配置
                    </h3>
                    <p className="text-[11px] text-gray-400">
                      基于 Chromium 内核的反指纹引擎，支持配置商业授权码以解锁 Pro 补丁与并发配额
                    </p>
                  </div>
                </div>
                <span className="text-[11px] px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 font-mono shrink-0">
                  商业内核 · 支持 Pro
                </span>
              </div>

              {/* License Management */}
              <div>
                <div className="flex items-center justify-between mb-2.5">
                  <div>
                    <label className="text-xs font-medium text-gray-200 block">
                      CloakBrowser 授权密钥管理 (License Keys)
                    </label>
                    <p className="text-[11px] text-gray-400">
                      支持添加多个授权，并在不同 Profile 环境中单独指定生效的授权
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={addLicense}
                    className="btn-secondary text-xs flex items-center gap-1.5 py-1 px-2.5"
                  >
                    <Plus className="w-3.5 h-3.5" /> 添加授权
                  </button>
                </div>

                <div className="space-y-3">
                  {licenses.map((lic) => (
                    <div
                      key={lic.id}
                      className="flex flex-col gap-2 p-3 border border-border rounded-lg bg-surface-0/80 relative"
                    >
                      <div className="flex gap-2 items-start">
                        <div className="flex-1 space-y-2">
                          <input
                            className="input text-xs"
                            placeholder="授权备注名称 (如: Team Pro 1)"
                            value={lic.name}
                            onChange={(e) =>
                              updateLicense(lic.id, "name", e.target.value)
                            }
                          />
                          <input
                            className="input font-mono text-xs"
                            type="password"
                            placeholder={
                              lic.placeholder
                                ? `当前密钥: ${lic.placeholder} (若无需更改请留空)`
                                : "请输入 CloakBrowser License Key (如: cb_...)"
                            }
                            value={lic.key}
                            onChange={(e) =>
                              updateLicense(lic.id, "key", e.target.value)
                            }
                          />
                        </div>
                        <div className="flex flex-col gap-2 shrink-0 pt-0.5">
                          <button
                            type="button"
                            title={
                              lic.is_default
                                ? "当前默认授权 (Default License)"
                                : "设为默认授权"
                            }
                            className={`p-1.5 rounded transition-colors ${
                              lic.is_default
                                ? "text-accent bg-accent/15 border border-accent/30"
                                : "text-gray-500 hover:bg-surface-2 hover:text-gray-300 border border-transparent"
                            }`}
                            onClick={() => setDefault(lic.id)}
                          >
                            <CheckCircle2 className="w-4 h-4" />
                          </button>
                          <button
                            type="button"
                            title="删除此授权"
                            className="p-1.5 rounded text-gray-500 hover:text-red-400 hover:bg-surface-2 transition-colors"
                            onClick={() => removeLicense(lic.id)}
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </div>
                      {lic.is_default && (
                        <div className="text-[11px] text-accent flex items-center gap-1">
                          <CheckCircle2 className="w-3 h-3" /> 默认授权：新创建的 CloakBrowser 环境将优先采用此 Key
                        </div>
                      )}
                    </div>
                  ))}

                  {licenses.length === 0 && (
                    <div className="text-xs text-gray-400 text-center py-6 border border-dashed border-border rounded-lg bg-surface-0/40 space-y-2">
                      <p>未配置商业授权，CloakBrowser 将以免费版 (Keyless) 运行。</p>
                      <div className="flex items-center justify-center gap-3 text-xs">
                        <a
                          href="https://cloakbrowser.dev/free"
                          target="_blank"
                          rel="noreferrer"
                          className="text-accent hover:underline flex items-center gap-1"
                        >
                          获取免费 Key <ExternalLink className="w-3 h-3" />
                        </a>
                        <span className="text-gray-600">|</span>
                        <a
                          href="https://cloakbrowser.dev/#pricing"
                          target="_blank"
                          rel="noreferrer"
                          className="text-gray-400 hover:text-gray-200 flex items-center gap-1"
                        >
                          了解 Pro 商业方案 <ExternalLink className="w-3 h-3" />
                        </a>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Release Channel */}
              <div className="pt-3 border-t border-border">
                <label className="text-xs font-medium text-gray-200 block mb-1">
                  官方分发发布渠道 (Release Channel)
                </label>
                <p className="text-[11px] text-gray-400 mb-2">
                  选择 CloakBrowser 内核官方二进制文件的下载源（仅控制 CloakBrowser，不影响 Camoufox）
                </p>
                <select
                  className="input text-xs"
                  value={channel}
                  onChange={(e) =>
                    setChannel(
                      e.target.value === "preview" ? "preview" : "stable"
                    )
                  }
                >
                  <option value="stable">Stable (稳定官方版 - 推荐)</option>
                  <option value="preview">Preview (抢先预览版 - 体验最新特性)</option>
                </select>
              </div>
            </div>
          )}

          {/* TAB 2: Camoufox */}
          {activeTab === "camoufox" && (
            <div className="space-y-5">
              {/* Tab Header Card */}
              <div className="flex items-center justify-between p-3 rounded-lg border border-orange-500/20 bg-orange-500/5">
                <div className="flex items-center gap-2.5">
                  <div className="w-8 h-8 rounded-lg bg-orange-500/10 border border-orange-500/20 flex items-center justify-center text-orange-400">
                    <ShieldCheck className="w-4 h-4" />
                  </div>
                  <div>
                    <h3 className="text-xs font-semibold text-gray-200">
                      Camoufox 内核说明
                    </h3>
                    <p className="text-[11px] text-gray-400">
                      基于 Firefox 源码深度定制的开源反指纹浏览器
                    </p>
                  </div>
                </div>
                <span className="text-[11px] px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono shrink-0">
                  开源内核 · 永久免费
                </span>
              </div>

              {/* Free & Open Source Card */}
              <div className="p-4 rounded-lg border border-border bg-surface-0 space-y-3">
                <div className="flex items-start gap-2.5">
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                  <div className="space-y-1">
                    <h4 className="text-xs font-medium text-gray-200">
                      免授权与开源特性
                    </h4>
                    <p className="text-xs text-gray-400 leading-relaxed">
                      Camoufox 遵循 GPL-3.0 协议开源发布。所有反指纹对抗特性（包括 C++ 源码级指纹混淆、字体微扰、Canvas/Audio 微扰及完整的硬件伪装）均<strong>完全免费开放</strong>，无需配置任何商业授权码或激活密钥，开箱即用。
                    </p>
                  </div>
                </div>
              </div>

              {/* GitHub Distribution Source Card */}
              <div className="p-4 rounded-lg border border-border bg-surface-0 space-y-3">
                <div className="flex items-start gap-2.5">
                  <FolderTree className="w-4 h-4 text-blue-400 shrink-0 mt-0.5" />
                  <div className="space-y-1">
                    <h4 className="text-xs font-medium text-gray-200">
                      版本获取与分发机制
                    </h4>
                    <p className="text-xs text-gray-400 leading-relaxed">
                      Camoufox 内核二进制文件直接从 GitHub 官方 Releases 仓库（<code>daijro/camoufox</code>）下载，并由系统内置的包管理器自动解压至数据目录，不存在商业 CDN 渠道区分。
                    </p>
                  </div>
                </div>
              </div>

              {/* Quick Actions */}
              <div className="p-4 rounded-lg border border-border bg-surface-0/60 flex items-center justify-between gap-4">
                <div>
                  <h4 className="text-xs font-medium text-gray-200">内核版本管理</h4>
                  <p className="text-[11px] text-gray-400">
                    如需查看、下载或切换不同的 Camoufox 内核版本，请使用内核管理器。
                  </p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {onOpenKernelManager && (
                    <button
                      type="button"
                      onClick={onOpenKernelManager}
                      className="btn-secondary text-xs flex items-center gap-1.5"
                    >
                      <Cpu className="w-3.5 h-3.5" /> 打开内核管理器
                    </button>
                  )}
                  <a
                    href="https://github.com/daijro/camoufox"
                    target="_blank"
                    rel="noreferrer"
                    className="btn-secondary text-xs flex items-center gap-1.5"
                  >
                    <ExternalLink className="w-3.5 h-3.5" /> GitHub 仓库
                  </a>
                </div>
              </div>
            </div>
          )}

          {/* TAB 3: General Information */}
          {activeTab === "general" && (
            <div className="space-y-5">
              <div className="flex items-center gap-2.5 p-3 rounded-lg border border-border bg-surface-0">
                <Info className="w-4 h-4 text-accent shrink-0" />
                <div>
                  <h3 className="text-xs font-semibold text-gray-200">系统环境与运行信息</h3>
                  <p className="text-[11px] text-gray-400">AntiBrowser-Manager 双内核管理器运行环境概览</p>
                </div>
              </div>

              <div className="p-4 rounded-lg border border-border bg-surface-0 space-y-3 text-xs">
                <div className="flex justify-between py-1.5 border-b border-border/60">
                  <span className="text-gray-400">宿主操作系统 (Host OS)</span>
                  <span className="font-mono text-gray-200">
                    {systemStatus?.host_os || "自动检测"}
                  </span>
                </div>
                <div className="flex justify-between py-1.5 border-b border-border/60">
                  <span className="text-gray-400">运行时模式 (Runtime Mode)</span>
                  <span className="font-mono text-gray-200">
                    {systemStatus?.runtime_mode || "local"}
                  </span>
                </div>
                <div className="flex justify-between py-1.5 border-b border-border/60">
                  <span className="text-gray-400">显示交互模式 (Viewer Mode)</span>
                  <span className="font-mono text-gray-200">
                    {systemStatus?.viewer_mode || "native"}
                  </span>
                </div>
                <div className="flex justify-between py-1.5 border-b border-border/60">
                  <span className="text-gray-400">扩展插件隔离目录</span>
                  <span className="font-mono text-gray-300 text-[11px]">
                    extensions/chromium, extensions/firefox
                  </span>
                </div>
                <div className="flex justify-between py-1.5">
                  <span className="text-gray-400">双内核支持</span>
                  <span className="text-emerald-400 font-medium">
                    CloakBrowser (Chromium) &amp; Camoufox (Firefox)
                  </span>
                </div>
              </div>

              <div className="p-3.5 rounded-lg border border-border/80 bg-surface-0/40 text-[11px] text-gray-400 space-y-1.5">
                <p className="font-medium text-gray-300">💡 关于双内核防关联架构：</p>
                <p>
                  AntiBrowser-Manager 已在环境存储、插件隔离、命令行启动参数及底层指纹特征层面实现 Chromium 与 Firefox 的完全物理解耦。您可以随时在单个 Profile 的配置界面自由切换内核类型，系统将自适应匹配对应内核的特征库与首选项。
                </p>
              </div>
            </div>
          )}

          {/* TAB 4: Backup & Restore */}
          {activeTab === "backup" && <BackupRestorePanel />}

          {error && <p className="text-xs text-red-400">{error}</p>}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-border px-5 py-3.5 bg-surface-1 shrink-0">
          <div className="text-[11px] text-gray-500">
            {activeTab === "cloakbrowser" && "配置仅作用于 CloakBrowser 内核"}
            {activeTab === "camoufox" && "Camoufox 引擎免授权开箱即用"}
            {activeTab === "general" && "系统状态正常运行中"}
            {activeTab === "backup" && "备份包已受 AES-256-GCM 端到端加密与 SHA-256 校验保护"}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={saving}
              className="btn-secondary text-xs"
            >
              {activeTab === "backup" ? "完成 / Close" : "取消 / Close"}
            </button>
            {activeTab !== "backup" && (
              <button
                type="button"
                onClick={handleSave}
                disabled={saving}
                className="btn-primary text-xs flex items-center gap-1.5"
              >
                {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                <span>{saving ? "保存中…" : "保存设置"}</span>
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
