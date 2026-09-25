import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, type SystemStatus } from "../lib/api";
import { SettingsPanel } from "./SettingsPanel";

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    api: {
      ...actual.api,
      getSettings: vi.fn(),
      updateSettings: vi.fn(),
    },
  };
});

const mockSystemStatus: SystemStatus = {
  tier: "pro",
  license_tier: "pro",
  binary_version: "128.0.0",
  resolved_channel: "stable",
  resolved_source: "cdn",
  host_os: "macos",
  runtime_mode: "local",
  viewer_mode: "native",
  binary_path: "/opt/cloak",
  auto_download: true,
  concurrency_limit: 10,
  active_profiles_count: 1,
  windows_fonts_complete: true,
  auth_required: false,
};

describe("SettingsPanel Dual-Engine Tabs", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getSettings).mockResolvedValue({
      license_key_set: true,
      license_key_masked: "cb_ab...9898",
      release_channel: "stable",
      licenses: [
        {
          id: "lic-1",
          name: "Team Pro",
          key_masked: "cb_ab...9898",
          is_default: true,
        },
      ],
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders with CloakBrowser tab active by default and displays license info", async () => {
    render(
      <SettingsPanel
        onClose={vi.fn()}
        onSaved={vi.fn()}
        systemStatus={mockSystemStatus}
      />
    );

    await waitFor(() => {
      expect(screen.getByText("CloakBrowser 专有配置")).toBeTruthy();
      expect(screen.getByDisplayValue("Team Pro")).toBeTruthy();
      expect(screen.getByText("官方分发发布渠道 (Release Channel)")).toBeTruthy();
    });
  });

  it("switches to Camoufox tab and shows open source and no-license notice", async () => {
    const onOpenKernelManager = vi.fn();
    render(
      <SettingsPanel
        onClose={vi.fn()}
        onSaved={vi.fn()}
        onOpenKernelManager={onOpenKernelManager}
        systemStatus={mockSystemStatus}
      />
    );

    await waitFor(() => {
      expect(screen.getByText("Camoufox (Firefox)")).toBeTruthy();
    });

    fireEvent.click(screen.getByText("Camoufox (Firefox)"));

    expect(screen.getByText("Camoufox 内核说明")).toBeTruthy();
    expect(screen.getByText("开源内核 · 永久免费")).toBeTruthy();
    expect(
      screen.getByText(/Camoufox 遵循 GPL-3.0 协议开源发布/i)
    ).toBeTruthy();

    const kmBtn = screen.getByText("打开内核管理器");
    fireEvent.click(kmBtn);
    expect(onOpenKernelManager).toHaveBeenCalledTimes(1);
  });

  it("switches to General tab and shows runtime environment details", async () => {
    render(
      <SettingsPanel
        onClose={vi.fn()}
        onSaved={vi.fn()}
        systemStatus={mockSystemStatus}
      />
    );

    await waitFor(() => {
      expect(screen.getByText("通用信息 (General)")).toBeTruthy();
    });

    fireEvent.click(screen.getByText("通用信息 (General)"));

    expect(screen.getByText("系统环境与运行信息")).toBeTruthy();
    expect(screen.getByText("macos")).toBeTruthy();
    expect(screen.getByText(/CloakBrowser \(Chromium\) & Camoufox \(Firefox\)/)).toBeTruthy();
    expect(screen.getByText(/关于双内核防关联架构/)).toBeTruthy();
  });

  it("saves CloakBrowser settings when Save is clicked", async () => {
    const onSaved = vi.fn();
    const onClose = vi.fn();
    vi.mocked(api.updateSettings).mockResolvedValue(mockSystemStatus);

    render(
      <SettingsPanel
        onClose={onClose}
        onSaved={onSaved}
        systemStatus={mockSystemStatus}
      />
    );

    await waitFor(() => {
      expect(screen.getByDisplayValue("Team Pro")).toBeTruthy();
    });

    const saveBtn = screen.getByRole("button", { name: /保存设置/ });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(api.updateSettings).toHaveBeenCalledWith({
        release_channel: "stable",
        licenses: [
          {
            id: "lic-1",
            name: "Team Pro",
            key: "",
            is_default: true,
          },
        ],
      });
      expect(onSaved).toHaveBeenCalledWith(mockSystemStatus);
      expect(onClose).toHaveBeenCalled();
    });
  });

  it("adds and removes licenses in CloakBrowser tab", async () => {
    render(
      <SettingsPanel
        onClose={vi.fn()}
        onSaved={vi.fn()}
        systemStatus={mockSystemStatus}
      />
    );

    await waitFor(() => {
      expect(screen.getByDisplayValue("Team Pro")).toBeTruthy();
    });

    fireEvent.click(screen.getByText("添加授权"));
    expect(screen.getByDisplayValue("License 2")).toBeTruthy();

    const deleteButtons = screen.getAllByTitle("删除此授权");
    expect(deleteButtons.length).toBe(2);
    fireEvent.click(deleteButtons[1]);

    expect(screen.queryByDisplayValue("License 2")).toBeNull();
  });
});
