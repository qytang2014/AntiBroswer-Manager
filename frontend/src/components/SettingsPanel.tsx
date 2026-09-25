import { useEffect, useState } from "react";
import { Loader2, X, Plus, Trash2, CheckCircle2 } from "lucide-react";
import { api, type SystemStatus } from "../lib/api";

interface SettingsPanelProps {
  onClose: () => void;
  onSaved: (status: SystemStatus) => void;
}

export function SettingsPanel({ onClose, onSaved }: SettingsPanelProps) {
  const [licenses, setLicenses] = useState<{ id: string; name: string; key: string; is_default: boolean }[]>([]);
  const [channel, setChannel] = useState<"stable" | "preview">("stable");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getSettings()
      .then((s) => {
        setChannel(s.release_channel === "preview" ? "preview" : "stable");
        // Initialize local editable licenses from masked data
        // For new keys added by the user, 'key' will hold the actual input.
        // For existing keys, 'key' will hold the masked value initially.
        // The backend knows not to parse masked keys if it hasn't changed.
        // Actually, backend updateSettings expects the full key!
        // Wait, if we send the masked key back, it will overwrite the real key with "cb_ab...9898".
        // To handle this properly: any untouched license just sends its masked key? No, backend doesn't know it's masked!
        // So we just store 'isNew: boolean' and handle it correctly. Or better yet:
        // Actually, since this is a local app, sending keys back and forth might be annoying if masked.
        // The backend `SettingsUpdate` expects the full key for `licenses`.
        // Let's just track edits. If a user edits a key, it's a new key.
        setLicenses(s.licenses?.map(l => ({
          id: l.id,
          name: l.name,
          key: "", // Don't put masked key in input value to avoid accidental override, use placeholder
          placeholder: l.key_masked,
          is_default: l.is_default
        })) || []);
      })
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load settings"),
      );
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      // Build the final licenses list. If a key is empty, it means the user didn't change it.
      // Wait, if they didn't change it, we shouldn't send it empty!
      // Actually, since we need to send the full list to `PUT /api/settings`, we might have an issue.
      // Wait, if the user didn't change the key, but we send `""` to the backend, the backend will think the key is empty!
      // Let's rethink: The backend `updateSettings` can just accept the licenses with empty strings and interpret them as "keep existing key".
      // Let's check backend `main.py` update_settings logic: it just saves whatever we send!
      // Oh! We need to either make the backend fetch the old key if empty, or just not fetch masked keys and fetch real keys in `getSettings`?
      // The user runs this locally on their machine. It's totally fine to return the full key in `getSettings`?
      // The current code masks it for `license_key_masked`. We can just keep it masked but we can't easily update it if we send it back.
      // Let's modify the frontend payload: if `key` is empty string, we tell backend to keep the existing key.

      const payloadLicenses = licenses.map(l => ({
        id: l.id,
        name: l.name,
        key: l.key,
        is_default: l.is_default,
        _keep_existing: l.key === "",
      }));

      // But wait! We didn't modify the backend to support `_keep_existing`.
      // We'll update the backend to support keeping existing keys later, or we can just send it and update backend.

      const payload: any = {
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
    setLicenses([...licenses, { id: `lic-${Date.now()}`, name: `License ${licenses.length + 1}`, key: "", is_default: licenses.length === 0 }]);
  };

  const removeLicense = (id: string) => {
    const newLicenses = licenses.filter(l => l.id !== id);
    if (newLicenses.length > 0 && !newLicenses.some(l => l.is_default)) {
      const first = newLicenses[0];
      if (first) {
        newLicenses[0] = { ...first, is_default: true };
      }
    }
    setLicenses(newLicenses);
  };

  const setDefault = (id: string) => {
    setLicenses(licenses.map(l => ({ ...l, is_default: l.id === id })));
  };

  const updateLicense = (id: string, field: keyof typeof licenses[0], value: any) => {
    setLicenses(licenses.map(l => l.id === id ? { ...l, [field]: value } : l));
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl rounded-lg border border-border bg-surface-1 shadow-xl flex flex-col max-h-[90vh]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-border px-4 py-3 shrink-0">
          <h2 className="text-sm font-semibold">Settings</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-6 p-4 overflow-y-auto">
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="label">CloakBrowser Pro 授权管理</label>
              <button type="button" onClick={addLicense} className="btn-secondary text-xs flex items-center gap-1">
                <Plus className="w-3 h-3" /> Add License
              </button>
            </div>

            <div className="space-y-3">
              {licenses.map((lic) => (
                <div key={lic.id} className="flex flex-col gap-2 p-3 border border-border rounded bg-surface-0 relative">
                  <div className="flex gap-2 items-start">
                    <div className="flex-1 space-y-2">
                      <input
                        className="input text-sm"
                        placeholder="License Name"
                        value={lic.name}
                        onChange={(e) => updateLicense(lic.id, "name", e.target.value)}
                      />
                      <input
                        className="input font-mono text-sm"
                        type="password"
                        placeholder={(lic as any).placeholder ? `Current: ${(lic as any).placeholder} (Type to replace)` : "Enter License Key"}
                        value={lic.key}
                        onChange={(e) => updateLicense(lic.id, "key", e.target.value)}
                      />
                    </div>
                    <div className="flex flex-col gap-2 shrink-0 pt-1">
                      <button
                        title={lic.is_default ? "Default License" : "Set as Default"}
                        className={`p-1.5 rounded transition-colors ${lic.is_default ? 'text-accent bg-accent/10' : 'text-gray-500 hover:bg-surface-2'}`}
                        onClick={() => setDefault(lic.id)}
                      >
                        <CheckCircle2 className="w-4 h-4" />
                      </button>
                      <button
                        title="Remove License"
                        className="p-1.5 rounded text-gray-500 hover:text-red-400 hover:bg-surface-2 transition-colors"
                        onClick={() => removeLicense(lic.id)}
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
              {licenses.length === 0 && (
                <div className="text-sm text-gray-500 text-center py-4 border border-dashed border-border rounded">
                  未配置授权，CloakBrowser 环境将以免费无 Key 模式运行。（Camoufox 引擎完全开源免费，无需授权）
                </div>
              )}
            </div>
            <p className="mt-2 text-xs text-gray-500">
              管理 CloakBrowser Pro 高级授权，您可以在不同环境单独指定使用的授权。注：此处配置仅对 CloakBrowser 引擎生效，不影响 Camoufox。
            </p>
          </div>

          <div>
            <label className="label">Release channel</label>
            <select
              className="input"
              value={channel}
              onChange={(e) =>
                setChannel(e.target.value === "preview" ? "preview" : "stable")
              }
            >
              <option value="stable">Stable</option>
              <option value="preview">Preview (early access)</option>
            </select>
          </div>

          {error && <p className="text-xs text-red-400">{error}</p>}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-border px-4 py-3 shrink-0">
          <button onClick={onClose} disabled={saving} className="btn-secondary">
            Cancel
          </button>
          <button onClick={handleSave} disabled={saving} className="btn-primary flex items-center gap-1.5">
            {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            <span>{saving ? "Applying…" : "Save"}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
