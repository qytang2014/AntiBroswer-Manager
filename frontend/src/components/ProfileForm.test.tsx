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
      expect(screen.getByText(/Camoufox 152/)).toBeTruthy();
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

  describe("compareKernelVersions", () => {
    it("correctly sorts Chromium and Camoufox versions descending", async () => {
      const { compareKernelVersions } = await import("./ProfileForm");

      const chromium = ["145.0.7632.109.2", "151.0.7922.108.3", "132.0.6834.83.1"];
      chromium.sort((a, b) => compareKernelVersions(b, a));
      expect(chromium).toEqual(["151.0.7922.108.3", "145.0.7632.109.2", "132.0.6834.83.1"]);

      const camoufox = ["v152.0.4-beta.29", "v152.0.4-beta.31", "130.0", "v152.0.4-beta.30"];
      camoufox.sort((a, b) => compareKernelVersions(b, a));
      expect(camoufox).toEqual(["v152.0.4-beta.31", "v152.0.4-beta.30", "v152.0.4-beta.29", "130.0"]);
    });
  });
});


