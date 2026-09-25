import { useState, useEffect, useRef, useCallback } from "react";
import {
  Cloud,
  Lock,
  ShieldCheck,
  Database,
  RefreshCw,
  Loader2,
  CheckCircle2,
  AlertCircle,
  AlertTriangle,
  ArrowDownToLine,
  Trash2,
  HardDrive,
  Clock,
  Shield,
  FileCheck,
} from "lucide-react";
import {
  api,
  type BackupBackend,
  type BackupConfig,
  type BackupConfigUpdate,
  type BackupFile,
  type BackupProgressEvent,
} from "../lib/api";

export function BackupRestorePanel() {
  const [loading, setLoading] = useState(false);
  const [config, setConfig] = useState<BackupConfig | null>(null);
  const [backups, setBackups] = useState<BackupFile[]>([]);
  const [backupsLoading, setBackupsLoading] = useState(false);

  // Form states
  const [backend, setBackend] = useState<BackupBackend>("webdav");
  const [webdavUrl, setWebdavUrl] = useState("");
  const [webdavUsername, setWebdavUsername] = useState("");
  const [webdavPassword, setWebdavPassword] = useState("");
  const [webdavRemotePath, setWebdavRemotePath] = useState("/antibrowser_backups");
  const [webdavSkipSsl, setWebdavSkipSsl] = useState(false);

  const [s3EndpointUrl, setS3EndpointUrl] = useState("");
  const [s3AccessKey, setS3AccessKey] = useState("");
  const [s3SecretKey, setS3SecretKey] = useState("");
  const [s3Bucket, setS3Bucket] = useState("");
  const [s3Prefix, setS3Prefix] = useState("antibrowser_backups");
  const [s3Region, setS3Region] = useState("us-east-1");

  const [encryptEnabled, setEncryptEnabled] = useState(false);
  const [encryptPassword, setEncryptPassword] = useState("");
  const [encryptPasswordConfirm, setEncryptPasswordConfirm] = useState("");

  const [autoBackupInterval, setAutoBackupInterval] = useState(0);
  const [retainCount, setRetainCount] = useState(10);
  const [includeBrowserState, setIncludeBrowserState] = useState(false);

  // Status & Feedback
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [actionFeedback, setActionFeedback] = useState<{ type: "success" | "error"; message: string } | null>(null);

  // Progress state for active backup/restore
  const [activeTask, setActiveTask] = useState<BackupProgressEvent | null>(null);
  const progressAbortRef = useRef<AbortController | null>(null);

  // Restore Modal state
  const [restoreModalFile, setRestoreModalFile] = useState<BackupFile | null>(null);
  const [restorePassword, setRestorePassword] = useState("");
  const [restoring, setRestoring] = useState(false);

  // Load config & backups
  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const cfg = await api.getBackupConfig();
      setConfig(cfg);
      if (cfg.backend) setBackend(cfg.backend);
      setWebdavUrl(cfg.webdav_url || "");
      setWebdavUsername(cfg.webdav_username || "");
      setWebdavRemotePath(cfg.webdav_remote_path || "/antibrowser_backups");
      setWebdavSkipSsl(Boolean(cfg.webdav_skip_ssl));

      setS3EndpointUrl(cfg.s3_endpoint_url || "");
      setS3AccessKey(cfg.s3_access_key || "");
      setS3Bucket(cfg.s3_bucket || "");
      setS3Prefix(cfg.s3_prefix || "antibrowser_backups");
      setS3Region(cfg.s3_region || "us-east-1");

      setEncryptEnabled(Boolean(cfg.encrypt_enabled));
      setAutoBackupInterval(cfg.auto_backup_interval_hours || 0);
      setRetainCount(cfg.retain_count || 10);
      setIncludeBrowserState(Boolean(cfg.include_browser_state));
    } catch (err: any) {
      setActionFeedback({ type: "error", message: err.message || "加载备份配置失败" });
    } finally {
      setLoading(false);
    }
  }, []);

  const refreshBackupsList = useCallback(async () => {
    setBackupsLoading(true);
    try {
      const list = await api.listBackups();
      setBackups(list);
    } catch (err: any) {
      // Backend may not be configured yet, ignore in silent mode
      setBackups([]);
    } finally {
      setBackupsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
    refreshBackupsList();
  }, [loadData, refreshBackupsList]);

  // Clean up SSE abort on unmount
  useEffect(() => {
    return () => {
      progressAbortRef.current?.abort();
    };
  }, []);

  const handleTestConnection = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const payload: BackupConfigUpdate = {
        backend,
        webdav_url: webdavUrl,
        webdav_username: webdavUsername,
        webdav_password: webdavPassword || undefined,
        webdav_remote_path: webdavRemotePath,
        webdav_skip_ssl: webdavSkipSsl,
        s3_endpoint_url: s3EndpointUrl || undefined,
        s3_access_key: s3AccessKey,
        s3_secret_key: s3SecretKey || undefined,
        s3_bucket: s3Bucket,
        s3_prefix: s3Prefix,
        s3_region: s3Region,
      };
      const res = await api.testBackupConnection(payload);
      if (res.ok) {
        setTestResult({ ok: true, message: "连接成功！远端存储配置有效且可读写。" });
      } else {
        setTestResult({ ok: false, message: res.error || "连接测试失败，请检查配置参数与网络。" });
      }
    } catch (err: any) {
      setTestResult({ ok: false, message: err.message || "测试连接发生错误" });
    } finally {
      setTesting(false);
    }
  };

  const handleSaveConfig = async () => {
    if (encryptEnabled && encryptPassword && encryptPassword !== encryptPasswordConfirm) {
      setActionFeedback({ type: "error", message: "两次输入的端到端加密密码不一致，请重新输入。" });
      return;
    }

    setSaving(true);
    setActionFeedback(null);
    try {
      const payload: BackupConfigUpdate = {
        backend,
        webdav_url: webdavUrl,
        webdav_username: webdavUsername,
        webdav_password: webdavPassword || undefined,
        webdav_remote_path: webdavRemotePath,
        webdav_skip_ssl: webdavSkipSsl,
        s3_endpoint_url: s3EndpointUrl || undefined,
        s3_access_key: s3AccessKey,
        s3_secret_key: s3SecretKey || undefined,
        s3_bucket: s3Bucket,
        s3_prefix: s3Prefix,
        s3_region: s3Region,
        encrypt_enabled: encryptEnabled,
        encrypt_password: encryptPassword || undefined,
        auto_backup_interval_hours: autoBackupInterval,
        retain_count: retainCount,
        include_browser_state: includeBrowserState,
      };

      const updated = await api.updateBackupConfig(payload);
      setConfig(updated);
      setWebdavPassword("");
      setS3SecretKey("");
      setEncryptPassword("");
      setEncryptPasswordConfirm("");
      setActionFeedback({ type: "success", message: "备份与恢复设置已成功保存！" });
      refreshBackupsList();
    } catch (err: any) {
      setActionFeedback({ type: "error", message: err.message || "保存设置失败" });
    } finally {
      setSaving(false);
    }
  };

  const handleTriggerBackup = async (overrideState?: boolean) => {
    setActionFeedback(null);
    const withState = overrideState !== undefined ? overrideState : includeBrowserState;

    try {
      const { task_id } = await api.triggerBackupNow(withState);
      const abortCtrl = new AbortController();
      progressAbortRef.current = abortCtrl;

      setActiveTask({
        task_id,
        type: "backup",
        stage: "starting",
        percent: 0,
        message: "正在准备备份...",
        status: "running",
      });

      api
        .subscribeBackupProgress(
          task_id,
          (ev) => {
            setActiveTask(ev);
          },
          abortCtrl.signal
        )
        .then(() => {
          refreshBackupsList();
          loadData();
          setTimeout(() => setActiveTask(null), 4000);
        })
        .catch((err) => {
          setActionFeedback({ type: "error", message: err.message || "备份过程中断" });
        });
    } catch (err: any) {
      setActionFeedback({ type: "error", message: err.message || "启动备份失败" });
    }
  };

  const handleOpenRestoreModal = (file: BackupFile) => {
    setRestoreModalFile(file);
    setRestorePassword("");
  };

  const handleExecuteRestore = async () => {
    if (!restoreModalFile) return;
    setRestoring(true);
    setActionFeedback(null);

    try {
      const { task_id } = await api.restoreBackup(restoreModalFile.name, restorePassword || undefined);
      setRestoreModalFile(null);

      const abortCtrl = new AbortController();
      progressAbortRef.current = abortCtrl;

      setActiveTask({
        task_id,
        type: "restore",
        stage: "starting",
        percent: 0,
        message: "正在准备恢复数据...",
        status: "running",
      });

      api
        .subscribeBackupProgress(
          task_id,
          (ev) => {
            setActiveTask(ev);
          },
          abortCtrl.signal
        )
        .then(() => {
          setTimeout(() => setActiveTask(null), 5000);
        })
        .catch((err) => {
          setActionFeedback({ type: "error", message: err.message || "数据恢复失败" });
        });
    } catch (err: any) {
      setActionFeedback({ type: "error", message: err.message || "启动恢复任务失败" });
    } finally {
      setRestoring(false);
    }
  };

  const handleDeleteBackup = async (filename: string) => {
    if (!confirm(`确定要从远端存储永久删除备份包「${filename}」吗？`)) return;
    try {
      await api.deleteBackup(filename);
      refreshBackupsList();
    } catch (err: any) {
      setActionFeedback({ type: "error", message: err.message || "删除备份失败" });
    }
  };

  const formatSize = (bytes: number) => {
    if (bytes <= 0) return "0 B";
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12 text-gray-400 gap-2">
        <Loader2 className="w-5 h-5 animate-spin" />
        <span className="text-xs">正在加载备份服务配置...</span>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Top Banner Card */}
      <div className="flex items-start justify-between p-3.5 rounded-lg border border-purple-500/20 bg-purple-500/5">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-purple-500/10 border border-purple-500/20 flex items-center justify-center text-purple-400 shrink-0">
            <Cloud className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-xs font-semibold text-gray-200">云端与多协议备份恢复</h3>
            <p className="text-[11px] text-gray-400 mt-0.5">
              支持 WebDAV、Amazon S3 及 OpenList 平台备份。具备 AES-256-GCM 端到端加密与 SHA-256 完整性防篡改校验。
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <span className="text-[11px] px-2 py-0.5 rounded bg-purple-500/10 text-purple-400 border border-purple-500/20 font-mono">
            {config?.backend ? `${config.backend.toUpperCase()}` : "未配置后端"}
          </span>
        </div>
      </div>

      {/* Global Action Feedback Banner */}
      {actionFeedback && (
        <div
          className={`flex items-center gap-2 p-3 text-xs rounded-lg border ${
            actionFeedback.type === "success"
              ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
              : "bg-red-500/10 border-red-500/30 text-red-400"
          }`}
        >
          {actionFeedback.type === "success" ? (
            <CheckCircle2 className="w-4 h-4 shrink-0" />
          ) : (
            <AlertCircle className="w-4 h-4 shrink-0" />
          )}
          <span>{actionFeedback.message}</span>
        </div>
      )}

      {/* Active Task Progress Banner */}
      {activeTask && (
        <div className="p-4 rounded-lg border border-blue-500/30 bg-blue-500/5 space-y-2.5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin text-blue-400" />
              <span className="text-xs font-medium text-blue-300">
                {activeTask.type === "backup" ? "正在执行云端备份..." : "正在恢复系统数据..."}
              </span>
            </div>
            <span className="text-xs font-mono text-blue-400">{activeTask.percent}%</span>
          </div>

          {/* Progress bar */}
          <div className="w-full bg-surface-0 rounded-full h-2 overflow-hidden border border-border">
            <div
              className={`h-full transition-all duration-300 ${
                activeTask.status === "error" ? "bg-red-500" : "bg-blue-500"
              }`}
              style={{ width: `${activeTask.percent}%` }}
            />
          </div>

          <p className="text-[11px] text-gray-400 font-mono">{activeTask.message}</p>
        </div>
      )}

      {/* Storage Backend Configuration Section */}
      <div className="space-y-4">
        <div className="flex items-center justify-between border-b border-border pb-2">
          <div className="flex items-center gap-2">
            <Database className="w-4 h-4 text-accent" />
            <h4 className="text-xs font-semibold text-gray-200">远端存储配置 (Storage Backend)</h4>
          </div>

          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setBackend("webdav")}
              className={`px-2.5 py-1 text-xs rounded border transition-colors ${
                backend === "webdav"
                  ? "bg-accent/10 border-accent text-accent font-medium"
                  : "bg-surface-0 border-border text-gray-400 hover:text-gray-200"
              }`}
            >
              WebDAV / OpenList
            </button>
            <button
              type="button"
              onClick={() => setBackend("s3")}
              className={`px-2.5 py-1 text-xs rounded border transition-colors ${
                backend === "s3"
                  ? "bg-accent/10 border-accent text-accent font-medium"
                  : "bg-surface-0 border-border text-gray-400 hover:text-gray-200"
              }`}
            >
              Amazon S3 / 对象存储
            </button>
          </div>
        </div>

        {/* WebDAV Settings Form */}
        {backend === "webdav" && (
          <div className="space-y-3 p-3.5 bg-surface-0/60 border border-border rounded-lg">
            <div>
              <label className="text-xs font-medium text-gray-300 block mb-1">
                WebDAV 服务端地址 (URL) <span className="text-red-400">*</span>
              </label>
              <input
                className="input text-xs font-mono"
                placeholder="例如: https://dav.example.com/dav 或 http://192.168.1.100:5244/dav"
                value={webdavUrl}
                onChange={(e) => setWebdavUrl(e.target.value)}
              />
              <p className="text-[11px] text-gray-400 mt-1">
                支持各类 NAS (群晖、QNAP)、Nextcloud、Alist 及 OpenList 内置的 WebDAV 协议接口。
              </p>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium text-gray-300 block mb-1">用户名 (Username)</label>
                <input
                  className="input text-xs"
                  placeholder="WebDAV 登录用户名"
                  value={webdavUsername}
                  onChange={(e) => setWebdavUsername(e.target.value)}
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-300 block mb-1">
                  密码 (Password)
                  {config?.backend === "webdav" && (
                    <span className="text-[10px] text-emerald-400 ml-1.5 font-normal">● 已安全保存</span>
                  )}
                </label>
                <input
                  className="input text-xs font-mono"
                  type="password"
                  placeholder={config?.backend === "webdav" ? "若无需变更请留空" : "输入 WebDAV 密码"}
                  value={webdavPassword}
                  onChange={(e) => setWebdavPassword(e.target.value)}
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3 items-center">
              <div>
                <label className="text-xs font-medium text-gray-300 block mb-1">远端备份目录 (Remote Path)</label>
                <input
                  className="input text-xs font-mono"
                  placeholder="/antibrowser_backups"
                  value={webdavRemotePath}
                  onChange={(e) => setWebdavRemotePath(e.target.value)}
                />
              </div>
              <div className="pt-5">
                <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300 select-none">
                  <input
                    type="checkbox"
                    checked={webdavSkipSsl}
                    onChange={(e) => setWebdavSkipSsl(e.target.checked)}
                    className="rounded border-border text-accent focus:ring-accent"
                  />
                  <span>忽略 SSL/TLS 证书校验 (自签名证书局域网 NAS)</span>
                </label>
              </div>
            </div>
          </div>
        )}

        {/* S3 Settings Form */}
        {backend === "s3" && (
          <div className="space-y-3 p-3.5 bg-surface-0/60 border border-border rounded-lg">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium text-gray-300 block mb-1">
                  Bucket 存储桶名称 <span className="text-red-400">*</span>
                </label>
                <input
                  className="input text-xs font-mono"
                  placeholder="例如: my-browser-backups"
                  value={s3Bucket}
                  onChange={(e) => setS3Bucket(e.target.value)}
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-300 block mb-1">Region 地区代码</label>
                <input
                  className="input text-xs font-mono"
                  placeholder="us-east-1 / auto"
                  value={s3Region}
                  onChange={(e) => setS3Region(e.target.value)}
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium text-gray-300 block mb-1">Access Key ID</label>
                <input
                  className="input text-xs font-mono"
                  placeholder="AKIA..."
                  value={s3AccessKey}
                  onChange={(e) => setS3AccessKey(e.target.value)}
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-300 block mb-1">
                  Secret Access Key
                  {config?.backend === "s3" && (
                    <span className="text-[10px] text-emerald-400 ml-1.5 font-normal">● 已安全保存</span>
                  )}
                </label>
                <input
                  className="input text-xs font-mono"
                  type="password"
                  placeholder={config?.backend === "s3" ? "若无需变更请留空" : "输入 Secret Access Key"}
                  value={s3SecretKey}
                  onChange={(e) => setS3SecretKey(e.target.value)}
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium text-gray-300 block mb-1">
                  自定义 Endpoint URL (可选兼容端点)
                </label>
                <input
                  className="input text-xs font-mono"
                  placeholder="例如: https://<account>.r2.cloudflarestorage.com"
                  value={s3EndpointUrl}
                  onChange={(e) => setS3EndpointUrl(e.target.value)}
                />
                <p className="text-[10px] text-gray-400 mt-0.5">
                  适用于 Cloudflare R2、MinIO、自建 S3 兼容网关或 OpenList S3 端点。
                </p>
              </div>
              <div>
                <label className="text-xs font-medium text-gray-300 block mb-1">路径前缀 (Prefix)</label>
                <input
                  className="input text-xs font-mono"
                  placeholder="antibrowser_backups"
                  value={s3Prefix}
                  onChange={(e) => setS3Prefix(e.target.value)}
                />
              </div>
            </div>
          </div>
        )}

        {/* Test Connection Result Banner */}
        {testResult && (
          <div
            className={`flex items-center gap-2 p-2.5 text-xs rounded border ${
              testResult.ok
                ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
                : "bg-red-500/10 border-red-500/30 text-red-400"
            }`}
          >
            {testResult.ok ? (
              <CheckCircle2 className="w-4 h-4 shrink-0" />
            ) : (
              <AlertTriangle className="w-4 h-4 shrink-0" />
            )}
            <span>{testResult.message}</span>
          </div>
        )}

        {/* Actions for Config */}
        <div className="flex items-center justify-between pt-1">
          <button
            type="button"
            disabled={testing}
            onClick={handleTestConnection}
            className="btn-secondary text-xs flex items-center gap-1.5 py-1.5 px-3"
          >
            {testing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <HardDrive className="w-3.5 h-3.5" />}
            测试连通性 (Test Connection)
          </button>

          <button
            type="button"
            disabled={saving}
            onClick={handleSaveConfig}
            className="btn-primary text-xs flex items-center gap-1.5 py-1.5 px-4"
          >
            {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
            保存存储配置
          </button>
        </div>
      </div>

      {/* Security & Automation Settings */}
      <div className="space-y-4 pt-2">
        <div className="flex items-center gap-2 border-b border-border pb-2">
          <Shield className="w-4 h-4 text-purple-400" />
          <h4 className="text-xs font-semibold text-gray-200">端到端加密与自动化策略 (Security & Automation)</h4>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Encryption card */}
          <div className="p-3.5 bg-surface-0/60 border border-border rounded-lg space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Lock className="w-4 h-4 text-purple-400" />
                <span className="text-xs font-medium text-gray-200">AES-256-GCM 端到端加密</span>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={encryptEnabled}
                  onChange={(e) => setEncryptEnabled(e.target.checked)}
                  className="sr-only peer"
                />
                <div className="w-9 h-5 bg-surface-1 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-purple-600"></div>
              </label>
            </div>

            <p className="text-[11px] text-gray-400">
              在打包上传前通过用户专属密码派生密钥，对归档全量加密。云端及第三方无法窥探任何配置数据。
            </p>

            {encryptEnabled && (
              <div className="space-y-2 pt-1">
                <div>
                  <label className="text-[11px] text-gray-300 block mb-1">
                    备份加密密码
                    {config?.encrypt_password_set && (
                      <span className="text-emerald-400 ml-1.5 font-normal">● 已存入系统钥匙串</span>
                    )}
                  </label>
                  <input
                    className="input text-xs font-mono"
                    type="password"
                    placeholder={config?.encrypt_password_set ? "如无需更改加密密码请留空" : "输入高强度密码"}
                    value={encryptPassword}
                    onChange={(e) => setEncryptPassword(e.target.value)}
                  />
                </div>
                {encryptPassword && (
                  <div>
                    <label className="text-[11px] text-gray-300 block mb-1">确认加密密码</label>
                    <input
                      className="input text-xs font-mono"
                      type="password"
                      placeholder="再次确认输入密码"
                      value={encryptPasswordConfirm}
                      onChange={(e) => setEncryptPasswordConfirm(e.target.value)}
                    />
                  </div>
                )}
                <div className="flex items-start gap-1.5 p-2 bg-amber-500/10 border border-amber-500/20 rounded text-[11px] text-amber-400">
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                  <span>重要警告：若遗忘加密密码，任何人都无法解密恢复备份文件，请务必妥善记录。</span>
                </div>
              </div>
            )}
          </div>

          {/* Automation & Retention card */}
          <div className="p-3.5 bg-surface-0/60 border border-border rounded-lg space-y-3">
            <div className="flex items-center gap-2">
              <Clock className="w-4 h-4 text-accent" />
              <span className="text-xs font-medium text-gray-200">自动定时备份与保留策略</span>
            </div>

            <div className="grid grid-cols-2 gap-2.5">
              <div>
                <label className="text-[11px] text-gray-300 block mb-1">备份执行周期</label>
                <select
                  className="input text-xs"
                  value={autoBackupInterval}
                  onChange={(e) => setAutoBackupInterval(Number(e.target.value))}
                >
                  <option value={0}>禁用自动备份</option>
                  <option value={6}>每 6 小时</option>
                  <option value={12}>每 12 小时</option>
                  <option value={24}>每天一次 (24 小时)</option>
                  <option value={168}>每周一次 (7 天)</option>
                </select>
              </div>

              <div>
                <label className="text-[11px] text-gray-300 block mb-1">保留备份份数</label>
                <input
                  type="number"
                  min={1}
                  max={100}
                  className="input text-xs font-mono"
                  value={retainCount}
                  onChange={(e) => setRetainCount(Math.max(1, Number(e.target.value)))}
                />
              </div>
            </div>

            <div>
              <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300 select-none pt-1">
                <input
                  type="checkbox"
                  checked={includeBrowserState}
                  onChange={(e) => setIncludeBrowserState(e.target.checked)}
                  className="rounded border-border text-accent focus:ring-accent"
                />
                <span>默认包含浏览器已登录状态与 Cookies (完整模式)</span>
              </label>
              <p className="text-[10px] text-gray-400 mt-0.5 ml-5">
                完整模式归档包含各环境存储数据，体积较大。取消勾选仅备份指纹配置、扩展及代理。
              </p>
            </div>

            {config?.last_backup_at && (
              <p className="text-[11px] text-gray-400 font-mono">
                最近自动备份时间: {new Date(config.last_backup_at).toLocaleString()}
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Manual Backup Actions */}
      <div className="flex items-center justify-between p-3.5 rounded-lg border border-border bg-surface-0/60">
        <div>
          <h4 className="text-xs font-semibold text-gray-200">执行手动备份</h4>
          <p className="text-[11px] text-gray-400">
            随时将当前全部浏览器环境、配置及数据库打包并安全上传到远端存储。
          </p>
        </div>

        <div className="flex gap-2">
          <button
            type="button"
            disabled={Boolean(activeTask)}
            onClick={() => handleTriggerBackup(false)}
            className="btn-secondary text-xs flex items-center gap-1.5 py-1.5 px-3"
            title="打包 profiles.db、settings.json 和 extensions，快速且轻量"
          >
            <Cloud className="w-3.5 h-3.5 text-blue-400" />
            快速备份 (仅配置)
          </button>

          <button
            type="button"
            disabled={Boolean(activeTask)}
            onClick={() => handleTriggerBackup(true)}
            className="btn-primary text-xs flex items-center gap-1.5 py-1.5 px-3.5"
            title="包含浏览器 cookies 与 session 登录态的完整全量备份"
          >
            <Database className="w-3.5 h-3.5" />
            全量备份 (含浏览器会话)
          </button>
        </div>
      </div>

      {/* Backups List & Restore Section */}
      <div className="space-y-3">
        <div className="flex items-center justify-between border-b border-border pb-2">
          <div className="flex items-center gap-2">
            <ArrowDownToLine className="w-4 h-4 text-accent" />
            <h4 className="text-xs font-semibold text-gray-200">远端历史备份版本 (Remote Backups)</h4>
            <span className="text-[11px] font-mono text-gray-400">({backups.length})</span>
          </div>

          <button
            type="button"
            disabled={backupsLoading}
            onClick={refreshBackupsList}
            className="text-xs text-gray-400 hover:text-gray-200 flex items-center gap-1 transition-colors"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${backupsLoading ? "animate-spin" : ""}`} />
            刷新列表
          </button>
        </div>

        {backups.length === 0 ? (
          <div className="text-center py-8 border border-dashed border-border rounded-lg bg-surface-0/30">
            <Cloud className="w-8 h-8 mx-auto text-gray-500 mb-2" />
            <p className="text-xs text-gray-400">暂无远端备份记录</p>
            <p className="text-[11px] text-gray-400 mt-1">
              请先在上方配置 WebDAV 或 S3 存储，并点击「快速备份」创建首个备份点。
            </p>
          </div>
        ) : (
          <div className="border border-border rounded-lg overflow-hidden bg-surface-0/60 divide-y divide-border">
            {backups.map((bk) => (
              <div
                key={bk.name}
                className="flex items-center justify-between p-3 hover:bg-surface-1/40 transition-colors"
              >
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs font-medium text-gray-200">{bk.name}</span>
                    {bk.encrypted ? (
                      <span className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-400 border border-purple-500/20 font-mono">
                        <Lock className="w-2.5 h-2.5" /> 已加密
                      </span>
                    ) : (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-500/10 text-gray-400 border border-gray-500/20 font-mono">
                        未加密
                      </span>
                    )}
                    <span
                      className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${
                        bk.mode === "full"
                          ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                          : "bg-blue-500/10 text-blue-400 border border-blue-500/20"
                      }`}
                    >
                      {bk.mode === "full" ? "全量状态" : "仅配置"}
                    </span>
                    {bk.checksum && (
                      <span
                        className="flex items-center gap-0.5 text-[10px] text-emerald-400 font-mono"
                        title="已检测到 SHA-256 校验摘要文件，恢复时自动比对防篡改"
                      >
                        <FileCheck className="w-3 h-3" /> SHA-256
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-4 text-[11px] text-gray-400 font-mono">
                    <span>时间: {new Date(bk.created_at).toLocaleString()}</span>
                    <span>大小: {formatSize(bk.size_bytes)}</span>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    disabled={Boolean(activeTask)}
                    onClick={() => handleOpenRestoreModal(bk)}
                    className="btn-secondary text-xs flex items-center gap-1 py-1 px-2.5 hover:text-emerald-400 transition-colors"
                  >
                    <ArrowDownToLine className="w-3.5 h-3.5" />
                    恢复到本地
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDeleteBackup(bk.name)}
                    className="p-1.5 text-gray-400 hover:text-red-400 transition-colors rounded hover:bg-red-500/10"
                    title="从远端永久删除"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Restore Confirmation Modal */}
      {restoreModalFile && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="bg-surface-0 border border-border rounded-xl shadow-2xl max-w-md w-full p-5 space-y-4">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <div className="flex items-center gap-2 text-amber-400">
                <AlertTriangle className="w-5 h-5 shrink-0" />
                <h3 className="text-sm font-semibold text-gray-100">确认恢复备份</h3>
              </div>
              <button
                type="button"
                onClick={() => setRestoreModalFile(null)}
                className="text-gray-400 hover:text-gray-200 text-xs"
              >
                ✕
              </button>
            </div>

            <div className="space-y-3 text-xs text-gray-300">
              <p>
                即将从备份包 <strong className="text-gray-100 font-mono">{restoreModalFile.name}</strong> 恢复系统数据。
              </p>

              <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg space-y-1 text-[11px] text-amber-300">
                <p className="font-semibold">⚠️ 注意事项：</p>
                <ul className="list-disc pl-4 space-y-1">
                  <li>恢复操作将覆盖本地现有的 Profiles 数据库、设置及扩展。</li>
                  <li>所有正在运行的浏览器实例必须已关闭，否则恢复将被拒绝。</li>
                  <li>系统在恢复前会自动为您创建一份本地应急快照。</li>
                </ul>
              </div>

              {restoreModalFile.encrypted && (
                <div className="space-y-1.5 pt-1">
                  <label className="text-xs font-medium text-gray-200 block">
                    输入解密密码 <span className="text-red-400">*</span>
                  </label>
                  <input
                    type="password"
                    className="input text-xs font-mono"
                    placeholder="请输入用于解密该备份包的密码"
                    value={restorePassword}
                    onChange={(e) => setRestorePassword(e.target.value)}
                  />
                  <p className="text-[10px] text-gray-400">
                    若本机钥匙串中存有此密码将自动尝试解密，也可手动指定新密码。
                  </p>
                </div>
              )}
            </div>

            <div className="flex items-center justify-end gap-2.5 pt-2 border-t border-border">
              <button
                type="button"
                disabled={restoring}
                onClick={() => setRestoreModalFile(null)}
                className="btn-secondary text-xs py-1.5 px-3"
              >
                取消
              </button>
              <button
                type="button"
                disabled={restoring}
                onClick={handleExecuteRestore}
                className="btn-primary text-xs flex items-center gap-1.5 py-1.5 px-4 bg-amber-600 hover:bg-amber-500 text-white"
              >
                {restoring ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ShieldCheck className="w-3.5 h-3.5" />}
                确认并开始恢复
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
