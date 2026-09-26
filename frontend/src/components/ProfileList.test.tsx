import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ProfileList, formatKernelVersion, getProxyProtocol } from "./ProfileList";
import { api, type Profile, type SystemStatus } from "../lib/api";

describe("ProfileList proxy protocol and kernel version formatting", () => {
  it("formats kernel versions properly without double v", () => {
    expect(formatKernelVersion("v152.0.4-beta.31")).toBe("v152");
    expect(formatKernelVersion("vv152.0.4")).toBe("v152");
    expect(formatKernelVersion("151.0.7922.108.3")).toBe("v151");
    expect(formatKernelVersion("132")).toBe("v132");
    expect(formatKernelVersion("")).toBe(null);
    expect(formatKernelVersion(null)).toBe(null);
    expect(formatKernelVersion(undefined)).toBe(null);
  });

  it("detects proxy protocol correctly from various proxy formats", () => {
    expect(getProxyProtocol(null)).toBe(null);
    expect(getProxyProtocol("")).toBe(null);
    expect(getProxyProtocol("  ")).toBe(null);

    // Common protocols
    expect(getProxyProtocol("vless://user@host:443?security=reality")).toBe("VLESS");
    expect(getProxyProtocol("vmess://eyJhZGQiOiIxLjIuMy40In0=")).toBe("VMESS");
    expect(getProxyProtocol("trojan://pass@host:443")).toBe("Trojan");
    expect(getProxyProtocol("hysteria2://pass@host:443")).toBe("Hysteria2");
    expect(getProxyProtocol("hy2://pass@host:443")).toBe("Hysteria2");
    expect(getProxyProtocol("tuic://pass@host:443")).toBe("TUIC");
    expect(getProxyProtocol("ss://YWVzLTI1Ni1nY206cGFzc0AxLjIuMy40OjQ0Mw==")).toBe("SS");
    expect(getProxyProtocol("shadowsocks://YWVzLTI1Ni1nY206cGFzc0AxLjIuMy40OjQ0Mw==")).toBe("SS");
    expect(getProxyProtocol("wireguard://privatekey@host:51820")).toBe("WireGuard");
    expect(getProxyProtocol("wg://privatekey@host:51820")).toBe("WireGuard");
    expect(getProxyProtocol("anytls://pass@host:443")).toBe("AnyTLS");
    expect(getProxyProtocol("ssh://user:pass@host:22")).toBe("SSH");
    expect(getProxyProtocol("socks5://user:pass@127.0.0.1:1080")).toBe("SOCKS5");
    expect(getProxyProtocol("socks5h://127.0.0.1:1080")).toBe("SOCKS5");
    expect(getProxyProtocol("socks4://127.0.0.1:1080")).toBe("SOCKS4");
    expect(getProxyProtocol("http://127.0.0.1:8080")).toBe("HTTP");
    expect(getProxyProtocol("https://127.0.0.1:8443")).toBe("HTTPS");
    expect(getProxyProtocol("user:pass@1.2.3.4:8080")).toBe("HTTP");

    // JSON format
    expect(getProxyProtocol(JSON.stringify({ outbounds: [{ type: "vless" }] }))).toBe("VLESS");
    expect(getProxyProtocol(JSON.stringify({ outbounds: [{ type: "trojan" }] }))).toBe("TROJAN");
    expect(getProxyProtocol(JSON.stringify({ foo: "bar" }))).toBe("JSON");

    // Generic fallback
    expect(getProxyProtocol("custom-unknown-protocol-target")).toBe("Proxy");
  });

  it("renders proxy protocol badge and single-v kernel badge in profile list", () => {
    const mockProfile1: Profile = {
      id: "p1",
      name: "Profile Camoufox VLESS",
      fingerprint_seed: 1234,
      proxy: "vless://user@1.2.3.4:443",
      timezone: null,
      locale: null,
      screen_width: 1920,
      screen_height: 1080,
      gpu_family: "auto",
      humanize: false,
      human_preset: "default",
      geoip: false,
      clipboard_sync: false,
      auto_launch: false,
      color_scheme: null,
      launch_args: [],
      extension_paths: [],
      allow_3p_cookies: true,
      set_google_default: false,
      capture_preview: false,
      restore_session: false,
      browser_version: "v152.0.4-beta.31",
      browser_type: "camoufox",
      notes: null,
      user_data_dir: "/tmp/p1",
      created_at: "2026-01-01",
      updated_at: "2026-01-01",
      sort_order: 0,
      tags: [],
      status: "stopped",
      runtime_mode: "native",
      viewer_mode: "native-window",
      vnc_ws_port: null,
      cdp_url: null,
      last_error: null,
      license_id: null,
    };

    const mockProfile2: Profile = {
      ...mockProfile1,
      id: "p2",
      name: "Profile Direct",
      proxy: null,
      browser_version: "151.0.7922.108.3",
    };

    render(
      <ProfileList
        profiles={[mockProfile1, mockProfile2]}
        selectedId={null}
        onSelect={vi.fn()}
        onNew={vi.fn()}
        onReorder={vi.fn()}
        systemStatus={null}
      />,
    );

    // Profile 1 should display "VLESS" and "v152" (NOT "vv152" and NOT generic "Proxy")
    expect(screen.getByText("VLESS")).toBeTruthy();
    expect(screen.getByText("v152")).toBeTruthy();
    expect(screen.queryByText("vv152")).toBeNull();
    expect(screen.queryByText("Proxy")).toBeNull();

    // Profile 2 should display "v151" and have no proxy badge
    expect(screen.getByText("v151")).toBeTruthy();
  });
});

