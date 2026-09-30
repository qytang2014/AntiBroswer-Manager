import { useState, useEffect, useRef, useCallback, forwardRef, useImperativeHandle } from "react";
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
  FileCheck,
  ChevronDown,
  ChevronUp,
  RotateCcw,
  Sparkles,
  Save,
} from "lucide-react";
import {
  api,
  type BackupBackend,
  type BackupConfig,
  type BackupConfigUpdate,
  type BackupFile,
  type BackupProgressEvent,
} from "../lib/api";
import { CustomSelect, CustomSelectOption } from "./common/CustomSelect";

const BACKUP_INTERVAL_OPTIONS: CustomSelectOption<number>[] = [
  { value: 0, label: "禁用自动备份", sublabel: "仅在需要时手动触发备份", badge: "手动", badgeVariant: "gray" },
  { value: 6, label: "每 6 小时", sublabel: "高频快照备份", badge: "高频", badgeVariant: "blue" },
  { value: 12, label: "每 12 小时", sublabel: "半天自动快照", badge: "推荐", badgeVariant: "emerald" },
  { value: 24, label: "每天一次 (24 小时)", sublabel: "日常定期保护", badge: "常用", badgeVariant: "blue" },
  { value: 168, label: "每周一次 (7 天)", sublabel: "周度常规存档", badge: "低频", badgeVariant: "gray" },
];

export interface BackupRestorePanelHandle {
  saveConfig: () => Promise<boolean>;
}

