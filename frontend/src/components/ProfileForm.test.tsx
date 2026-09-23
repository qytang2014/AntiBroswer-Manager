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
});


