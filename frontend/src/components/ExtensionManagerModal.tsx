import React, { useState, useEffect } from "react";
import { X, Upload, Download, Trash2, CheckCircle2, AlertCircle, Loader2 } from "lucide-react";
import { api, Extension, PopularExtension, ApiError } from "../lib/api";

interface ExtensionManagerModalProps {
  isOpen: boolean;
  onClose: () => void;
  onExtensionsChanged?: () => void;
}

export function ExtensionManagerModal({
  isOpen,
  onClose,
  onExtensionsChanged,
}: ExtensionManagerModalProps) {
  const [activeTab, setActiveTab] = useState<"webstore" | "popular" | "upload">("webstore");
  const [extensions, setExtensions] = useState<Extension[]>([]);
  const [popular, setPopular] = useState<PopularExtension[]>([]);
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [webstoreInput, setWebstoreInput] = useState("");
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const fetchExtensions = async () => {
    try {
      setLoading(true);
      const list = await api.listExtensions();
      setExtensions(list);
    } catch (err) {
      console.error("Failed to load extensions:", err);
    } finally {
      setLoading(false);
    }
  };

  const fetchPopular = async () => {
    try {
      const list = await api.getPopularExtensions();
      setPopular(list);
    } catch (err) {
      console.error("Failed to load popular extensions:", err);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchExtensions();
      fetchPopular();
      setFeedback(null);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const handleInstallFromWebStore = async (idOrUrl?: string) => {
    const target = idOrUrl || webstoreInput;
    if (!target.trim()) return;

    setActionLoading(true);
    setFeedback(null);
    try {
      const installed = await api.installFromWebStore(target.trim());
      setFeedback({ type: "success", text: `Successfully installed "${installed.name}"!` });
      setWebstoreInput("");
      await fetchExtensions();
      onExtensionsChanged?.();
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Failed to install from Web Store";
      setFeedback({ type: "error", text: msg });
    } finally {
      setActionLoading(false);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setActionLoading(true);
    setFeedback(null);
    try {
      const installed = await api.uploadExtension(file);
      setFeedback({ type: "success", text: `Successfully installed "${installed.name}"!` });
      e.target.value = "";
      await fetchExtensions();
      onExtensionsChanged?.();
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Failed to upload extension";
      setFeedback({ type: "error", text: msg });
    } finally {
      setActionLoading(false);
    }
  };

  const handleDelete = async (extId: string, name: string) => {
    if (!confirm(`Are you sure you want to remove extension "${name}"?`)) return;

    setActionLoading(true);
    setFeedback(null);
    try {
      await api.deleteExtension(extId);
      setFeedback({ type: "success", text: `Removed "${name}".` });
      await fetchExtensions();
      onExtensionsChanged?.();
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Failed to delete extension";
      setFeedback({ type: "error", text: msg });
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="bg-gray-900 border border-gray-800 rounded-xl w-full max-w-2xl shadow-2xl flex flex-col max-h-[85vh] overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-800 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="h-8 w-8 rounded-lg bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400 font-bold">
              🧩
            </div>
            <div>
              <h2 className="text-base font-semibold text-white">Extension Store & Manager</h2>
              <p className="text-xs text-gray-400">Install Chrome extensions for all browser profiles</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white p-1 rounded-lg hover:bg-gray-800 transition"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Feedback Alert */}
        {feedback && (
          <div
            className={`mx-6 mt-4 p-3 rounded-lg text-xs flex items-center gap-2 ${
              feedback.type === "success"
                ? "bg-emerald-950/40 text-emerald-300 border border-emerald-800/40"
                : "bg-red-950/40 text-red-300 border border-red-800/40"
            }`}
          >
            {feedback.type === "success" ? (
              <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
            ) : (
              <AlertCircle className="h-4 w-4 shrink-0 text-red-400" />
            )}
            <span className="flex-1">{feedback.text}</span>
          </div>
        )}

        {/* Installation Tabs */}
        <div className="px-6 pt-4 pb-2 border-b border-gray-800/60">
          <div className="flex gap-2 text-xs font-medium">
            <button
              className={`px-3 py-1.5 rounded-md transition ${
                activeTab === "webstore"
                  ? "bg-indigo-600 text-white"
                  : "text-gray-400 hover:text-gray-200 hover:bg-gray-800"
              }`}
              onClick={() => setActiveTab("webstore")}
            >
              Web Store ID / URL
            </button>
            <button
              className={`px-3 py-1.5 rounded-md transition ${
                activeTab === "popular"
                  ? "bg-indigo-600 text-white"
                  : "text-gray-400 hover:text-gray-200 hover:bg-gray-800"
              }`}
              onClick={() => setActiveTab("popular")}
            >
              Popular Extensions
            </button>
            <button
              className={`px-3 py-1.5 rounded-md transition ${
                activeTab === "upload"
                  ? "bg-indigo-600 text-white"
                  : "text-gray-400 hover:text-gray-200 hover:bg-gray-800"
              }`}
              onClick={() => setActiveTab("upload")}
            >
              Upload .crx / .zip
            </button>
          </div>

          <div className="mt-3 pb-2">
            {activeTab === "webstore" && (
              <div className="flex gap-2">
                <input
                  className="input flex-1 text-xs"
                  value={webstoreInput}
                  onChange={(e) => setWebstoreInput(e.target.value)}
                  placeholder="https://chromewebstore.google.com/detail/... or 32-char ID"
                  disabled={actionLoading}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleInstallFromWebStore();
                  }}
                />
                <button
                  type="button"
                  className="btn-primary text-xs px-4 flex items-center gap-1.5 disabled:opacity-50"
                  onClick={() => handleInstallFromWebStore()}
                  disabled={actionLoading || !webstoreInput.trim()}
                >
                  {actionLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
                  Install
                </button>
              </div>
            )}

            {activeTab === "popular" && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-48 overflow-y-auto pr-1">
                {popular.map((item) => {
                  const isInstalled = extensions.some(
                    (e) => e.webstore_id === item.id || e.name.toLowerCase().includes(item.name.toLowerCase())
                  );
                  return (
                    <div
                      key={item.id}
                      className="p-2.5 rounded-lg border border-gray-800 bg-gray-800/40 flex items-center justify-between gap-2"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="text-xs font-semibold text-white truncate">{item.name}</div>
                        <div className="text-[11px] text-gray-400 truncate">{item.description}</div>
                      </div>
                      <button
                        type="button"
                        className={`text-xs px-2.5 py-1 rounded transition shrink-0 ${
                          isInstalled
                            ? "bg-gray-700/50 text-gray-400 cursor-default"
                            : "btn-secondary text-indigo-300 hover:text-white"
                        }`}
                        disabled={actionLoading || isInstalled}
                        onClick={() => handleInstallFromWebStore(item.id)}
                      >
                        {isInstalled ? "Installed" : "Install"}
                      </button>
                    </div>
                  );
                })}
              </div>
            )}

            {activeTab === "upload" && (
              <div className="border-2 border-dashed border-gray-700 rounded-lg p-4 text-center hover:border-gray-600 transition">
                <input
                  type="file"
                  id="ext-file-upload"
                  className="hidden"
                  accept=".crx,.zip"
                  onChange={handleFileUpload}
                  disabled={actionLoading}
                />
                <label
                  htmlFor="ext-file-upload"
                  className="cursor-pointer flex flex-col items-center justify-center gap-1.5 text-xs text-gray-300"
                >
                  <Upload className="h-5 w-5 text-indigo-400" />
                  <span>Click to browse and upload <code className="text-indigo-300">.crx</code> or <code className="text-indigo-300">.zip</code></span>
                  <span className="text-[10px] text-gray-500">Unpacks automatically into persistent extension library</span>
                </label>
              </div>
            )}
          </div>
        </div>

        {/* Installed Extensions List */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
              Installed Extensions ({extensions.length})
            </h3>
            {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-gray-400" />}
          </div>

          {extensions.length === 0 && !loading ? (
            <div className="text-center py-8 text-gray-500 text-xs">
              No extensions installed yet. Use the tabs above to install from Chrome Web Store or upload a file.
            </div>
          ) : (
            <div className="space-y-2">
              {extensions.map((ext) => (
                <div
                  key={ext.id}
                  className="p-3 rounded-lg border border-gray-800 bg-gray-800/30 flex items-center justify-between gap-3 hover:border-gray-700 transition"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    {ext.icon_url ? (
                      <img src={ext.icon_url} alt={ext.name} className="h-8 w-8 rounded shrink-0 object-contain bg-gray-900/50 p-1" />
                    ) : (
                      <div className="h-8 w-8 rounded shrink-0 bg-indigo-950/60 border border-indigo-800/40 flex items-center justify-center text-indigo-300 text-xs font-bold">
                        {ext.name.charAt(0).toUpperCase()}
                      </div>
                    )}
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-white truncate">{ext.name}</span>
                        <span className="text-[10px] text-gray-400 bg-gray-800 px-1.5 py-0.2 rounded border border-gray-700">
                          v{ext.version}
                        </span>
                      </div>
                      <p className="text-[11px] text-gray-400 truncate max-w-md">
                        {ext.description || ext.path}
                      </p>
                    </div>
                  </div>

                  <button
                    type="button"
                    onClick={() => handleDelete(ext.id, ext.name)}
                    disabled={actionLoading}
                    className="text-gray-500 hover:text-red-400 p-1.5 rounded hover:bg-gray-800 transition"
                    title="Delete extension"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-gray-800 flex justify-end bg-gray-950/40">
          <button type="button" className="btn-secondary text-xs px-4" onClick={onClose}>
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
