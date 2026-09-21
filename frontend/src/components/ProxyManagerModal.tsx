import React, { useState, useEffect, useCallback } from "react";
import { X, Zap, Edit2, Plus, Trash2, CheckCircle2, AlertCircle, Loader2 } from "lucide-react";
import {
  api,
  Subscription,
  ProxyNode,
  ApiError,
} from "../lib/api";

interface ProxyManagerModalProps {
  isOpen: boolean;
  onClose: () => void;
  onNodesChanged?: () => void;
}

export function ProxyManagerModal({
  isOpen,
  onClose,
  onNodesChanged,
}: ProxyManagerModalProps) {
  // Tabs: "manual" or subscription.id
  const [activeTab, setActiveTab] = useState<string>("manual");
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [nodes, setNodes] = useState<ProxyNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [testingBatch, setTestingBatch] = useState(false);
  const [testingNodeId, setTestingNodeId] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  // Sub-modal states
  const [showNewSubModal, setShowNewSubModal] = useState(false);
  const [showEditSubModal, setShowEditSubModal] = useState(false);
  const [showBatchAddModal, setShowBatchAddModal] = useState(false);

  // New sub form
  const [newSubName, setNewSubName] = useState("");
  const [newSubUrl, setNewSubUrl] = useState("");
  const [newSubInterval, setNewSubInterval] = useState<number>(0);
  const [newSubCustomHours, setNewSubCustomHours] = useState<number>(12);
  const [newSubIsCustom, setNewSubIsCustom] = useState(false);

  // Edit sub form
  const [editSubName, setEditSubName] = useState("");
  const [editSubUrl, setEditSubUrl] = useState("");
  const [editSubInterval, setEditSubInterval] = useState<number>(0);
  const [editSubCustomHours, setEditSubCustomHours] = useState<number>(12);
  const [editSubIsCustom, setEditSubIsCustom] = useState(false);
  const [subActionLoading, setSubActionLoading] = useState(false);

  // Batch add form
  const [batchText, setBatchText] = useState("");
  const [batchLoading, setBatchLoading] = useState(false);

  // Notification checkbox & mode select
  const [notifyEnabled, setNotifyEnabled] = useState(false);
  const [proxyMode, setProxyMode] = useState("single");

  // Feedback notification
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const [subs, allNodes] = await Promise.all([
        api.getSubscriptions(),
        api.getProxyNodes(),
      ]);
      setSubscriptions(subs);
      setNodes(allNodes);
    } catch (err) {
      console.error("Failed to load proxies data:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      fetchData();
      setFeedback(null);
    }
  }, [isOpen, fetchData]);

  if (!isOpen) return null;

  // Active subscription object (if activeTab is a subscription id)
  const currentSub = subscriptions.find((s) => s.id === activeTab);

  // Filter nodes for the current tab
  const displayedNodes = nodes.filter((n) => {
    if (activeTab === "manual") {
      return !n.subscription_id;
    }
    return n.subscription_id === activeTab;
  });

  // Prepare edit subscription form
  const handleOpenEditSub = () => {
    if (!currentSub) return;
    setEditSubName(currentSub.name);
    setEditSubUrl(currentSub.url);
    const interval = currentSub.update_interval_hours;
    if (interval === 0 || interval === 24 || interval === 72) {
      setEditSubInterval(interval);
      setEditSubIsCustom(false);
    } else {
      setEditSubInterval(-1);
      setEditSubIsCustom(true);
      setEditSubCustomHours(interval);
    }
    setShowEditSubModal(true);
  };

  // Save new subscription
  const handleCreateSubscription = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newSubName.trim() || !newSubUrl.trim()) return;
    setSubActionLoading(true);
    setFeedback(null);
    try {
      const interval = newSubIsCustom ? newSubCustomHours : newSubInterval;
      const created = await api.createSubscription({
        name: newSubName.trim(),
        url: newSubUrl.trim(),
        update_interval_hours: interval,
      });
      setFeedback({ type: "success", text: `订阅 "${created.name}" 创建成功，已自动拉取节点！` });
      setShowNewSubModal(false);
      setNewSubName("");
      setNewSubUrl("");
      setNewSubInterval(0);
      setNewSubIsCustom(false);
      await fetchData();
      setActiveTab(created.id);
      onNodesChanged?.();
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "创建订阅失败";
      setFeedback({ type: "error", text: msg });
    } finally {
      setSubActionLoading(false);
    }
  };

  // Save edited subscription
  const handleUpdateSubscription = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!currentSub || !editSubName.trim() || !editSubUrl.trim()) return;
    setSubActionLoading(true);
    setFeedback(null);
    try {
      const interval = editSubIsCustom ? editSubCustomHours : editSubInterval;
      const updated = await api.updateSubscription(currentSub.id, {
        name: editSubName.trim(),
        url: editSubUrl.trim(),
        update_interval_hours: interval,
      });
      setFeedback({ type: "success", text: `订阅 "${updated.name}" 已更新！` });
      setShowEditSubModal(false);
      await fetchData();
      onNodesChanged?.();
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "更新订阅失败";
      setFeedback({ type: "error", text: msg });
    } finally {
      setSubActionLoading(false);
    }
  };

  // Refresh current subscription now
  const handleRefreshSubscription = async () => {
    if (!currentSub) return;
    setSubActionLoading(true);
    setFeedback(null);
    try {
      await api.refreshSubscription(currentSub.id);
      setFeedback({ type: "success", text: `订阅 "${currentSub.name}" 节点已同步最新内容！` });
      setShowEditSubModal(false);
      await fetchData();
      onNodesChanged?.();
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "同步订阅失败";
      setFeedback({ type: "error", text: msg });
    } finally {
      setSubActionLoading(false);
    }
  };

  // Delete subscription
  const handleDeleteSubscription = async () => {
    if (!currentSub) return;
    if (!confirm(`确定要删除订阅 "${currentSub.name}" 及其所有节点吗？`)) return;
    setSubActionLoading(true);
    setFeedback(null);
    try {
      await api.deleteSubscription(currentSub.id);
      setFeedback({ type: "success", text: `订阅 "${currentSub.name}" 已删除。` });
      setShowEditSubModal(false);
      setActiveTab("manual");
      await fetchData();
      onNodesChanged?.();
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "删除订阅失败";
      setFeedback({ type: "error", text: msg });
    } finally {
      setSubActionLoading(false);
    }
  };

  // Batch add nodes
  const handleBatchAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!batchText.trim()) return;
    setBatchLoading(true);
    setFeedback(null);
    try {
      const subId = activeTab === "manual" ? undefined : activeTab;
      const added = await api.batchAddProxyNodes(batchText.trim(), subId);
      setFeedback({ type: "success", text: `成功导入 ${added.length} 个节点！` });
      setShowBatchAddModal(false);
      setBatchText("");
      await fetchData();
      onNodesChanged?.();
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "批量添加节点失败";
      setFeedback({ type: "error", text: msg });
    } finally {
      setBatchLoading(false);
    }
  };

  // Delete single node
  const handleDeleteNode = async (nodeId: string, nodeName: string) => {
    if (!confirm(`确定删除节点 "${nodeName}" 吗？`)) return;
    try {
      await api.deleteProxyNode(nodeId);
      setNodes((prev) => prev.filter((n) => n.id !== nodeId));
      onNodesChanged?.();
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "删除节点失败";
      setFeedback({ type: "error", text: msg });
    }
  };

  // Test single node
  const handleTestNode = async (nodeId: string) => {
    setTestingNodeId(nodeId);
    try {
      const res = await api.testProxyNode(nodeId);
      setNodes((prev) =>
        prev.map((n) =>
          n.id === nodeId
            ? {
                ...n,
                last_latency_ms: res.latency_ms,
                last_tested_at: new Date().toISOString(),
              }
            : n
        )
      );
    } catch (err) {
      setNodes((prev) =>
        prev.map((n) =>
          n.id === nodeId
            ? { ...n, last_latency_ms: -1, last_tested_at: new Date().toISOString() }
            : n
        )
      );
    } finally {
      setTestingNodeId(null);
    }
  };

  // Batch test nodes in current tab
  const handleBatchTest = async () => {
    if (displayedNodes.length === 0) return;
    setTestingBatch(true);
    try {
      const nodeIds = displayedNodes.map((n) => n.id);
      const results = await api.batchTestProxyNodes({ node_ids: nodeIds });
      const resultMap = new Map(results.map((r) => [r.node_id, r.latency_ms]));
      setNodes((prev) =>
        prev.map((n) => {
          if (resultMap.has(n.id)) {
            return {
              ...n,
              last_latency_ms: resultMap.get(n.id) ?? null,
              last_tested_at: new Date().toISOString(),
            };
          }
          return n;
        })
      );
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "一键测速失败";
      setFeedback({ type: "error", text: msg });
    } finally {
      setTestingBatch(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
      {/* Main Modal Container */}
      <div className="bg-[#121624] border border-cyan-500/40 rounded-2xl w-full max-w-4xl shadow-[0_0_50px_-12px_rgba(6,182,212,0.25)] flex flex-col max-h-[90vh] overflow-hidden">
        
        {/* Header (Matching Image 0) */}
        <div className="px-6 py-4 flex items-center justify-between border-b border-gray-800/80">
          <h2 className="text-lg font-bold text-cyan-400 tracking-wide">管理代理链</h2>
          <button
            onClick={onClose}
            className="text-cyan-400/80 hover:text-cyan-300 p-1.5 rounded-lg hover:bg-cyan-500/10 transition"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Feedback Alert */}
        {feedback && (
          <div
            className={`mx-6 mt-3 p-3 rounded-lg text-xs flex items-center gap-2 ${
              feedback.type === "success"
                ? "bg-emerald-950/50 text-emerald-300 border border-emerald-800/60"
                : "bg-red-950/50 text-red-300 border border-red-800/60"
            }`}
          >
            {feedback.type === "success" ? (
              <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
            ) : (
              <AlertCircle className="h-4 w-4 shrink-0 text-red-400" />
            )}
            <span className="flex-1">{feedback.text}</span>
            <button
              onClick={() => setFeedback(null)}
              className="text-gray-400 hover:text-white"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )}

        {/* Sub-header Controls (Mode & Notification) */}
        <div className="px-6 pt-3 pb-2 flex items-center justify-between">
          <div className="w-48">
            <select
              value={proxyMode}
              onChange={(e) => setProxyMode(e.target.value)}
              className="bg-[#191f33] border border-gray-700/80 text-gray-200 text-xs rounded-lg px-3 py-1.5 w-full focus:outline-none focus:border-cyan-500"
            >
              <option value="single">单节点模式</option>
            </select>
          </div>
          <label className="flex items-center gap-2 text-xs text-gray-300 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={notifyEnabled}
              onChange={(e) => setNotifyEnabled(e.target.checked)}
              className="rounded bg-[#191f33] border-gray-700 text-cyan-500 focus:ring-0 focus:ring-offset-0"
            />
            <span>通知</span>
          </label>
        </div>

        {/* Tabs Bar */}
        <div className="px-6 border-b border-gray-800/80 flex items-center gap-1 overflow-x-auto">
          {/* Manual Tab */}
          <button
            onClick={() => setActiveTab("manual")}
            className={`px-4 py-2 text-sm font-medium transition whitespace-nowrap border-b-2 ${
              activeTab === "manual"
                ? "border-cyan-400 text-cyan-400 bg-[#162035]/80"
                : "border-transparent text-gray-400 hover:text-gray-200 hover:bg-gray-800/40"
            }`}
          >
            手动添加
          </button>

          {/* Subscriptions Tabs */}
          {subscriptions.map((sub) => (
            <button
              key={sub.id}
              onClick={() => setActiveTab(sub.id)}
              className={`px-4 py-2 text-sm font-medium transition whitespace-nowrap border-b-2 ${
                activeTab === sub.id
                  ? "border-cyan-400 text-cyan-400 bg-[#162035]/80"
                  : "border-transparent text-gray-400 hover:text-gray-200 hover:bg-gray-800/40"
              }`}
            >
              {sub.name}
            </button>
          ))}
        </div>

        {/* Action Bar (Tab Title & Action Buttons) */}
        <div className="px-6 py-3 flex items-center justify-between gap-4 flex-wrap">
          <div className="text-cyan-400 font-semibold text-base">
            {activeTab === "manual"
              ? `手动添加 (${displayedNodes.length})`
              : `${currentSub?.name ?? "订阅"} (${displayedNodes.length})`}
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            {/* ⚡ 一键测速 */}
            <button
              onClick={handleBatchTest}
              disabled={testingBatch || displayedNodes.length === 0}
              className="bg-[#1b233a] hover:bg-[#232f4e] text-amber-300 border border-amber-500/30 px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {testingBatch ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-300" />
              ) : (
                <Zap className="h-3.5 w-3.5" />
              )}
              <span>一键测速</span>
            </button>

            {/* ✏️ 编辑订阅 (Only for subscription tabs) */}
            {activeTab !== "manual" && (
              <button
                onClick={handleOpenEditSub}
                className="bg-[#1b2135] hover:bg-[#242b45] text-gray-300 border border-gray-700/80 px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition"
              >
                <Edit2 className="h-3.5 w-3.5" />
                <span>编辑订阅</span>
              </button>
            )}

            {/* + 新建订阅 */}
            <button
              onClick={() => setShowNewSubModal(true)}
              className="bg-[#1b2135] hover:bg-[#242b45] text-gray-300 border border-gray-700/80 px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition"
            >
              <Plus className="h-3.5 w-3.5" />
              <span>新建订阅</span>
            </button>

            {/* + 批量添加节点 */}
            <button
              onClick={() => setShowBatchAddModal(true)}
              className="bg-[#1b2135] hover:bg-[#242b45] text-gray-300 border border-gray-700/80 px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition"
            >
              <Plus className="h-3.5 w-3.5" />
              <span>批量添加节点</span>
            </button>
          </div>
        </div>

        {/* Node List Container */}
        <div className="flex-1 overflow-y-auto px-6 pb-6">
          <div className="border border-gray-800/90 rounded-xl bg-[#131726]/60 overflow-hidden min-h-[200px]">
            {loading ? (
              <div className="flex items-center justify-center py-16 text-gray-500 text-xs">
                <Loader2 className="h-5 w-5 animate-spin mr-2 text-cyan-400" />
                正在加载节点...
              </div>
            ) : displayedNodes.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 text-gray-500 text-xs gap-2">
                <p>暂无节点</p>
                <button
                  onClick={() => setShowBatchAddModal(true)}
                  className="text-cyan-400 hover:text-cyan-300 underline text-xs mt-1"
                >
                  点击 "+ 批量添加节点" 添加
                </button>
              </div>
            ) : (
              displayedNodes.map((node) => {
                const isTestingThis = testingNodeId === node.id;
                const isSelected = selectedNodeId === node.id;
                return (
                  <div
                    key={node.id}
                    className={`flex items-center justify-between px-4 py-3 border-b border-gray-800/60 last:border-b-0 hover:bg-[#181e33] transition ${
                      isSelected ? "bg-[#182138]/60" : ""
                    }`}
                  >
                    {/* Left: Radio + Protocol Badge + Node Name */}
                    <div className="flex items-center gap-3 min-w-0 flex-1 mr-4">
                      <input
                        type="radio"
                        name="active_proxy_node"
                        checked={isSelected}
                        onChange={() => setSelectedNodeId(node.id)}
                        className="text-cyan-500 focus:ring-0 focus:ring-offset-0 bg-[#191f33] border-gray-700 cursor-pointer"
                      />
                      <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-gray-800/90 text-gray-300 border border-gray-700/80 shrink-0">
                        {node.protocol}
                      </span>
                      <span className="text-sm font-medium text-gray-200 truncate font-mono">
                        {node.name}
                      </span>
                    </div>

                    {/* Right: Latency + Test Button + Delete Button */}
                    <div className="flex items-center gap-3 shrink-0">
                      {/* Latency display */}
                      <div className="w-20 text-right">
                        {isTestingThis ? (
                          <div className="flex items-center justify-end gap-1">
                            <Loader2 className="h-3 w-3 animate-spin text-cyan-400" />
                            <span className="text-xs text-cyan-400 font-mono">测速中</span>
                          </div>
                        ) : node.last_latency_ms === -1 ? (
                          <span className="text-xs font-semibold font-mono text-red-500">
                            Fail
                          </span>
                        ) : node.last_latency_ms != null ? (
                          <span
                            className={`text-xs font-mono font-medium ${
                              node.last_latency_ms < 300
                                ? "text-emerald-400"
                                : node.last_latency_ms < 800
                                ? "text-yellow-400"
                                : "text-orange-400"
                            }`}
                          >
                            {node.last_latency_ms}ms
                          </span>
                        ) : (
                          <span className="text-xs text-gray-600 font-mono">-</span>
                        )}
                      </div>

                      {/* Test single node */}
                      <button
                        onClick={() => handleTestNode(node.id)}
                        disabled={isTestingThis || testingBatch}
                        className="px-3 py-1 text-xs rounded bg-[#1c2236] text-gray-300 hover:text-white border border-gray-700/80 transition disabled:opacity-50"
                      >
                        测试
                      </button>

                      {/* Delete node */}
                      <button
                        onClick={() => handleDeleteNode(node.id, node.name)}
                        className="p-1 text-red-400/80 hover:text-red-300 hover:bg-red-500/10 rounded border border-gray-800/80 transition"
                        title="删除节点"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>

      {/* Sub-modal 1: New Subscription Modal (Image 2/3) */}
      {showNewSubModal && (
        <div className="fixed inset-0 z-60 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="bg-[#121624] border border-cyan-400/80 rounded-2xl w-full max-w-lg shadow-[0_0_40px_-10px_rgba(6,182,212,0.3)] p-6 flex flex-col gap-4">
            <div className="flex items-center justify-between border-b border-gray-800/80 pb-3">
              <h3 className="text-base font-bold text-cyan-400">新建订阅</h3>
              <button
                onClick={() => setShowNewSubModal(false)}
                className="text-cyan-400/80 hover:text-cyan-300 p-1 rounded-lg hover:bg-cyan-500/10 transition"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <form onSubmit={handleCreateSubscription} className="space-y-4">
              <div>
                <label className="block text-xs text-gray-300 mb-1.5">名称</label>
                <input
                  type="text"
                  required
                  placeholder="例如: rabisu"
                  value={newSubName}
                  onChange={(e) => setNewSubName(e.target.value)}
                  className="w-full bg-[#191f33] border border-gray-700/80 text-gray-200 text-xs rounded-lg px-3 py-2 focus:outline-none focus:border-cyan-500"
                />
              </div>

              <div>
                <label className="block text-xs text-gray-300 mb-1.5">订阅链接</label>
                <input
                  type="url"
                  required
                  placeholder="https://..."
                  value={newSubUrl}
                  onChange={(e) => setNewSubUrl(e.target.value)}
                  className="w-full bg-[#191f33] border border-gray-700/80 text-gray-200 text-xs rounded-lg px-3 py-2 focus:outline-none focus:border-cyan-500"
                />
              </div>

              <div>
                <label className="block text-xs text-gray-300 mb-1.5">定时更新</label>
                <select
                  value={newSubIsCustom ? -1 : newSubInterval}
                  onChange={(e) => {
                    const val = Number(e.target.value);
                    if (val === -1) {
                      setNewSubIsCustom(true);
                    } else {
                      setNewSubIsCustom(false);
                      setNewSubInterval(val);
                    }
                  }}
                  className="w-full bg-[#191f33] border border-gray-700/80 text-gray-200 text-xs rounded-lg px-3 py-2 focus:outline-none focus:border-cyan-500"
                >
                  <option value={0}>关闭</option>
                  <option value={24}>每 24 小时</option>
                  <option value={72}>每 72 小时</option>
                  <option value={-1}>自定义 (小时)</option>
                </select>

                {newSubIsCustom && (
                  <div className="mt-2 flex items-center gap-2">
                    <input
                      type="number"
                      min={1}
                      max={720}
                      value={newSubCustomHours}
                      onChange={(e) => setNewSubCustomHours(Math.max(1, Number(e.target.value)))}
                      className="w-28 bg-[#191f33] border border-gray-700/80 text-gray-200 text-xs rounded-lg px-3 py-1.5 focus:outline-none focus:border-cyan-500"
                    />
                    <span className="text-xs text-gray-400">小时更新一次</span>
                  </div>
                )}
              </div>

              <div className="flex justify-end gap-2 pt-3">
                <button
                  type="submit"
                  disabled={subActionLoading}
                  className="bg-[#1a2b42] text-cyan-400 border border-cyan-500/40 hover:bg-[#203654] px-5 py-2 rounded-lg text-xs font-semibold transition flex items-center gap-1.5 disabled:opacity-50"
                >
                  {subActionLoading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  <span>保存</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Sub-modal 2: Edit Subscription Modal (Image 1) */}
      {showEditSubModal && currentSub && (
        <div className="fixed inset-0 z-60 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="bg-[#121624] border border-cyan-400/80 rounded-2xl w-full max-w-lg shadow-[0_0_40px_-10px_rgba(6,182,212,0.3)] p-6 flex flex-col gap-4">
            <div className="flex items-center justify-between border-b border-gray-800/80 pb-3">
              <h3 className="text-base font-bold text-cyan-400">订阅设置</h3>
              <button
                onClick={() => setShowEditSubModal(false)}
                className="text-cyan-400/80 hover:text-cyan-300 p-1 rounded-lg hover:bg-cyan-500/10 transition"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <form onSubmit={handleUpdateSubscription} className="space-y-4">
              <div>
                <label className="block text-xs text-gray-300 mb-1.5">名称</label>
                <input
                  type="text"
                  required
                  value={editSubName}
                  onChange={(e) => setEditSubName(e.target.value)}
                  className="w-full bg-[#191f33] border border-gray-700/80 text-gray-200 text-xs rounded-lg px-3 py-2 focus:outline-none focus:border-cyan-500"
                />
              </div>

              <div>
                <label className="block text-xs text-gray-300 mb-1.5">订阅链接</label>
                <input
                  type="url"
                  required
                  value={editSubUrl}
                  onChange={(e) => setEditSubUrl(e.target.value)}
                  className="w-full bg-[#191f33] border border-gray-700/80 text-gray-200 text-xs rounded-lg px-3 py-2 focus:outline-none focus:border-cyan-500"
                />
              </div>

              <div>
                <label className="block text-xs text-gray-300 mb-1.5">定时更新</label>
                <select
                  value={editSubIsCustom ? -1 : editSubInterval}
                  onChange={(e) => {
                    const val = Number(e.target.value);
                    if (val === -1) {
                      setEditSubIsCustom(true);
                    } else {
                      setEditSubIsCustom(false);
                      setEditSubInterval(val);
                    }
                  }}
                  className="w-full bg-[#191f33] border border-gray-700/80 text-gray-200 text-xs rounded-lg px-3 py-2 focus:outline-none focus:border-cyan-500"
                >
                  <option value={0}>关闭</option>
                  <option value={24}>每 24 小时</option>
                  <option value={72}>每 72 小时</option>
                  <option value={-1}>自定义 (小时)</option>
                </select>

                {editSubIsCustom && (
                  <div className="mt-2 flex items-center gap-2">
                    <input
                      type="number"
                      min={1}
                      max={720}
                      value={editSubCustomHours}
                      onChange={(e) => setEditSubCustomHours(Math.max(1, Number(e.target.value)))}
                      className="w-28 bg-[#191f33] border border-gray-700/80 text-gray-200 text-xs rounded-lg px-3 py-1.5 focus:outline-none focus:border-cyan-500"
                    />
                    <span className="text-xs text-gray-400">小时更新一次</span>
                  </div>
                )}
              </div>

              <div className="flex items-center justify-between pt-3">
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={handleRefreshSubscription}
                    disabled={subActionLoading}
                    className="bg-[#1b233a] hover:bg-[#232f4e] text-cyan-400 border border-cyan-500/30 px-3 py-2 rounded-lg text-xs font-semibold transition flex items-center gap-1.5 disabled:opacity-50"
                  >
                    {subActionLoading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                    <span>立即更新</span>
                  </button>
                  <button
                    type="button"
                    onClick={handleDeleteSubscription}
                    disabled={subActionLoading}
                    className="bg-red-950/40 hover:bg-red-900/50 text-red-400 border border-red-800/50 px-3 py-2 rounded-lg text-xs font-semibold transition flex items-center gap-1.5 disabled:opacity-50"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    <span>删除订阅</span>
                  </button>
                </div>

                <button
                  type="submit"
                  disabled={subActionLoading}
                  className="bg-[#1a2b42] text-cyan-400 border border-cyan-500/40 hover:bg-[#203654] px-5 py-2 rounded-lg text-xs font-semibold transition flex items-center gap-1.5 disabled:opacity-50"
                >
                  {subActionLoading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  <span>保存</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Sub-modal 3: Batch Add Nodes Modal (Image 4) */}
      {showBatchAddModal && (
        <div className="fixed inset-0 z-60 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="bg-[#121624] border border-cyan-400/80 rounded-2xl w-full max-w-lg shadow-[0_0_40px_-10px_rgba(6,182,212,0.3)] p-6 flex flex-col gap-4">
            <div className="flex items-center justify-between border-b border-gray-800/80 pb-3">
              <h3 className="text-base font-bold text-cyan-400">批量添加节点</h3>
              <button
                onClick={() => setShowBatchAddModal(false)}
                className="text-cyan-400/80 hover:text-cyan-300 p-1 rounded-lg hover:bg-cyan-500/10 transition"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <p className="text-xs text-gray-400">
              Paste links here (one per line). Supports vmess, vless, trojan, ss, socks5, tuic.
            </p>

            <form onSubmit={handleBatchAdd} className="space-y-4">
              <textarea
                required
                rows={10}
                value={batchText}
                onChange={(e) => setBatchText(e.target.value)}
                placeholder={"vmess://...\nss://...\nvless://...\ntrojan://...\ntuic://..."}
                className="w-full bg-[#191f33] border border-gray-700/80 text-gray-200 font-mono text-xs rounded-lg p-3 focus:outline-none focus:border-cyan-500 resize-none"
              />

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="submit"
                  disabled={batchLoading}
                  className="bg-[#1a2b42] text-cyan-400 border border-cyan-500/40 hover:bg-[#203654] px-5 py-2 rounded-lg text-xs font-semibold transition flex items-center gap-1.5 disabled:opacity-50"
                >
                  {batchLoading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  <span>保存</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
