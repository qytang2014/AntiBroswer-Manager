import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { KernelManagerModal } from "./KernelManagerModal";
import { api } from "../lib/api";

vi.mock("../lib/api", () => {
  return {
    api: {
      listKernels: vi.fn(),
      getKernelDownloadStatus: vi.fn(),
      downloadKernelStream: vi.fn(),
      deleteKernel: vi.fn(),
    },
    ApiError: class ApiError extends Error {},
  };
});

describe("KernelManagerModal", () => {
  const mockKernelsResponse = {
    current_platform: "darwin-arm64",
    current_tier: "free",
    active_version: "145.0.7632.109.2",
    installed: true,
    kernels: [
      {
        version: "145.0.7632.109.2",
        tier: "free" as const,
        name: "Chromium 145.0.7632.109.2 (官方稳定版)",
        description: "官方预设稳定版内核",
        platform: "darwin-arm64",
        installed: true,
        is_active: true,
        binary_path: "/path/to/binary",
        size_mb: 150,
      },
    ],
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.listKernels).mockResolvedValue(mockKernelsResponse);
    vi.mocked(api.getKernelDownloadStatus).mockResolvedValue({
      active: false,
      task: null,
    });
  });

  it("renders kernel list correctly when open", async () => {
    render(<KernelManagerModal isOpen={true} onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText(/Chromium 145.0.7632.109.2/)).toBeTruthy();
      expect(screen.getAllByText(/已安装/).length).toBeGreaterThanOrEqual(1);
    });
  });

  it("handles completed background task once without infinite calls", async () => {
    vi.mocked(api.getKernelDownloadStatus).mockResolvedValue({
      active: false,
      task: {
        stage: "completed",
        version: "145.0.7632.109.2",
        message: "Completed",
        percent: 100,
      },
    });

    const onKernelChanged = vi.fn();
    const { rerender } = render(
      <KernelManagerModal
        isOpen={true}
        onClose={() => {}}
        onKernelChanged={onKernelChanged}
      />
    );

    await waitFor(() => {
      expect(screen.getByText(/已在后台安装完成/)).toBeTruthy();
      expect(onKernelChanged).toHaveBeenCalledTimes(1);
    });

    // Simulating parent re-render passing a new inline onClose callback
    rerender(
      <KernelManagerModal
        isOpen={true}
        onClose={() => {}}
        onKernelChanged={onKernelChanged}
      />
    );

    // Should NOT have triggered onKernelChanged again
    expect(onKernelChanged).toHaveBeenCalledTimes(1);
  });

  it("refreshes list when clicking refresh button", async () => {
    render(<KernelManagerModal isOpen={true} onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByTitle("刷新内核列表")).toBeTruthy();
    });

    const initialCalls = vi.mocked(api.listKernels).mock.calls.length;
    fireEvent.click(screen.getByTitle("刷新内核列表"));

    await waitFor(() => {
      expect(vi.mocked(api.listKernels).mock.calls.length).toBeGreaterThan(initialCalls);
    });
  });

  it("switches tabs, updates dynamic header, and shows open-source badge for Camoufox", async () => {
    vi.mocked(api.listKernels).mockResolvedValue({
      current_platform: "darwin-arm64",
      current_tier: "pro",
      active_version: "151.0.7922.108.3",
      installed: true,
      kernels: [
        {
          version: "151.0.7922.108.3",
          tier: "pro" as const,
          browser_type: "cloakbrowser",
          name: "Chromium 151.0 (Pro)",
          description: "CloakBrowser Pro 内核",
          platform: "darwin-arm64",
          installed: true,
          is_active: true,
          binary_path: "/path/to/chrome",
          size_mb: 180,
        },
        {
          version: "152.0.4-beta.31",
          tier: "free" as const,
          browser_type: "camoufox",
          name: "Camoufox 152.0.4-beta.31",
          description: "基于 Firefox 的指纹浏览器内核",
          platform: "darwin-arm64",
          installed: true,
          is_active: true,
          binary_path: "/path/to/camoufox",
          size_mb: 120,
        },
      ],
    });

    render(<KernelManagerModal isOpen={true} onClose={() => {}} />);

    // Default CloakBrowser tab
    await waitFor(() => {
      expect(screen.getByText(/内核管理 \/ Kernel Manager/)).toBeTruthy();
      expect(screen.getAllByText("pro").length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText(/已安装:/)).toBeTruthy();
      expect(screen.getByText(/个版本/)).toBeTruthy();
    });

    // Switch to Camoufox tab
    fireEvent.click(screen.getByRole("button", { name: "Camoufox (Firefox)" }));

    await waitFor(() => {
      expect(screen.getByText(/内核管理 \/ Kernel Manager/)).toBeTruthy();
      expect(screen.getByText("开源免授权")).toBeTruthy();
      expect(screen.getByText("Camoufox 152.0.4-beta.31")).toBeTruthy();
    });
  });
});
