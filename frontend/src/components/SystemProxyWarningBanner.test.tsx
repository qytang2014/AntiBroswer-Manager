import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SystemProxyWarningBanner } from "./SystemProxyWarningBanner";

describe("SystemProxyWarningBanner", () => {
  it("renders nothing when status is null or inactive", () => {
    const { container, rerender } = render(<SystemProxyWarningBanner status={null} />);
    expect(container.firstChild).toBeNull();

    rerender(
      <SystemProxyWarningBanner
        status={{ active: false, tun_mode: false, http_proxy: null, detected_app: null }}
      />
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders warning banner when Karing TUN is detected", () => {
    render(
      <SystemProxyWarningBanner
        status={{
          active: true,
          tun_mode: true,
          http_proxy: null,
          detected_app: "Karing",
        }}
      />
    );

    expect(screen.getByText(/提示：宿主机已开启 Karing/)).toBeTruthy();
    expect(screen.getByText(/TUN 虚拟网卡模式/)).toBeTruthy();
    expect(screen.getByText(/若您未在 Karing 中连接代理节点/)).toBeTruthy();
  });

  it("renders warning banner for standard system proxy with http_proxy info", () => {
    render(
      <SystemProxyWarningBanner
        status={{
          active: true,
          tun_mode: false,
          http_proxy: "127.0.0.1:7890",
          detected_app: "Clash",
        }}
      />
    );

    expect(screen.getByText(/提示：宿主机已开启 Clash/)).toBeTruthy();
    expect(screen.getByText(/127.0.0.1:7890/)).toBeTruthy();
  });

  it("calls onRefresh when refresh button clicked", () => {
    const onRefresh = vi.fn();
    render(
      <SystemProxyWarningBanner
        status={{
          active: true,
          tun_mode: true,
          http_proxy: null,
          detected_app: "Karing",
        }}
        onRefresh={onRefresh}
      />
    );

    const button = screen.getByRole("button", { name: /重新检测系统代理状态/ });
    fireEvent.click(button);
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it("dismisses banner when close button is clicked", () => {
    const { container } = render(
      <SystemProxyWarningBanner
        status={{
          active: true,
          tun_mode: true,
          http_proxy: null,
          detected_app: "Karing",
        }}
      />
    );

    expect(screen.getByText(/提示：宿主机已开启 Karing/)).toBeTruthy();
    const closeBtn = screen.getByRole("button", { name: /关闭提示/ });
    fireEvent.click(closeBtn);
    expect(container.firstChild).toBeNull();
  });
});
