import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../lib/api";
import type { Profile } from "../lib/api";
import { ProfileForm } from "./ProfileForm";

function profile(status: Profile["status"]): Profile {
  return {
    id: "p1",
    name: "Work",
    fingerprint_seed: 1,
    proxy: null,
    timezone: null,
    locale: null,
    screen_width: 1920,
    screen_height: 1080,
    gpu_family: "auto",
    humanize: false,
    human_preset: "default",
    geoip: true,
    clipboard_sync: true,
    auto_launch: false,
    color_scheme: null,
    launch_args: [],
    extension_paths: [],
    allow_3p_cookies: true,
    set_google_default: true,
    capture_preview: true,
    restore_session: true,
    notes: null,
    tags: [],
    user_data_dir: "/data/profiles/p1",
    created_at: "",
    updated_at: "",
    status,
  } as unknown as Profile;
}

function renderForm(status: Profile["status"]) {
  const onDuplicate = vi.fn().mockResolvedValue(undefined);
  render(
    <ProfileForm
      profile={profile(status)}
      hostOs="linux"
      viewerMode="vnc"
      onSave={vi.fn()}
      onDuplicate={onDuplicate}
      onCancel={vi.fn()}
    />,
  );
  return onDuplicate;
}

describe("ProfileForm duplicate split button", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("Escape closes the menu and returns focus to the trigger", () => {
    renderForm("stopped");
    const trigger = screen.getByLabelText("Duplicate options");
    fireEvent.click(trigger);
    const item = screen.getByRole("menuitem", { name: /Settings and fingerprint only/ });
    item.focus();
    expect(document.activeElement).toBe(item);

    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("closes on an outside click", () => {
    renderForm("stopped");
    fireEvent.click(screen.getByLabelText("Duplicate options"));
    expect(screen.getByRole("menu")).toBeTruthy();
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("offers browser state only for a stopped profile", () => {
    renderForm("running");
    fireEvent.click(screen.getByLabelText("Duplicate options"));
    const item = screen.getByRole("menuitem", { name: /With browser state/ }) as HTMLButtonElement;
    expect(item.disabled).toBe(true);
    expect(screen.getByText("Stop the profile first")).toBeTruthy();
  });

  it("the button itself is a config-only copy; the menu item asks for state", async () => {
    vi.stubGlobal("confirm", vi.fn(() => true));
    const onDuplicate = renderForm("stopped");
    const trigger = screen.getByLabelText("Duplicate options") as HTMLButtonElement;

    fireEvent.click(screen.getByTitle("Duplicate settings and fingerprint only"));
    expect(onDuplicate).toHaveBeenLastCalledWith(false);
    // Both halves are disabled while a duplicate is in flight
    await waitFor(() => expect(trigger.disabled).toBe(false));

    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("menuitem", { name: /With browser state/ }));
    expect(onDuplicate).toHaveBeenLastCalledWith(true);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("renders default Direct option and action to open proxy manager", () => {
    renderForm("stopped");
    const trigger = screen.getByRole("button", { name: /Proxy node/i });
    expect(trigger).toBeTruthy();
    expect(trigger.textContent).toContain("直连 / Direct");

    // Click to open custom dropdown
    fireEvent.click(trigger);
    expect(screen.getAllByText(/纯直连 \/ Direct/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/添加节点 \/ 打开代理管理/)).toBeTruthy();
  });
});

describe("ProfileForm kernel version selection and validation", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders installed kernel options and triggers onOpenKernelManager", async () => {
    vi.spyOn(api, "getSubscriptions").mockResolvedValue([]);
    vi.spyOn(api, "getProxyNodes").mockResolvedValue([]);
    vi.spyOn(api, "listExtensions").mockResolvedValue([]);
    vi.spyOn(api, "listKernels").mockResolvedValue({
      current_platform: "mac",
      current_tier: "free",
      installed: true,
      kernels: [
        {
          version: "145.0.7632.109.2",
          name: "Chromium 145 (官方稳定版)",
          tier: "free",
          platform: "mac-arm64",
          description: "Official stable",
          installed: true,
        },
      ],
    });

    const onOpenKernelManager = vi.fn();
    render(
      <ProfileForm
        profile={profile("stopped")}
        hostOs="linux"
        viewerMode="vnc"
        onSave={vi.fn()}
        onCancel={vi.fn()}
        onOpenKernelManager={onOpenKernelManager}
      />,
    );

    const btn = screen.getByRole("button", { name: /管理\/下载更多内核/ });
    expect(btn).toBeTruthy();
    fireEvent.click(btn);
    expect(onOpenKernelManager).toHaveBeenCalled();

    await waitFor(() => {
      expect(screen.getByText(/Chromium 145 \(官方稳定版\)/)).toBeTruthy();
    });
  });

  it("shows warning when selected kernel is not installed / deleted", async () => {
    vi.spyOn(api, "getSubscriptions").mockResolvedValue([]);
    vi.spyOn(api, "getProxyNodes").mockResolvedValue([]);
    vi.spyOn(api, "listExtensions").mockResolvedValue([]);
    vi.spyOn(api, "listKernels").mockResolvedValue({
      current_platform: "mac",
      current_tier: "free",
      installed: true,
      kernels: [
        {
          version: "151.0.7895.120",
          name: "Chromium 151 (尝鲜测试版)",
          tier: "pro",
          platform: "mac-arm64",
          description: "Pro test",
          installed: true,
        },
      ],
    });

    const deletedKernelProfile = {
      ...profile("stopped"),
      browser_version: "145.0.7632.109.2",
    };

    render(
      <ProfileForm
        profile={deletedKernelProfile}
        hostOs="linux"
        viewerMode="vnc"
        onSave={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(
        screen.getByText(/该环境绑定的内核版本 \(v145.0.7632.109.2\) 本地已被删除或不存在/),
      ).toBeTruthy();
    });
  });

  it("warns about inline proxy auth argument on older kernel", async () => {
    vi.spyOn(api, "getSubscriptions").mockResolvedValue([]);
    vi.spyOn(api, "getProxyNodes").mockResolvedValue([]);
    vi.spyOn(api, "listExtensions").mockResolvedValue([]);
    vi.spyOn(api, "listKernels").mockResolvedValue({
      current_platform: "mac",
      current_tier: "free",
      installed: true,
      kernels: [],
    });

    const oldKernelProfile = {
      ...profile("stopped"),
      browser_version: "145.0.7632.109.2",
      launch_args: ["--proxy-server=http://user:pass@127.0.0.1:8080"],
    };

    render(
      <ProfileForm
        profile={oldKernelProfile}
        hostOs="linux"
        viewerMode="vnc"
        onSave={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText(/当前选中的内核版本 \(v145.0.7632.109.2\) 原生不支持命令行内联代理凭证/)).toBeTruthy();
    expect(screen.getByText(/检测到包含账号密码的内联代理参数/)).toBeTruthy();
  });

  it("filters kernel versions by browser_type and auto-selects latest installed version on switch", async () => {
    vi.spyOn(api, "getSubscriptions").mockResolvedValue([]);
    vi.spyOn(api, "getProxyNodes").mockResolvedValue([]);
    vi.spyOn(api, "listExtensions").mockResolvedValue([]);
    vi.spyOn(api, "listKernels").mockResolvedValue({
      current_platform: "mac",
      current_tier: "free",
      installed: true,
      kernels: [
        {
          version: "151.0.7895.120",
          browser_type: "cloakbrowser",
          name: "Chromium 151 (Pro)",
          tier: "pro",
          platform: "mac-arm64",
          description: "Chromium Pro",
          installed: true,
        },
        {
          version: "152.0.4-beta.31",
          browser_type: "camoufox",
          name: "Camoufox 152",
          tier: "free",
          platform: "mac-arm64",
          description: "Firefox stealth",
          installed: true,
        },
      ],
    });

    render(
      <ProfileForm
        profile={profile("stopped")}
        hostOs="linux"
        viewerMode="vnc"
        onSave={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    // Initial CloakBrowser type: only Chromium kernel option shown
    await waitFor(() => {
      expect(screen.getByText(/Chromium 151 \(Pro\)/)).toBeTruthy();
      expect(screen.queryByText(/Camoufox 152/)).toBeNull();
    });

    // Switch to Camoufox
    const typeSelect = screen.getByLabelText(/内核类型/);
    fireEvent.change(typeSelect, { target: { value: "camoufox" } });

    // After switch: only Camoufox kernel option shown, and version auto-selected
    await waitFor(() => {
      expect(screen.getAllByText(/Camoufox 152/).length).toBeGreaterThan(0);
      expect(screen.queryByText(/Chromium 151 \(Pro\)/)).toBeNull();
      const versionSelect = screen.getByLabelText(/内核版本/) as HTMLSelectElement;
      expect(versionSelect.value).toBe("152.0.4-beta.31");
    });
  });

  it("clears version and shows warning when switching to browser_type without installed kernels", async () => {
    vi.spyOn(api, "getSubscriptions").mockResolvedValue([]);
    vi.spyOn(api, "getProxyNodes").mockResolvedValue([]);
    vi.spyOn(api, "listExtensions").mockResolvedValue([]);
    vi.spyOn(api, "listKernels").mockResolvedValue({
      current_platform: "mac",
      current_tier: "free",
      installed: true,
      kernels: [
        {
          version: "151.0.7895.120",
          browser_type: "cloakbrowser",
          name: "Chromium 151 (Pro)",
          tier: "pro",
          platform: "mac-arm64",
          description: "Chromium Pro",
          installed: true,
        },
      ],
    });

    render(
      <ProfileForm
        profile={profile("stopped")}
        hostOs="linux"
        viewerMode="vnc"
        onSave={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText(/Chromium 151 \(Pro\)/)).toBeTruthy();
    });

    // Switch to Camoufox (which has 0 installed kernels)
    const typeSelect = screen.getByLabelText(/内核类型/);
    fireEvent.change(typeSelect, { target: { value: "camoufox" } });

    await waitFor(() => {
      expect(screen.getByText(/未检测到已安装的 Camoufox \(Firefox\) 内核/)).toBeTruthy();
      const versionSelect = screen.getByLabelText(/内核版本/) as HTMLSelectElement;
      expect(versionSelect.value).toBe("");
    });
  });

  it("defaults to highest version even when older versions appear first in list", async () => {
    vi.spyOn(api, "getSubscriptions").mockResolvedValue([]);
    vi.spyOn(api, "getProxyNodes").mockResolvedValue([]);
    vi.spyOn(api, "listExtensions").mockResolvedValue([]);
    vi.spyOn(api, "getSettings").mockResolvedValue({ licenses: [] } as any);
    vi.spyOn(api, "listKernels").mockResolvedValue({
      current_platform: "mac",
      current_tier: "free",
      installed: true,
      kernels: [
        {
          version: "145.0.7632.109.2",
          browser_type: "cloakbrowser",
          name: "Chromium 145 (Free)",
          tier: "free",
          platform: "mac-arm64",
          description: "Chromium Free",
          installed: true,
        },
        {
          version: "151.0.7922.108.3",
          browser_type: "cloakbrowser",
          name: "Chromium 151 (Pro)",
          tier: "pro",
          platform: "mac-arm64",
          description: "Chromium Pro",
          installed: true,
        },
      ],
    });

    render(
      <ProfileForm
        profile={profile("stopped")}
        hostOs="linux"
        viewerMode="vnc"
        onSave={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    await waitFor(() => {
      const versionSelect = screen.getByLabelText(/内核版本/) as HTMLSelectElement;
      expect(versionSelect.value).toBe("151.0.7922.108.3");
    });
  });

  it("automatically updates to highest remaining version when selected version is deleted", async () => {
    vi.spyOn(api, "getSubscriptions").mockResolvedValue([]);
    vi.spyOn(api, "getProxyNodes").mockResolvedValue([]);
    vi.spyOn(api, "listExtensions").mockResolvedValue([]);
    vi.spyOn(api, "getSettings").mockResolvedValue({ licenses: [] } as any);

    // Initially both 151 and 145 are installed
    const listKernelsMock = vi.spyOn(api, "listKernels").mockResolvedValue({
      current_platform: "mac",
      current_tier: "free",
      installed: true,
      kernels: [
        {
          version: "151.0.7922.108.3",
          browser_type: "cloakbrowser",
          name: "Chromium 151 (Pro)",
          tier: "pro",
          platform: "mac-arm64",
          description: "Chromium Pro",
          installed: true,
        },
        {
          version: "145.0.7632.109.2",
          browser_type: "cloakbrowser",
          name: "Chromium 145 (Free)",
          tier: "free",
          platform: "mac-arm64",
          description: "Chromium Free",
          installed: true,
        },
      ],
    });

    const { rerender } = render(
      <ProfileForm
        profile={profile("stopped")}
        hostOs="linux"
        viewerMode="vnc"
        onSave={vi.fn()}
        onCancel={vi.fn()}
        kernelsUpdated={0}
      />,
    );

    await waitFor(() => {
      const versionSelect = screen.getByLabelText(/内核版本/) as HTMLSelectElement;
      expect(versionSelect.value).toBe("151.0.7922.108.3");
    });

    // Now simulate deleting 151 from disk: listKernels returns only 145
    listKernelsMock.mockResolvedValue({
      current_platform: "mac",
      current_tier: "free",
      installed: true,
      kernels: [
        {
          version: "145.0.7632.109.2",
          browser_type: "cloakbrowser",
          name: "Chromium 145 (Free)",
          tier: "free",
          platform: "mac-arm64",
          description: "Chromium Free",
          installed: true,
        },
      ],
    });

    // Rerender with kernelsUpdated incremented (simulating modal close)
    rerender(
      <ProfileForm
        profile={profile("stopped")}
        hostOs="linux"
        viewerMode="vnc"
        onSave={vi.fn()}
        onCancel={vi.fn()}
        kernelsUpdated={1}
      />,
    );

    await waitFor(() => {
      const versionSelect = screen.getByLabelText(/内核版本/) as HTMLSelectElement;
      expect(versionSelect.value).toBe("145.0.7632.109.2");
    });
  });

  describe("Dual-engine presets and hardware fingerprints", () => {
    it("renders dual-engine presets and hardware fingerprint controls without --disable-gpu", async () => {
      vi.spyOn(api, "getSettings").mockResolvedValue({
        license_key_set: false,
        license_key_masked: null,
        release_channel: "stable",
        licenses: [],
      });
      vi.spyOn(api, "listKernels").mockResolvedValue({
        current_platform: "mac",
        current_tier: "free",
        installed: true,
        kernels: [
          {
            version: "151.0.7922.108.3",
            browser_type: "cloakbrowser",
            name: "Chromium 151",
            tier: "pro",
            platform: "mac-arm64",
            description: "Chromium Pro",
            installed: true,
          },
          {
            version: "v152.0.4-beta.31",
            browser_type: "camoufox",
            name: "Camoufox v152",
            tier: "free",
            platform: "mac-arm64",
            description: "Camoufox Firefox",
            installed: true,
          },
        ],
      });
      vi.spyOn(api, "listExtensions").mockResolvedValue([]);

      const onSave = vi.fn().mockResolvedValue(undefined);
      render(
        <ProfileForm
          profile={profile("stopped")}
          hostOs="linux"
          viewerMode="vnc"
          onSave={onSave}
          onCancel={vi.fn()}
        />,
      );

      // Verify hardware fingerprints summary exists
      expect(screen.getByText(/高级硬件与隐私指纹/)).toBeTruthy();

      // Check presets: verify --disable-gpu button/preset is NOT present
      expect(screen.queryByTitle(/--disable-gpu/)).toBeNull();

      // Verify CloakBrowser preset is visible
      expect(screen.getByTitle(/--disable-blink-features=AutomationControlled/)).toBeTruthy();

      // Switch to Camoufox
      const typeSelect = screen.getByLabelText(/内核类型/) as HTMLSelectElement;
      fireEvent.change(typeSelect, { target: { value: "camoufox" } });

      // Verify Camoufox presets appear
      await waitFor(() => {
        expect(screen.getByTitle(/-mute-audio/)).toBeTruthy();
        expect(screen.getByTitle(/-private-window/)).toBeTruthy();
      });

      // Verify Firefox User Preferences section appears
      expect(screen.getByText(/Firefox 首选项配置/)).toBeTruthy();
    });

    it("does not flash uninstalled warning while kernels are loading on initial render", async () => {
      // Simulate slow API response
      let resolveKernels: (value: any) => void;
      const kernelsPromise = new Promise((resolve) => {
        resolveKernels = resolve;
      });
      vi.spyOn(api, "listKernels").mockReturnValue(kernelsPromise as any);
      vi.spyOn(api, "listExtensions").mockResolvedValue([]);

      const p = profile("stopped");
      p.browser_version = "151.0.7922.108.3";

      render(
        <ProfileForm
          profile={p}
          hostOs="linux"
          viewerMode="vnc"
          onSave={vi.fn()}
          onCancel={vi.fn()}
        />,
      );

      // Warning should NOT be displayed while kernels are still loading
      expect(screen.queryByText(/未检测到已安装的.*内核，请先下载内核/)).toBeNull();
      // Select option should retain the profile's browser_version instead of dropping to "未检测到已安装内核"
      expect(screen.getAllByText(/151.0.7922.108.3/).length).toBeGreaterThan(0);

      // Now resolve the API call
      resolveKernels!({
        kernels: [
          {
            version: "151.0.7922.108.3",
            name: "Chromium 151",
            browser_type: "cloakbrowser",
            tier: "pro",
            installed: true,
          },
        ],
      });

      await waitFor(() => {
        expect(screen.getAllByText(/Chromium 151 \(v151.0.7922.108.3\)/).length).toBeGreaterThan(0);
      });
    });

    it("resets proxy test results when switching to another profile or create mode", async () => {
      vi.spyOn(api, "listKernels").mockResolvedValue({ kernels: [] } as any);
      vi.spyOn(api, "listExtensions").mockResolvedValue([]);
      vi.spyOn(api, "getSubscriptions").mockResolvedValue([]);
      vi.spyOn(api, "getProxyNodes").mockResolvedValue([]);
      vi.spyOn(api, "getSettings").mockResolvedValue({ licenses: [] } as any);
      vi.spyOn(api, "testProxy").mockResolvedValue({
        ok: true,
        ip: "198.51.100.99",
        country: "JP",
        city: "Tokyo",
        timezone: "Asia/Tokyo",
        locale: "ja-JP",
        latency_ms: 45,
        cached: false,
      });

      const p1 = { ...profile("stopped"), id: "p1", name: "Profile 1", proxy: "http://1.1.1.1:8080" };
      const { rerender } = render(
        <ProfileForm
          profile={p1}
          hostOs="linux"
          viewerMode="vnc"
          onSave={vi.fn()}
          onCancel={vi.fn()}
        />,
      );

      // Trigger test connection
      const testBtn = screen.getByRole("button", { name: /测试连接/ });
      fireEvent.click(testBtn);

      await waitFor(() => {
        expect(api.testProxy).toHaveBeenCalled();
      });

      await waitFor(() => {
        expect(screen.getByText(/198\.51\.100\.99/)).toBeTruthy();
        expect(screen.getAllByText(/Asia\/Tokyo/).length).toBeGreaterThan(0);
      });

      // Switch to Profile 2
      const p2 = { ...profile("stopped"), id: "p2", name: "Profile 2", proxy: "http://2.2.2.2:8080" };
      rerender(
        <ProfileForm
          profile={p2}
          hostOs="linux"
          viewerMode="vnc"
          onSave={vi.fn()}
          onCancel={vi.fn()}
        />,
      );

      // Previous test result from Profile 1 MUST be cleared
      await waitFor(() => {
        expect(screen.queryByText(/198\.51\.100\.99/)).toBeNull();
        expect(screen.queryAllByText(/Asia\/Tokyo/)).toHaveLength(0);
      });
    });
  });
});


