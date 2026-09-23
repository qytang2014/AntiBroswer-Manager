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
      expect(screen.getByText(/当前使用/)).toBeTruthy();
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
});
