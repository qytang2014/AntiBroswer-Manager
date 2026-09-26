import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useSystemProxyStatus, _resetSystemProxyStatusCache } from "./useSystemProxyStatus";
import { api } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    getSystemProxyStatus: vi.fn(),
  },
}));

describe("useSystemProxyStatus", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _resetSystemProxyStatusCache();
  });

  it("fetches system proxy status when autoFetch is true", async () => {
    const mockStatus = {
      active: true,
      tun_mode: true,
      http_proxy: null,
      detected_app: "Karing",
    };
    vi.mocked(api.getSystemProxyStatus).mockResolvedValue(mockStatus);

    const { result } = renderHook(() => useSystemProxyStatus(true));

    await waitFor(() => {
      expect(result.current.status).toEqual(mockStatus);
    });
    expect(api.getSystemProxyStatus).toHaveBeenCalled();
  });

  it("does not fetch automatically when autoFetch is false", () => {
    renderHook(() => useSystemProxyStatus(false));
    expect(api.getSystemProxyStatus).not.toHaveBeenCalled();
  });

  it("allows manual refresh", async () => {
    const mockStatus = {
      active: false,
      tun_mode: false,
      http_proxy: null,
      detected_app: null,
    };
    vi.mocked(api.getSystemProxyStatus).mockResolvedValue(mockStatus);

    const { result } = renderHook(() => useSystemProxyStatus(false));
    expect(result.current.status).toBeNull();

    await act(async () => {
      await result.current.refresh();
    });

    expect(result.current.status).toEqual(mockStatus);
  });
});