export const BackupRestorePanel = forwardRef<BackupRestorePanelHandle>((_props, ref) => {
  const [loading, setLoading] = useState(false);
  const [config, setConfig] = useState<BackupConfig | null>(null);
  const [backups, setBackups] = useState<BackupFile[]>([]);
  const [backupsLoading, setBackupsLoading] = useState(false);

  // Settings fold state (auto-expanded if not configured)
  const [settingsExpanded, setSettingsExpanded] = useState<boolean>(false);

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

  // Progress state for active backup
  const [activeBackupTask, setActiveBackupTask] = useState<BackupProgressEvent | null>(null);
  const backupAbortRef = useRef<AbortController | null>(null);
  const [fullBackupConfirmOpen, setFullBackupConfirmOpen] = useState(false);

  // Restore Modal & In-place progress state
  const [restoreModalFile, setRestoreModalFile] = useState<BackupFile | null>(null);
  const [restorePassword, setRestorePassword] = useState("");
  const [restoring, setRestoring] = useState(false);
  const [restoreTask, setRestoreTask] = useState<BackupProgressEvent | null>(null);
  const restoreAbortRef = useRef<AbortController | null>(null);

  // Load config & backups
  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const cfg = await api.getBackupConfig();
      setConfig(cfg);
      if (cfg.backend) {
        setBackend(cfg.backend);
        setSettingsExpanded(false);
      } else {
        setSettingsExpanded(true); // Open settings by default if no backend is set
      }

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
      setBackups([]);
    } finally {
      setBackupsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
    refreshBackupsList();

    // Check if there is an active backup or restore task running in background
    api.getBackupStatus().then((res) => {
      if (res.active && res.task) {
        setActiveBackupTask(res.task);
        if (res.task.type === "backup" && res.task.task_id) {
          const abortCtrl = new AbortController();
          backupAbortRef.current = abortCtrl;
          api.subscribeBackupProgress(
            res.task.task_id,
            (ev) => {
              setActiveBackupTask(ev);
            },
            abortCtrl.signal
          ).then(() => {
            refreshBackupsList();
            loadData();
            setTimeout(() => setActiveBackupTask(null), 5000);
          }).catch(() => {});
        }
      }
    }).catch(() => {});
  }, [loadData, refreshBackupsList]);

  // Clean up SSE aborts on unmount
  useEffect(() => {
    return () => {
      backupAbortRef.current?.abort();
      restoreAbortRef.current?.abort();
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

  const handleSaveConfig = async (): Promise<boolean> => {
    if (encryptEnabled && encryptPassword && encryptPassword !== encryptPasswordConfirm) {
      setActionFeedback({ type: "error", message: "两次输入的端到端加密密码不一致，请重新输入。" });
      return false;
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
      return true;
    } catch (err: any) {
      setActionFeedback({ type: "error", message: err.message || "保存设置失败" });
      return false;
    } finally {
      setSaving(false);
    }
  };

  useImperativeHandle(ref, () => ({
    saveConfig: handleSaveConfig,
  }));

  const handleSelectBackend = async (newBackend: BackupBackend) => {
    setBackend(newBackend);
    try {
      await api.updateBackupConfig({ backend: newBackend });
      setConfig((prev) => (prev ? { ...prev, backend: newBackend } : null));
    } catch {
      // Non-fatal background sync
    }
  };

  const handleTriggerBackup = async (overrideState?: boolean) => {
    setActionFeedback(null);
    const withState = overrideState !== undefined ? overrideState : includeBrowserState;

    try {
      const { task_id } = await api.triggerBackupNow(withState);
      const abortCtrl = new AbortController();
      backupAbortRef.current = abortCtrl;

      setActiveBackupTask({
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
            setActiveBackupTask(ev);
          },
          abortCtrl.signal
        )
        .then(() => {
          refreshBackupsList();
          loadData();
          setTimeout(() => setActiveBackupTask(null), 5000);
        })
        .catch((err) => {
          setActiveBackupTask((prev) =>
            prev ? { ...prev, status: "error", message: err.message || "备份过程中断" } : null
          );
          setActionFeedback({ type: "error", message: err.message || "备份过程中断" });
          setTimeout(() => setActiveBackupTask(null), 5000);
        });
    } catch (err: any) {
      setActionFeedback({ type: "error", message: err.message || "启动备份失败" });
    }
  };

  const handleOpenRestoreModal = (file: BackupFile) => {
    setRestoreModalFile(file);
    setRestorePassword("");
    setRestoreTask(null);
    setRestoring(false);
  };

  const handleExecuteRestore = async () => {
    if (!restoreModalFile) return;
    setRestoring(true);
    setActionFeedback(null);

    // Initial progress in-modal
    setRestoreTask({
      task_id: "init",
      type: "restore",
      stage: "starting",
      percent: 5,
      message: "正在向后台提交数据恢复请求...",
      status: "running",
    });

    try {
      const { task_id } = await api.restoreBackup(restoreModalFile.name, restorePassword || undefined);

      const abortCtrl = new AbortController();
      restoreAbortRef.current = abortCtrl;

      setRestoreTask({
        task_id,
        type: "restore",
        stage: "starting",
        percent: 10,
        message: "已连接恢复任务通道，正在准备下载与校验...",
        status: "running",
      });

      api
        .subscribeBackupProgress(
          task_id,
          (ev) => {
            setRestoreTask(ev);
          },
          abortCtrl.signal
        )
        .then(() => {
          setRestoring(false);
        })
        .catch((err) => {
          setRestoring(false);
          setRestoreTask((prev) =>
            prev ? { ...prev, status: "error", message: err.message || "恢复操作异常中断" } : null
          );
          setTimeout(() => setRestoreTask(null), 5000);
        });
    } catch (err: any) {
      setRestoring(false);
      setRestoreTask({
        task_id: "error",
        type: "restore",
        stage: "error",
        percent: 100,
        message: err.message || "启动恢复任务失败",
        status: "error",
      });
      setTimeout(() => setRestoreTask(null), 5000);
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

  const isConfigured = Boolean(config?.backend);

  return (
    <div className="space-y-6">
      {/* 1. TOP HEADER & STATUS SUMMARY */}
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
        <div className="flex items-center gap-2 shrink-0">
          <span
            className={`text-[11px] px-2.5 py-0.5 rounded font-mono border ${
              isConfigured
                ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
                : "bg-amber-500/10 text-amber-400 border-amber-500/20"
            }`}
          >
            {isConfigured ? `${config?.backend?.toUpperCase()} 已连接` : "尚未配置存储"}
          </span>
        </div>
      </div>

      {/* Global Action Feedback Alert */}
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

      {/* 2. TOP ACTION CARD: IMMEDIATE BACKUP & IN-PLACE PROGRESS */}
      <div className="p-4 rounded-xl border border-border bg-surface-0/80 shadow-sm space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-purple-400" />
              <h4 className="text-xs font-semibold text-gray-200">快捷手动备份 (Instant Backup)</h4>
            </div>
            <p className="text-[11px] text-gray-400 mt-0.5">
              默认推荐快速备份（轻量、秒级打包）；全量备份包含各环境完整 Cookies 与持久化会话。
            </p>
          </div>

          <div className="flex items-center gap-2.5 shrink-0">
            {/* 快速备份 (醒目主按钮，默认推荐) */}
            <button
              type="button"
              disabled={Boolean(activeBackupTask) || !isConfigured}
              onClick={() => handleTriggerBackup(false)}
              className="btn-primary text-xs flex items-center gap-1.5 py-2 px-4 shadow-sm font-medium"
              title="打包 profiles.db、settings.json 和 extensions，快速且轻量"
            >
              {activeBackupTask ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Cloud className="w-3.5 h-3.5" />
              )}
              <span>快速备份 (推荐)</span>
            </button>

            {/* 全量备份 (次级按钮，需二次确认) */}
            <button
              type="button"
              disabled={Boolean(activeBackupTask) || !isConfigured}
              onClick={() => setFullBackupConfirmOpen(true)}
              className="btn-secondary text-xs flex items-center gap-1.5 py-2 px-3 text-gray-300 hover:text-gray-100 hover:border-gray-500/50"
              title="包含全部浏览器环境完整会话、本地存储和 Cookies，体积较大"
            >
              <Database className="w-3.5 h-3.5 text-gray-400" />
              <span>全量备份 (含全部会话)</span>
            </button>
          </div>
        </div>

        {/* Live In-place Backup Progress Bar (Displayed directly inside the action card) */}
        {activeBackupTask && (
          <div className="pt-2 border-t border-border/80 space-y-2.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                {activeBackupTask.status === "completed" ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                ) : activeBackupTask.status === "error" ? (
                  <AlertCircle className="w-4 h-4 text-red-400" />
                ) : (
                  <Loader2 className="w-4 h-4 animate-spin text-purple-400" />
                )}
                <span className="text-xs font-medium text-gray-200">
                  {activeBackupTask.status === "completed"
                    ? "备份完成！"
                    : activeBackupTask.status === "error"
                    ? "备份失败"
                    : "正在执行云端备份与安全上传..."}
                </span>
              </div>
              <span className="text-xs font-mono font-medium text-purple-400">
                {activeBackupTask.percent}%
              </span>
            </div>

            {/* Visual animated progress track */}
            <div className="w-full bg-surface-1 rounded-full h-2 overflow-hidden border border-border">
              <div
                className={`h-full transition-all duration-300 ${
                  activeBackupTask.status === "error"
                    ? "bg-red-500"
                    : activeBackupTask.status === "completed"
                    ? "bg-emerald-500"
                    : "bg-gradient-to-r from-purple-500 to-blue-500"
                }`}
                style={{ width: `${activeBackupTask.percent}%` }}
              />
            </div>

            <div className="flex items-center justify-between text-[11px] text-gray-400 font-mono">
              <span>{activeBackupTask.message}</span>
              {activeBackupTask.filename && (
                <span className="text-gray-300">目标: {activeBackupTask.filename}</span>
              )}
            </div>
          </div>
        )}
      </div>

      {/* 3. REMOTE BACKUPS LIST & RESTORE SECTION (PROMINENT MIDDLE POSITION) */}
      <div className="space-y-3">
        <div className="flex items-center justify-between border-b border-border pb-2">
          <div className="flex items-center gap-2">
            <ArrowDownToLine className="w-4 h-4 text-accent" />
            <h4 className="text-xs font-semibold text-gray-200">远端历史备份版本 (Remote Backups)</h4>
            <span className="text-[11px] font-mono text-gray-400">({backups.length})</span>
          </div>

          <button
            type="button"
            disabled={backupsLoading || !isConfigured}
            onClick={refreshBackupsList}
            className="text-xs text-gray-400 hover:text-gray-200 flex items-center gap-1.5 transition-colors px-2 py-1 rounded hover:bg-surface-0"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${backupsLoading ? "animate-spin" : ""}`} />
            刷新列表
          </button>
        </div>

        {backups.length === 0 ? (
          <div className="text-center py-8 border border-dashed border-border rounded-lg bg-surface-0/40">
            <Cloud className="w-8 h-8 mx-auto text-gray-500 mb-2" />
            <p className="text-xs text-gray-300 font-medium">暂无远端备份记录</p>
            <p className="text-[11px] text-gray-400 mt-1 max-w-sm mx-auto">
              {!isConfigured
                ? "请在下方配置 WebDAV 或 S3 存储后端，随后即可点击上方「快速备份」创建首个备份点。"
                : "远端存储已就绪，点击上方「快速备份」或「全量备份」即可立即创建云端备份。"}
            </p>
          </div>
        ) : (
          <div className="border border-border rounded-lg overflow-hidden bg-surface-0/60 divide-y divide-border">
            {backups.map((bk) => (
              <div
                key={bk.name}
                className="flex items-center justify-between p-3.5 hover:bg-surface-1/40 transition-colors"
              >
                <div className="space-y-1.5">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-mono text-xs font-semibold text-gray-200">{bk.name}</span>
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
                      {bk.mode === "full" ? "全量会话" : "仅配置"}
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

                <div className="flex items-center gap-2 shrink-0">
                  <button
                    type="button"
                    onClick={() => handleOpenRestoreModal(bk)}
                    className="btn-secondary text-xs flex items-center gap-1 py-1.5 px-3 hover:text-emerald-400 transition-colors"
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

      {/* 4. STORAGE BACKEND & SECURITY SETTINGS (COLLAPSIBLE / BELOW LIST) */}
      <div className="border border-border rounded-xl bg-surface-0/60 overflow-hidden">
        {/* Collapsible Header */}
        <button
          type="button"
          onClick={() => setSettingsExpanded(!settingsExpanded)}
          className="w-full flex items-center justify-between p-3.5 hover:bg-surface-1/40 transition-colors text-left"
        >
          <div className="flex items-center gap-2.5">
            <div className="w-6 h-6 rounded bg-surface-1 border border-border flex items-center justify-center text-gray-400">
              <Database className="w-3.5 h-3.5 text-accent" />
            </div>
            <div>
              <h4 className="text-xs font-semibold text-gray-200">
                存储后端与高级安全配置 (Storage & Security Settings)
              </h4>
              <p className="text-[11px] text-gray-400">
                {isConfigured
                  ? `当前配置：${config?.backend?.toUpperCase()} (${config?.backend === "webdav" ? config?.webdav_url : config?.s3_bucket})`
                  : "点击展开配置 WebDAV 或 S3 存储参数"}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 text-gray-400">
            <span className="text-xs">{settingsExpanded ? "收起配置" : "展开配置"}</span>
            {settingsExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </div>
        </button>

        {/* Collapsible Content */}
        {settingsExpanded && (
          <div className="p-4 pt-1 border-t border-border space-y-6">
            {/* Backend Tabs Selector */}
            <div className="flex items-center justify-between pt-2">
              <label className="text-xs font-medium text-gray-300">选择远端存储协议：</label>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => handleSelectBackend("webdav")}
                  className={`px-3 py-1.5 text-xs rounded border transition-colors ${
                    backend === "webdav"
                      ? "bg-accent/10 border-accent text-accent font-medium"
                      : "bg-surface-0 border-border text-gray-400 hover:text-gray-200"
                  }`}
                >
                  WebDAV / OpenList
                </button>
                <button
                  type="button"
                  onClick={() => handleSelectBackend("s3")}
                  className={`px-3 py-1.5 text-xs rounded border transition-colors ${
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
              <div className="space-y-3 p-3.5 bg-surface-1/40 border border-border rounded-lg">
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
                      {config?.webdav_password_set && (
                        <span className="text-[10px] text-emerald-400 ml-1.5 font-normal">● 密码已安全保存</span>
                      )}
                    </label>
                    <input
                      className="input text-xs font-mono"
                      type="password"
                      placeholder={config?.webdav_password_set ? "已保存密码 (••••••••) 若无需变更请留空" : "输入 WebDAV 密码"}
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
              <div className="space-y-3 p-3.5 bg-surface-1/40 border border-border rounded-lg">
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
                      {config?.s3_secret_key_set && (
                        <span className="text-[10px] text-emerald-400 ml-1.5 font-normal">● 密钥已安全保存</span>
                      )}
                    </label>
                    <input
                      className="input text-xs font-mono"
                      type="password"
                      placeholder={config?.s3_secret_key_set ? "已保存密钥 (••••••••) 若无需变更请留空" : "输入 Secret Access Key"}
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

            {/* Storage Quick Test Action */}
            <div className="flex items-center justify-between pt-1">
              <button
                type="button"
                disabled={testing}
                onClick={handleTestConnection}
                className="btn-secondary text-xs flex items-center gap-1.5 py-1.5 px-3"
              >
                {testing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <HardDrive className="w-3.5 h-3.5" />}
                测试存储连通性 (Test Connection)
              </button>

              <span className="text-[11px] text-gray-400">
                填写存储与加密参数后，请在下方点击保存
              </span>
            </div>

            {/* Security & Automation Settings Cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-3 border-t border-border">
              {/* Encryption card */}
              <div className="p-3.5 bg-surface-1/40 border border-border rounded-lg space-y-3">
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
                    <div className="w-9 h-5 bg-surface-0 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-purple-600"></div>
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
                          <span className="text-emerald-400 ml-1.5 font-normal">● 密码已安全保存</span>
                        )}
                      </label>
                      <input
                        className="input text-xs font-mono"
                        type="password"
                        placeholder={config?.encrypt_password_set ? "已保存密码 (••••••••) 若无需更改请留空" : "输入高强度密码"}
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

                    <div className="pt-1.5">
                      <button
                        type="button"
                        disabled={saving}
                        onClick={handleSaveConfig}
                        className="w-full btn-secondary text-xs flex items-center justify-center gap-1.5 py-1.5 text-purple-300 border-purple-500/30 hover:bg-purple-500/10 hover:border-purple-500/50 transition-colors"
                      >
                        {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                        <span>确认保存加密设置</span>
                      </button>
                    </div>
                  </div>
                )}
              </div>

              {/* Automation & Retention card */}
              <div className="p-3.5 bg-surface-1/40 border border-border rounded-lg space-y-3">
                <div className="flex items-center gap-2">
                  <Clock className="w-4 h-4 text-accent" />
                  <span className="text-xs font-medium text-gray-200">自动定时备份与保留策略</span>
                </div>

                <div className="space-y-3">
                  <div>
                    <label htmlFor="auto_backup_interval" className="text-[11px] text-gray-300 block mb-1">
                      备份执行周期
                    </label>
                    <CustomSelect
                      id="auto_backup_interval"
                      value={autoBackupInterval}
                      options={BACKUP_INTERVAL_OPTIONS}
                      onChange={(val) => setAutoBackupInterval(val ?? 0)}
                      size="sm"
                    />
                  </div>

                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label htmlFor="retain_count" className="text-[11px] text-gray-300">
                        保留历史备份份数
                      </label>
                      <span className="text-[10px] text-gray-400">保留最新份数，超出自动轮转清理</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <input
                        id="retain_count"
                        type="number"
                        min={1}
                        max={100}
                        className="input text-xs font-mono w-28"
                        value={retainCount}
                        onChange={(e) => setRetainCount(Math.max(1, Number(e.target.value)))}
                      />
                      <span className="text-xs text-gray-400">份</span>
                    </div>
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
                    <span>定时自动备份时包含浏览器持久化会话与 Cookies (全量模式)</span>
                  </label>
                  <p className="text-[10px] text-gray-400 mt-0.5 ml-5">
                    默认不勾选（推荐快速轻量备份，仅备份指纹配置、扩展及数据库）。勾选后自动备份体积较大。
                  </p>
                </div>

                {config?.last_backup_at && (
                  <p className="text-[11px] text-gray-400 font-mono">
                    最近自动备份时间: {new Date(config.last_backup_at).toLocaleString()}
                  </p>
                )}
              </div>
            </div>

            {/* Master Bottom Actions Bar */}
            <div className="flex flex-col sm:flex-row items-center justify-between gap-3 pt-3.5 border-t border-border mt-2 bg-surface-1/40 -mx-4 -mb-4 p-4 rounded-b-xl">
              <div className="text-[11px] text-gray-400 flex items-center gap-1.5">
                <ShieldCheck className="w-4 h-4 text-purple-400 shrink-0" />
                <span>保存将同步更新远端存储源、AES-256-GCM 加密密钥与自动备份策略。</span>
              </div>

              <div className="flex items-center gap-2.5 w-full sm:w-auto justify-end">
                <button
                  type="button"
                  disabled={testing}
                  onClick={handleTestConnection}
                  className="btn-secondary text-xs flex items-center gap-1.5 py-2 px-3.5"
                >
                  {testing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <HardDrive className="w-3.5 h-3.5" />}
                  测试存储连接
                </button>

                <button
                  type="button"
                  disabled={saving}
                  onClick={handleSaveConfig}
                  className="btn-primary text-xs flex items-center gap-1.5 py-2 px-5 font-medium shadow-md shadow-accent/20"
                >
                  {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                  保存所有备份与加密配置
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* 5. IN-PLACE RESTORE PROGRESS MODAL */}
      {restoreModalFile && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="bg-surface-0 border border-border rounded-xl shadow-2xl max-w-md w-full p-5 space-y-4">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <div className="flex items-center gap-2 text-amber-400">
                {restoreTask?.status === "completed" ? (
                  <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
                ) : restoreTask?.status === "error" ? (
                  <AlertCircle className="w-5 h-5 text-red-400 shrink-0" />
                ) : restoring ? (
                  <Loader2 className="w-5 h-5 animate-spin text-blue-400 shrink-0" />
                ) : (
                  <AlertTriangle className="w-5 h-5 shrink-0" />
                )}
                <h3 className="text-sm font-semibold text-gray-100">
                  {restoreTask?.status === "completed"
                    ? "数据恢复成功"
                    : restoreTask?.status === "error"
                    ? "数据恢复失败"
                    : restoring
                    ? "正在恢复数据..."
                    : "确认恢复备份"}
                </h3>
              </div>
              {!restoring && (
                <button
                  type="button"
                  onClick={() => {
                    setRestoreModalFile(null);
                    setRestoreTask(null);
                  }}
                  className="text-gray-400 hover:text-gray-200 text-xs p-1"
                >
                  ✕
                </button>
              )}
            </div>

            {/* In-place progress view during/after restore */}
            {restoreTask ? (
              <div className="space-y-4 py-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-gray-200">
                    {restoreTask.status === "completed"
                      ? "所有系统数据与配置已恢复完毕！"
                      : restoreTask.status === "error"
                      ? "恢复过程出现异常"
                      : "正在执行原子级系统还原..."}
                  </span>
                  <span className="text-xs font-mono font-medium text-purple-400">
                    {restoreTask.percent}%
                  </span>
                </div>

                <div className="w-full bg-surface-1 rounded-full h-2.5 overflow-hidden border border-border">
                  <div
                    className={`h-full transition-all duration-300 ${
                      restoreTask.status === "error"
                        ? "bg-red-500"
                        : restoreTask.status === "completed"
                        ? "bg-emerald-500"
                        : "bg-gradient-to-r from-blue-500 to-emerald-500"
                    }`}
                    style={{ width: `${restoreTask.percent}%` }}
                  />
                </div>

                <div
                  className={`p-3 rounded-lg text-xs font-mono ${
                    restoreTask.status === "completed"
                      ? "bg-emerald-500/10 border border-emerald-500/30 text-emerald-300"
                      : restoreTask.status === "error"
                      ? "bg-red-500/10 border border-red-500/30 text-red-300"
                      : "bg-surface-1/60 border border-border text-gray-300"
                  }`}
                >
                  <p>{restoreTask.message}</p>
                </div>

                {restoreTask.status === "completed" && (
                  <p className="text-[11px] text-gray-400">
                    提示：恢复前已自动在本地创建应急快照。建议立即刷新页面以同步最新的环境列表。
                  </p>
                )}

                <div className="flex items-center justify-end gap-2.5 pt-2 border-t border-border">
                  {restoreTask.status === "completed" ? (
                    <>
                      <button
                        type="button"
                        onClick={() => {
                          setRestoreModalFile(null);
                          setRestoreTask(null);
                        }}
                        className="btn-secondary text-xs py-1.5 px-3"
                      >
                        关闭
                      </button>
                      <button
                        type="button"
                        onClick={() => window.location.reload()}
                        className="btn-primary text-xs flex items-center gap-1.5 py-1.5 px-4 bg-emerald-600 hover:bg-emerald-500 text-white"
                      >
                        <RotateCcw className="w-3.5 h-3.5" />
                        立即刷新页面
                      </button>
                    </>
                  ) : restoreTask.status === "error" ? (
                    <>
                      <button
                        type="button"
                        onClick={() => {
                          setRestoreModalFile(null);
                          setRestoreTask(null);
                        }}
                        className="btn-secondary text-xs py-1.5 px-3"
                      >
                        关闭
                      </button>
                      <button
                        type="button"
                        onClick={() => setRestoreTask(null)}
                        className="btn-primary text-xs py-1.5 px-3"
                      >
                        重试
                      </button>
                    </>
                  ) : null}
                </div>
              </div>
            ) : (
              /* Pre-restore confirmation & password form */
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
                    <div className="flex items-center justify-between">
                      <label className="text-xs font-medium text-gray-200 block">
                        输入解密密码 <span className="text-red-400">*</span>
                      </label>
                      {config?.encrypt_password_set && (
                        <span className="text-[11px] text-emerald-400 font-normal">● 已检测到本机默认密码</span>
                      )}
                    </div>
                    <input
                      type="password"
                      className="input text-xs font-mono"
                      placeholder={
                        config?.encrypt_password_set
                          ? "留空将自动使用本机已存密码解密，或输入其他密码"
                          : "请输入用于解密该备份包的密码"
                      }
                      value={restorePassword}
                      onChange={(e) => setRestorePassword(e.target.value)}
                    />
                    <p className="text-[10px] text-gray-400">
                      {config?.encrypt_password_set
                        ? "提示：本机已配置加密密码。若此备份来自本机直接留空即可；若来自其他设备，请输入创建时的密码。"
                        : "请输入创建该备份时设置的端到端解密密码。"}
                    </p>
                  </div>
                )}

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
            )}
          </div>
        </div>
      )}

      {/* 6. FULL BACKUP CONFIRMATION MODAL */}
      {fullBackupConfirmOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="bg-surface-0 border border-border rounded-xl shadow-2xl max-w-md w-full p-5 space-y-4 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <div className="flex items-center gap-2 text-amber-400">
                <AlertTriangle className="w-5 h-5 shrink-0" />
                <h3 className="text-sm font-semibold text-gray-100">确认执行全量备份？</h3>
              </div>
              <button
                type="button"
                onClick={() => setFullBackupConfirmOpen(false)}
                className="text-gray-400 hover:text-gray-200 text-xs p-1"
              >
                ✕
              </button>
            </div>

            <div className="space-y-3 text-xs text-gray-300">
              <p className="leading-relaxed">
                您即将执行包含浏览器<strong>全部持久化会话</strong>的完整备份。为防止一次性打包上传过多数据，请确认以下信息：
              </p>

              <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg space-y-2 text-[11px] text-amber-300">
                <div className="font-semibold flex items-center gap-1.5 text-amber-400">
                  <Database className="w-3.5 h-3.5" />
                  <span>全量备份包含内容：</span>
                </div>
                <ul className="list-disc pl-4 space-y-1 text-gray-300">
                  <li>所有浏览器环境的本地数据、Cookies、缓存、Local Storage 及登录态</li>
                  <li>系统环境数据库 (profiles.db)、核心设置与扩展程序</li>
                </ul>
                <p className="text-amber-400/90 pt-1 border-t border-amber-500/20 text-[10px]">
                  ⚠️ 提示：备份包体积可能达到数十 MB 至数 GB，打包加密与网络上传耗时较长。
                </p>
              </div>

              <div className="p-2.5 bg-blue-500/10 border border-blue-500/20 rounded-lg text-[11px] text-blue-300 flex items-start gap-2">
                <Cloud className="w-4 h-4 shrink-0 text-blue-400 mt-0.5" />
                <div>
                  <span className="font-medium text-blue-200">默认推荐「快速备份」：</span>
                  <p className="text-gray-300 mt-0.5">
                    若仅需保留环境指纹参数、代理设置、扩展程序及系统数据，快速备份体积仅几十 KB 且秒级完成。
                  </p>
                </div>
              </div>
            </div>

            <div className="flex items-center justify-end gap-2.5 pt-2 border-t border-border">
              <button
                type="button"
                onClick={() => setFullBackupConfirmOpen(false)}
                className="btn-secondary text-xs py-1.5 px-3.5"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => {
                  setFullBackupConfirmOpen(false);
                  handleTriggerBackup(true);
                }}
                className="btn-primary text-xs flex items-center gap-1.5 py-1.5 px-4 bg-amber-600 hover:bg-amber-500 text-white font-medium"
              >
                <Database className="w-3.5 h-3.5" />
                确认并开始全量备份
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
});

BackupRestorePanel.displayName = "BackupRestorePanel";