describe("ProfileList footer address badge & version", () => {
  const writeText = vi.fn().mockResolvedValue(undefined);

  beforeEach(() => {
    writeText.mockClear();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
  });

  const mockSystemStatus: SystemStatus = {
    running_count: 0,
    binary_version: "128.0.0",
    binary_installed: true,
    license_tier: "keyless",
    profiles_total: 0,
    host_os: "macos",
    runtime_mode: "native",
    viewer_mode: "native-window",
    windows_fonts_present: null,
    windows_fonts_required: null,
    windows_fonts_complete: null,
    app_version: "0.2.0-test",
    server_port: 8088,
    server_host: "127.0.0.1",
    server_url: "http://127.0.0.1:8088",
  };

  it("renders server access address and app version", () => {
    render(
      <ProfileList
        profiles={[]}
        selectedId={null}
        onSelect={vi.fn()}
        onNew={vi.fn()}
        onReorder={vi.fn()}
        systemStatus={mockSystemStatus}
      />,
    );

    expect(screen.getByText("127.0.0.1:8088")).toBeTruthy();
    expect(screen.getByText("v0.2.0-test")).toBeTruthy();
  });

  it("falls back to default 52341 and 0.1.0 when systemStatus is null", () => {
    render(
      <ProfileList
        profiles={[]}
        selectedId={null}
        onSelect={vi.fn()}
        onNew={vi.fn()}
        onReorder={vi.fn()}
        systemStatus={null}
      />,
    );

    expect(screen.getByText("127.0.0.1:52341")).toBeTruthy();
    expect(screen.getByText("v0.1.0")).toBeTruthy();
  });

  it("opens access url in browser when clicking the address button", async () => {
    const openSpy = vi.spyOn(api, "openExternal").mockResolvedValue({ ok: true });

    render(
      <ProfileList
        profiles={[]}
        selectedId={null}
        onSelect={vi.fn()}
        onNew={vi.fn()}
        onReorder={vi.fn()}
        systemStatus={mockSystemStatus}
      />,
    );

    const openBtn = screen.getByTitle("在浏览器中打开 / Open in browser");
    fireEvent.click(openBtn);

    await waitFor(() => {
      expect(openSpy).toHaveBeenCalledWith("http://127.0.0.1:8088");
    });
  });

  it("copies access url to clipboard on copy button click and shows feedback", async () => {
    render(
      <ProfileList
        profiles={[]}
        selectedId={null}
        onSelect={vi.fn()}
        onNew={vi.fn()}
        onReorder={vi.fn()}
        systemStatus={mockSystemStatus}
      />,
    );

    const copyBtn = screen.getByTitle("复制访问地址 / Copy address");
    fireEvent.click(copyBtn);

    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith("http://127.0.0.1:8088");
      expect(screen.getByTitle("已复制")).toBeTruthy();
    });
  });
});
