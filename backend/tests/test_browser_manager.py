"""Tests for browser_manager pure functions — proxy parsing, fingerprint args, profile defaults."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.browser_manager import (
    _init_profile_defaults,
    _normalize_proxy,
    _validate_proxy,
    BrowserManager,
    ProfileBusyError,
    RunningProfile,
    SEARCH_ENGINE_MARKER,
)
from backend.runtime import RuntimeConfig

DOCKER_RUNTIME = RuntimeConfig(
    host_os="linux",
    runtime_mode="docker",
    viewer_mode="vnc",
    data_dir=Path("/data"),
)
NATIVE_RUNTIME = RuntimeConfig(
    host_os="windows",
    runtime_mode="native",
    viewer_mode="native-window",
    data_dir=Path("C:/manager-data"),
)


# ── _normalize_proxy ─────────────────────────────────────────────────────────


def test_normalize_already_http():
    assert _normalize_proxy("http://user:pass@host:8080") == "http://user:pass@host:8080"


def test_normalize_already_https():
    assert _normalize_proxy("https://host:443") == "https://host:443"


def test_normalize_already_socks5():
    assert _normalize_proxy("socks5://host:1080") == "socks5://host:1080"


def test_normalize_host_port_user_pass():
    assert _normalize_proxy("proxy.com:8080:myuser:mypass") == "http://myuser:mypass@proxy.com:8080"


def test_normalize_host_port_only():
    assert _normalize_proxy("proxy.com:8080") == "http://proxy.com:8080"


def test_normalize_three_parts():
    # 3 parts doesn't match any pattern — returned as-is
    assert _normalize_proxy("a:b:c") == "a:b:c"


def test_normalize_five_parts():
    # 5 parts doesn't match — returned as-is
    assert _normalize_proxy("a:b:c:d:e") == "a:b:c:d:e"


def test_normalize_empty_parts():
    # host:port:user:pass with empty parts
    result = _normalize_proxy(":8080:user:pass")
    assert result == "http://user:pass@:8080"


# ── _validate_proxy ──────────────────────────────────────────────────────────


def test_validate_valid_http():
    _validate_proxy("http://proxy.com:8080")  # should not raise


def test_validate_valid_socks5():
    _validate_proxy("socks5://proxy.com:1080")  # should not raise


def test_validate_valid_with_auth():
    _validate_proxy("http://user:pass@proxy.com:8080")  # should not raise


def test_validate_bad_scheme():
    with pytest.raises(ValueError, match="Invalid proxy scheme 'ftp'"):
        _validate_proxy("ftp://host:80")


def test_validate_no_hostname():
    with pytest.raises(ValueError, match="missing hostname"):
        _validate_proxy("http://:8080")


def test_validate_no_port():
    with pytest.raises(ValueError, match="missing port"):
        _validate_proxy("http://host")


# ── _build_fingerprint_args ──────────────────────────────────────────────────

# Use the BrowserManager instance to call the method
_mgr = BrowserManager(DOCKER_RUNTIME)


def test_build_args_uses_only_current_managed_flags():
    args = _mgr._build_fingerprint_args({})
    assert "--disable-infobars" not in args
    assert "--test-type" not in args
    assert "--use-angle=swiftshader" in args


def test_build_args_seed():
    args = _mgr._build_fingerprint_args({"fingerprint_seed": 42})
    assert "--fingerprint=42" in args


def test_build_args_no_seed():
    args = _mgr._build_fingerprint_args({"fingerprint_seed": None})
    assert not any(a.startswith("--fingerprint=") for a in args)


def test_build_args_platform_comes_from_runtime():
    assert "--fingerprint-platform=windows" in _mgr._build_fingerprint_args({})
    mac_runtime = RuntimeConfig(
        host_os="macos",
        runtime_mode="native",
        viewer_mode="native-window",
        data_dir=Path("/tmp/manager-data"),
    )
    mac_manager = BrowserManager(mac_runtime)
    assert "--fingerprint-platform=macos" in mac_manager._build_fingerprint_args({})
    assert not any(
        "gpu-vendor" in arg
        for arg in mac_manager._build_fingerprint_args({"gpu_family": "nvidia"})
    )


def test_build_args_gpu_family_and_cookie_compatibility():
    nvidia = _mgr._build_fingerprint_args({"gpu_family": "nvidia", "allow_3p_cookies": True})
    assert "--fingerprint-gpu-vendor=NVIDIA" in nvidia
    assert "--fingerprint-allow-3p-cookies" in nvidia
    intel = _mgr._build_fingerprint_args({"gpu_family": "intel"})
    assert "--fingerprint-gpu-vendor=Intel" in intel
    assert not any("gpu-vendor" in arg for arg in _mgr._build_fingerprint_args({"gpu_family": "auto"}))


def test_build_args_screen():
    args = _mgr._build_fingerprint_args({"screen_width": 2560, "screen_height": 1440})
    assert "--fingerprint-screen-width=2560" in args
    assert "--fingerprint-screen-height=1440" in args


def test_build_args_empty_profile():
    args = _mgr._build_fingerprint_args({})
    # Docker software rendering + runtime platform + default noise suppression.
    assert len(args) == 3
    assert "--fingerprint-noise=false" in args


def test_native_build_args_do_not_force_software_gl():
    args = BrowserManager(NATIVE_RUNTIME)._build_fingerprint_args({})
    assert "--use-angle=swiftshader" not in args


# ── launch_args appended to extra_args ────────────────────────────────────────


def test_launch_args_appended_to_fingerprint_args():
    """launch_args from profile should appear in the args list after fingerprint args."""
    profile = {
        "fingerprint_seed": 42,
        "launch_args": ["--load-extension=/tmp/ext", "--disable-features=Foo"],
    }
    args = _mgr._build_fingerprint_args(profile)
    args += profile.get("launch_args") or []
    assert "--load-extension=/tmp/ext" in args
    assert "--disable-features=Foo" in args
    # Fingerprint args still present
    assert "--fingerprint=42" in args


def test_launch_args_empty_no_effect():
    profile = {"launch_args": []}
    args = _mgr._build_fingerprint_args(profile)
    base_count = len(args)
    args += profile.get("launch_args") or []
    assert len(args) == base_count


def test_launch_args_none_no_effect():
    profile = {"launch_args": None}
    args = _mgr._build_fingerprint_args(profile)
    base_count = len(args)
    args += profile.get("launch_args") or []
    assert len(args) == base_count


# ── runtime-specific launch behavior ─────────────────────────────────────────


def _launch_profile(tmp_path: Path) -> dict:
    user_data_dir = tmp_path / "profile-1"
    user_data_dir.mkdir(parents=True, exist_ok=True)
    # Skip the one-time default-search-engine setup (unrelated to launch mechanics;
    # it would otherwise spawn its own real browser launches during these tests).
    (user_data_dir / SEARCH_ENGINE_MARKER).write_text("google\n")
    return {
        "id": "profile-1",
        "name": "Native",
        "user_data_dir": str(user_data_dir),
        "screen_width": 1920,
        "screen_height": 1080,
        "launch_args": [],
    }


@pytest.mark.asyncio
async def test_native_launch_skips_vnc_and_display(monkeypatch, tmp_path: Path):
    from backend import browser_manager as module

    context = MagicMock()
    context.pages = []
    context.add_init_script = AsyncMock()
    manager = BrowserManager(NATIVE_RUNTIME)
    manager.vnc.allocate = AsyncMock()
    manager.vnc.start_vnc = AsyncMock()
    manager._wait_for_cdp = AsyncMock()
    launch = AsyncMock(return_value=context)
    monkeypatch.setattr(module, "launch_persistent_context_async", launch)

    running = await manager.launch(_launch_profile(tmp_path))

    assert running.display is None
    assert running.ws_port is None
    manager.vnc.allocate.assert_not_awaited()
    manager.vnc.start_vnc.assert_not_awaited()
    context.add_init_script.assert_not_awaited()
    options = launch.await_args.kwargs
    assert "env" not in options
    assert "viewport" not in options
    assert "--use-angle=swiftshader" not in options["args"]
    assert "--remote-debugging-address=127.0.0.1" in options["args"]
    assert options["headless"] is False
    assert options["extension_paths"] == []


@pytest.mark.asyncio
async def test_native_close_event_releases_session(monkeypatch, tmp_path: Path):
    from backend import browser_manager as module

    context = MagicMock(pages=[])
    context.add_init_script = AsyncMock()
    manager = BrowserManager(NATIVE_RUNTIME)
    manager._wait_for_cdp = AsyncMock()
    monkeypatch.setattr(
        module,
        "launch_persistent_context_async",
        AsyncMock(return_value=context),
    )
    running = await manager.launch(_launch_profile(tmp_path))
    close_callback = context.on.call_args.args[1]

    await close_callback(context)

    assert "profile-1" not in manager.running
    assert running.cdp_port not in manager._cdp_ports


@pytest.mark.asyncio
async def test_launch_rejects_user_debugging_flags(tmp_path: Path):
    manager = BrowserManager(NATIVE_RUNTIME)
    profile = _launch_profile(tmp_path)
    profile["launch_args"] = ["--remote-debugging-address=0.0.0.0"]

    with pytest.raises(ValueError, match="Manager owns remote debugging"):
        await manager.launch(profile)

    assert "profile-1" not in manager._launching
    assert manager._cdp_ports == set()


@pytest.mark.asyncio
async def test_docker_launch_keeps_vnc_display(monkeypatch, tmp_path: Path):
    from backend import browser_manager as module

    context = MagicMock()
    context.pages = []
    context.add_init_script = AsyncMock()
    manager = BrowserManager(DOCKER_RUNTIME)
    manager.vnc.allocate = AsyncMock(return_value=(100, 6100))
    manager.vnc.start_vnc = AsyncMock()
    manager._wait_for_cdp = AsyncMock()
    launch = AsyncMock(return_value=context)
    monkeypatch.setattr(module, "launch_persistent_context_async", launch)

    running = await manager.launch(_launch_profile(tmp_path))

    assert running.display == 100
    assert running.ws_port == 6100
    manager.vnc.start_vnc.assert_awaited_once()
    context.add_init_script.assert_awaited_once()
    options = launch.await_args.kwargs
    assert options["env"]["DISPLAY"] == ":100"
    assert options["viewport"] == {"width": 1920, "height": 947}
    assert "--use-angle=swiftshader" in options["args"]


@pytest.mark.asyncio
async def test_launch_passes_license_config(monkeypatch, tmp_path: Path):
    from backend import browser_manager as module

    context = MagicMock(pages=[])
    context.add_init_script = AsyncMock()
    manager = BrowserManager(
        NATIVE_RUNTIME, license_key="cb_test", release_channel="preview",
        licenses=[{"id": "lic-1", "key": "cb_test"}]
    )
    manager._wait_for_cdp = AsyncMock()
    launch = AsyncMock(return_value=context)
    monkeypatch.setattr(module, "launch_persistent_context_async", launch)

    profile = _launch_profile(tmp_path)
    profile["license_id"] = "lic-1"
    profile["extension_paths"] = ["/tmp/extension"]
    profile["launch_args"] = ["--raw-flag"]
    await manager.launch(profile)

    options = launch.await_args.kwargs
    assert options["license_key"] == "cb_test"
    assert options["release_channel"] == "preview"
    assert options["extension_paths"] == ["/tmp/extension"]
    assert options["args"].index("--raw-flag") > options["args"].index("--fingerprint-platform=windows")


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_launch_gates_search_engine_on_flag(monkeypatch, tmp_path: Path, enabled: bool):
    from backend import browser_manager as module

    context = MagicMock(pages=[])
    context.add_init_script = AsyncMock()
    manager = BrowserManager(NATIVE_RUNTIME)
    manager._wait_for_cdp = AsyncMock()
    manager._ensure_search_engine = AsyncMock()
    monkeypatch.setattr(
        module, "launch_persistent_context_async", AsyncMock(return_value=context)
    )

    profile = _launch_profile(tmp_path)
    profile["set_google_default"] = enabled
    await manager.launch(profile)

    if enabled:
        manager._ensure_search_engine.assert_awaited_once()
    else:
        manager._ensure_search_engine.assert_not_awaited()


@pytest.mark.asyncio
async def test_launch_retries_failed_cdp_and_closes_first_context(
    monkeypatch,
    tmp_path: Path,
):
    from backend import browser_manager as module

    first_context = MagicMock(pages=[])
    first_context.close = AsyncMock()
    second_context = MagicMock(pages=[])
    second_context.add_init_script = AsyncMock()
    second_context.close = AsyncMock()
    manager = BrowserManager(NATIVE_RUNTIME)
    manager._wait_for_cdp = AsyncMock(side_effect=[TimeoutError("busy"), None])
    launch = AsyncMock(side_effect=[first_context, second_context])
    monkeypatch.setattr(module, "launch_persistent_context_async", launch)

    running = await manager.launch(_launch_profile(tmp_path))

    assert launch.await_count == 2
    first_context.close.assert_awaited_once()
    assert running.cdp_port in manager._cdp_ports


@pytest.mark.asyncio
async def test_failed_launch_stays_active_until_its_context_is_closed(monkeypatch, tmp_path: Path):
    """A launch that fails AFTER the browser is up must keep the profile active
    while the half-launched context is being closed — the failure path used to
    drop _launching before awaiting the close, leaving a window in which
    hold_stopped() (duplicate / reset / delete) would touch a live profile dir."""
    from backend import browser_manager as module

    context = MagicMock(pages=[])
    context.on = MagicMock(side_effect=RuntimeError("post-startup wiring failed"))
    closing, finish = asyncio.Event(), asyncio.Event()

    async def blocked_close(*_args):
        closing.set()
        await finish.wait()

    manager = BrowserManager(NATIVE_RUNTIME)
    manager._wait_for_cdp = AsyncMock()
    manager._ensure_search_engine = AsyncMock()
    monkeypatch.setattr(manager, "_close_context", blocked_close)
    monkeypatch.setattr(module, "launch_persistent_context_async", AsyncMock(return_value=context))
    profile = _launch_profile(tmp_path)
    profile["timezone"] = "UTC"
    profile["locale"] = "en-US"
    profile["geoip"] = False
    pid = profile["id"]

    task = asyncio.create_task(manager.launch(profile))
    await asyncio.wait_for(closing.wait(), 5)
    try:
        assert pid not in manager._launching  # the exact window: cleanup pending
        assert manager.is_active(pid)
        with pytest.raises(ProfileBusyError):
            async with manager.hold_stopped(pid):
                pass
    finally:
        finish.set()
    with pytest.raises(RuntimeError, match="post-startup wiring failed"):
        await task

    # Once cleanup has finished the profile is genuinely stopped again
    assert not manager.is_active(pid)
    async with manager.hold_stopped(pid):
        pass


@pytest.mark.asyncio
async def test_launch_is_refused_while_the_previous_browser_is_still_closing(monkeypatch):
    """A relaunch during shutdown used to be admitted, and if it then failed its
    cleanup cleared the shutdown's `_stopping` entry — leaving the still-closing
    profile inactive to hold_stopped(). Now the relaunch is refused outright."""
    manager = BrowserManager(DOCKER_RUNTIME)
    closing, finish = asyncio.Event(), asyncio.Event()

    async def blocked_close(*_args):
        closing.set()
        await finish.wait()

    monkeypatch.setattr(manager, "_close_context", blocked_close)
    manager.vnc.allocate = AsyncMock(return_value=(101, 6101))
    manager.vnc.start_vnc = AsyncMock(side_effect=RuntimeError("Xvnc failed to start"))
    manager.vnc.stop_vnc = AsyncMock()
    manager.running["profile-1"] = RunningProfile("profile-1", object(), 19001, capture_preview=False)

    stop = asyncio.create_task(manager.stop("profile-1"))
    await asyncio.wait_for(closing.wait(), 2)
    try:
        assert manager.is_active("profile-1")
        with pytest.raises(ProfileBusyError, match="still closing"):
            await manager.launch({"id": "profile-1", "user_data_dir": "/nonexistent"})
        # The refused launch touched nothing: the shutdown reservation is intact
        assert not stop.done()
        assert manager.is_active("profile-1")
        manager.vnc.allocate.assert_not_awaited()
    finally:
        finish.set()
        await stop
    assert not manager.is_active("profile-1")


def test_stopping_reservations_are_counted_per_operation():
    """One operation's cleanup must never release another's reservation."""
    manager = BrowserManager(NATIVE_RUNTIME)
    manager._reserve_stopping("p")
    manager._reserve_stopping("p")
    manager._release_stopping("p")
    assert manager.is_active("p")
    manager._release_stopping("p")
    assert not manager.is_active("p")
    manager._release_stopping("p")  # over-release is harmless
    assert not manager.is_active("p")


@pytest.mark.asyncio
async def test_stop_releases_native_cdp_port():
    manager = BrowserManager(NATIVE_RUNTIME)
    context = MagicMock()
    context.close = AsyncMock()
    port = manager._reserve_cdp_port()
    manager.running["profile-1"] = module_running = RunningProfile(
        "profile-1", context, port
    )

    await manager.stop("profile-1")

    context.close.assert_awaited_once()
    assert module_running.cdp_port not in manager._cdp_ports
    assert "profile-1" not in manager.running


# ── CDP reservation and verification ─────────────────────────────────────────


def test_reserve_cdp_port_tracks_unique_ports():
    manager = BrowserManager(NATIVE_RUNTIME)
    first = manager._reserve_cdp_port()
    second = manager._reserve_cdp_port()
    assert first != second
    assert manager._cdp_ports == {first, second}


def test_release_cdp_port_is_idempotent():
    manager = BrowserManager(NATIVE_RUNTIME)
    port = manager._reserve_cdp_port()
    manager._release_cdp_port(port)
    manager._release_cdp_port(port)
    assert port not in manager._cdp_ports


@pytest.mark.asyncio
async def test_wait_for_cdp_verifies_debugger_port(monkeypatch):
    manager = BrowserManager(NATIVE_RUNTIME)
    fetch = AsyncMock(return_value={
        "webSocketDebuggerUrl": "ws://127.0.0.1:53123/devtools/browser/test",
    })
    monkeypatch.setattr(manager, "_fetch_cdp_version", fetch)
    await manager._wait_for_cdp(53123, timeout=0.1)


@pytest.mark.asyncio
async def test_wait_for_cdp_rejects_wrong_debugger_port(monkeypatch):
    manager = BrowserManager(NATIVE_RUNTIME)
    fetch = AsyncMock(return_value={
        "webSocketDebuggerUrl": "ws://127.0.0.1:53124/devtools/browser/test",
    })
    monkeypatch.setattr(manager, "_fetch_cdp_version", fetch)
    with pytest.raises(TimeoutError, match="was not ready"):
        await manager._wait_for_cdp(53123, timeout=0.01)


# ── _init_profile_defaults ───────────────────────────────────────────────────


def test_init_creates_bookmarks(tmp_path: Path):
    _init_profile_defaults(tmp_path)
    bookmarks_path = tmp_path / "Default" / "Bookmarks"
    assert bookmarks_path.exists()
    data = json.loads(bookmarks_path.read_text())
    children = data["roots"]["bookmark_bar"]["children"]
    assert len(children) == 4  # 4 folders
    folder_names = {f["name"] for f in children}
    assert folder_names == {"Detection Tests", "Fingerprint", "Headers & TLS", "reCAPTCHA"}


def test_init_creates_bookmarks_not_preferences(tmp_path: Path):
    _init_profile_defaults(tmp_path)
    # Bookmarks are seeded here.
    assert (tmp_path / "Default" / "Bookmarks").exists()
    # The default search engine is NOT set via Preferences (it can't stick — it
    # lives in MAC-protected Secure Preferences). That is handled once per profile
    # by BrowserManager._ensure_search_engine, not here.
    assert not (tmp_path / "Default" / "Preferences").exists()


def test_init_idempotent(tmp_path: Path):
    _init_profile_defaults(tmp_path)
    bookmarks_path = tmp_path / "Default" / "Bookmarks"
    original = bookmarks_path.read_text()

    # Write a sentinel to the file
    bookmarks_path.write_text("SENTINEL")

    # Second call should NOT overwrite (file already exists)
    _init_profile_defaults(tmp_path)
    assert bookmarks_path.read_text() == "SENTINEL"


# ── Kernel version selection & launch args validation ────────────────────────


@pytest.mark.asyncio
async def test_launch_rejects_inline_proxy_auth_on_old_kernel(monkeypatch, tmp_path):
    manager = BrowserManager(NATIVE_RUNTIME, license_key="test-key")
    monkeypatch.setattr(manager, "is_binary_ready", lambda: True)

    profile = {
        "id": "prof-1",
        "user_data_dir": str(tmp_path / "user_data"),
        "launch_args": ["--proxy-server=http://user:pass@1.2.3.4:8080"],
        "browser_version": "145.0.7632.109.2",
    }
    Path(profile["user_data_dir"]).mkdir(parents=True, exist_ok=True)

    with pytest.raises(ValueError, match="不支持在命令行参数中直接传递代理密码"):
        await manager.launch(profile)


@pytest.mark.asyncio
async def test_launch_kernel_resolution_and_fallback(monkeypatch, tmp_path):
    manager = BrowserManager(NATIVE_RUNTIME, license_key="test-key", licenses=[{"id": "lic-pro", "key": "test-key"}])
    monkeypatch.setattr(manager, "is_binary_ready", lambda: True)

    # Mock launch_persistent_context_async
    captured_options = {}

    async def mock_launch(**kwargs):
        captured_options.update(kwargs)
        mock_ctx = MagicMock()
        mock_ctx.pages = []
        return mock_ctx

    monkeypatch.setattr("backend.browser_manager.launch_persistent_context_async", mock_launch)
    monkeypatch.setattr(manager, "_wait_for_cdp", AsyncMock())
    monkeypatch.setattr(manager, "_reserve_cdp_port", lambda: 55000)

    # 1. Non-existent kernel -> Option A fallback
    profile = {
        "id": "prof-fallback",
        "user_data_dir": str(tmp_path / "p1"),
        "browser_version": "999.0.0.0",
    }
    Path(profile["user_data_dir"]).mkdir(parents=True, exist_ok=True)

    running = await manager.launch(profile)
    assert running.is_fallback is True
    assert captured_options["browser_version"] != "999.0.0.0"
    await manager.stop("prof-fallback")

    # 2. Free kernel (e.g. 145) -> license_key is None (unrestricted)
    monkeypatch.setattr("backend.browser_manager.get_binary_path", lambda ver, pro=False: (
        tmp_path / f"bin-{ver}-{'pro' if pro else 'free'}"
    ))
    monkeypatch.setattr("backend.browser_manager._is_executable", lambda p: True)

    # Simulate free binary exists, pro binary does not
    def fake_get_binary_path(ver, pro=False):
        p = tmp_path / f"bin-{ver}-{'pro' if pro else 'free'}"
        if not pro and ver == "145.0.7632.109.2":
            p.touch()
        elif pro and ver == "151.0.7922.108.3":
            p.touch()
        return p

    monkeypatch.setattr("backend.browser_manager.get_binary_path", fake_get_binary_path)

    profile_free = {
        "id": "prof-free",
        "user_data_dir": str(tmp_path / "p2"),
        "browser_version": "145.0.7632.109.2",
    }
    Path(profile_free["user_data_dir"]).mkdir(parents=True, exist_ok=True)

    running_free = await manager.launch(profile_free)
    assert running_free.kernel_version == "145.0.7632.109.2"
    assert running_free.is_fallback is False
    assert captured_options["license_key"] is None  # Free kernel has no license key passed
    await manager.stop("prof-free")

    # 3. Pro kernel -> license_key is preserved
    profile_pro = {
        "id": "prof-pro",
        "user_data_dir": str(tmp_path / "p3"),
        "browser_version": "151.0.7922.108.3",
        "license_id": "lic-pro",
    }
    Path(profile_pro["user_data_dir"]).mkdir(parents=True, exist_ok=True)

    running_pro = await manager.launch(profile_pro)
    assert running_pro.kernel_version == "151.0.7922.108.3"
    assert captured_options["license_key"] == "test-key"
    await manager.stop("prof-pro")


@pytest.mark.asyncio
async def test_headless_search_engine_setup_uses_free_kernel_license(monkeypatch, tmp_path):
    manager = BrowserManager(NATIVE_RUNTIME, license_key="pro-key", licenses=[{"id": "lic-pro", "key": "pro-key"}])
    monkeypatch.setattr(manager, "is_binary_ready", lambda: True)

    captured_headless_options = {}

    async def mock_headless_launch(user_data_dir, browser_version=None, license_key=None):
        captured_headless_options["browser_version"] = browser_version
        captured_headless_options["license_key"] = license_key
        mock_ctx = MagicMock()
        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value={"keyword": "google.com"})
        mock_ctx.new_page = AsyncMock(return_value=mock_page)
        return mock_ctx

    monkeypatch.setattr(manager, "_headless_launch", mock_headless_launch)
    monkeypatch.setattr(manager, "_close_context", AsyncMock())
    monkeypatch.setattr(manager, "_wait_for_cdp", AsyncMock())
    monkeypatch.setattr(manager, "_reserve_cdp_port", lambda: 55001)

    # Free binary exists, Pro does not
    monkeypatch.setattr("backend.browser_manager.get_binary_path", lambda ver, pro=False: (
        tmp_path / f"bin-{ver}-{'pro' if pro else 'free'}"
    ))
    (tmp_path / "bin-145.0.7632.109.2-free").touch()
    monkeypatch.setattr("backend.browser_manager._is_executable", lambda p: True)

    async def mock_launch(**kwargs):
        mock_ctx = MagicMock()
        mock_ctx.pages = []
        return mock_ctx

    monkeypatch.setattr("backend.browser_manager.launch_persistent_context_async", mock_launch)

    profile_free = {
        "id": "prof-free-init",
        "user_data_dir": str(tmp_path / "p-free-init"),
        "browser_version": "145.0.7632.109.2",
        "set_google_default": True,
    }
    Path(profile_free["user_data_dir"]).mkdir(parents=True, exist_ok=True)

    running = await manager.launch(profile_free)
    assert captured_headless_options["browser_version"] == "145.0.7632.109.2"
    assert captured_headless_options["license_key"] is None  # Must NOT pass Pro license key!
    await manager.stop("prof-free-init")


def test_build_fingerprint_args_dnt_and_webgl():
    manager_mac = BrowserManager(RuntimeConfig(runtime_mode="native", viewer_mode="native-window", host_os="macos", data_dir=Path("/data")))
    # macOS runtime: webgl_vendor shouldn't force NVIDIA/Intel vendor flag
    args_mac = manager_mac._build_fingerprint_args({"do_not_track": True, "webgl_vendor": "NVIDIA Corporation"})
    assert "--enable-do-not-track" in args_mac
    assert "--fingerprint-gpu-vendor=NVIDIA" not in args_mac

    # Non-macOS runtime: webgl_vendor fallback works
    manager_linux = BrowserManager(RuntimeConfig(runtime_mode="native", viewer_mode="native-window", host_os="linux", data_dir=Path("/data")))
    args_linux = manager_linux._build_fingerprint_args({"do_not_track": True, "webgl_vendor": "NVIDIA GeForce RTX 4070"})
    assert "--enable-do-not-track" in args_linux
    assert "--fingerprint-gpu-vendor=NVIDIA" in args_linux


def test_build_fingerprint_args_noise_control():
    # When canvas_noise is False or omitted, --fingerprint-noise=false is appended
    args_default = _mgr._build_fingerprint_args({})
    assert "--fingerprint-noise=false" in args_default

    args_false = _mgr._build_fingerprint_args({"canvas_noise": False})
    assert "--fingerprint-noise=false" in args_false

    args_zero = _mgr._build_fingerprint_args({"canvas_noise": 0})
    assert "--fingerprint-noise=false" in args_zero

    # When canvas_noise is True, --fingerprint-noise=false is NOT appended
    args_true = _mgr._build_fingerprint_args({"canvas_noise": True})
    assert "--fingerprint-noise=false" not in args_true


def test_build_fingerprint_args_hardware_and_webgl():
    manager_mac = BrowserManager(RuntimeConfig(runtime_mode="native", viewer_mode="native-window", host_os="macos", data_dir=Path("/data")))
    args = manager_mac._build_fingerprint_args({
        "cpu_cores": 8,
        "memory_gb": 16,
        "webgl_renderer": "ANGLE (Apple, Apple M3, OpenGL 4.1)",
        "webgl_vendor": "Google Inc. (Apple)",
    })
    assert "--fingerprint-hardware-concurrency=8" in args
    assert "--fingerprint-device-memory=16" in args
    assert "--fingerprint-gpu-renderer=ANGLE (Apple, Apple M3, OpenGL 4.1)" in args
    assert "--fingerprint-gpu-vendor=Google Inc. (Apple)" in args


@pytest.mark.asyncio
async def test_launch_uses_engine_isolated_extra_launch_args(monkeypatch, tmp_path):
    manager = BrowserManager(NATIVE_RUNTIME)
    monkeypatch.setattr(manager, "is_binary_ready", lambda: True)
    monkeypatch.setattr(manager, "_reserve_cdp_port", lambda: 55002)
    monkeypatch.setattr(manager, "_wait_for_cdp", AsyncMock())
    monkeypatch.setattr(manager, "_ensure_search_engine", AsyncMock())
    monkeypatch.setattr("backend.browser_manager.get_binary_path", lambda ver, pro=False: tmp_path / f"bin-{ver}")
    (tmp_path / "bin-145").touch()
    monkeypatch.setattr("backend.browser_manager._is_executable", lambda p: True)

    captured_launch_args = []

    async def mock_launch(**kwargs):
        captured_launch_args.extend(kwargs.get("args", []))
        mock_ctx = MagicMock()
        mock_ctx.pages = []
        mock_ctx.add_init_script = AsyncMock()
        return mock_ctx

    monkeypatch.setattr("backend.browser_manager.launch_persistent_context_async", mock_launch)

    profile = {
        "id": "prof-isolated",
        "user_data_dir": str(tmp_path / "p-isolated"),
        "browser_type": "cloakbrowser",
        "browser_version": "145",
        "extra_launch_args": {
            "cloakbrowser": ["--custom-cloak-flag"],
            "camoufox": ["-mute-audio"],
        },
    }
    Path(profile["user_data_dir"]).mkdir(parents=True, exist_ok=True)

    running = await manager.launch(profile)
    assert "--custom-cloak-flag" in captured_launch_args
    assert "-mute-audio" not in captured_launch_args
    await manager.stop("prof-isolated")


@pytest.mark.asyncio
async def test_camoufox_launch_config_and_user_prefs(monkeypatch, tmp_path):
    manager = BrowserManager(NATIVE_RUNTIME)
    monkeypatch.setattr(manager, "is_binary_ready", lambda: True)
    monkeypatch.setattr(manager, "_ensure_camoufox_search_engine", AsyncMock())

    captured_options = {}

    async def mock_camoufox_browser(pw, **kwargs):
        captured_options.update(kwargs)
        mock_ctx = MagicMock()
        mock_ctx.pages = []
        return mock_ctx

    monkeypatch.setattr("camoufox.async_api.AsyncNewBrowser", mock_camoufox_browser)

    mock_pw = MagicMock()
    mock_pw.stop = AsyncMock()

    class MockAsyncPlaywright:
        async def start(self):
            return mock_pw

    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: MockAsyncPlaywright())

    mock_version = MagicMock()
    mock_version.version = "152.0.4"
    mock_version.build = "beta.31"
    mock_version.full_string = "152.0.4-beta.31"
    mock_inst = MagicMock()
    mock_inst.version = mock_version
    mock_inst.path = Path("/mock/camoufox/152.0.4-beta.31")
    mock_inst.is_active = True
    monkeypatch.setattr("camoufox.multiversion.list_installed", lambda: [mock_inst])

    profile = {
        "id": "prof-cam-config",
        "user_data_dir": str(tmp_path / "p-cam-config"),
        "browser_type": "camoufox",
        "browser_version": "152.0.4",
        "cpu_cores": 8,
        "webgl_vendor": "Apple",
        "webgl_renderer": "Apple M2",
        "canvas_noise": False,
        "audio_noise": False,
        "do_not_track": True,
        "firefox_user_prefs": {
            "custom.test.pref": True,
            "custom.number.pref": 42,
        },
        "extra_launch_args": {
            "camoufox": ["-mute-audio"],
        },
    }
    Path(profile["user_data_dir"]).mkdir(parents=True, exist_ok=True)

    running = await manager.launch(profile)
    assert running.profile_id == "prof-cam-config"

    # Verify Camoufox config
    cfg = captured_options["config"]
    assert cfg["navigator.hardwareConcurrency"] == 8
    assert cfg["webGl:vendor"] == "Apple"
    assert cfg["webGl:renderer"] == "Apple M2"
    assert cfg["canvas:seed"] == 0
    assert cfg["audio:seed"] == 0
    assert cfg["navigator.doNotTrack"] == "1"

    # Verify webgl_config tuple
    assert captured_options["webgl_config"] == ("Apple", "Apple M2")

    # Verify firefox_user_prefs merged
    prefs = captured_options["firefox_user_prefs"]
    assert prefs["custom.test.pref"] is True
    assert prefs["custom.number.pref"] == 42
    assert prefs["privacy.donottrackheader.enabled"] is True

    # Verify CLI args passed
    assert "-mute-audio" in captured_options["args"]

    await manager.stop("prof-cam-config")


@pytest.mark.asyncio
async def test_camoufox_kernel_resolution_and_cdp_none(monkeypatch, tmp_path):
    manager = BrowserManager(NATIVE_RUNTIME)
    monkeypatch.setattr(manager, "is_binary_ready", lambda: True)
    monkeypatch.setattr(manager, "_ensure_camoufox_search_engine", AsyncMock())

    captured_options = {}

    async def mock_camoufox_browser(pw, **kwargs):
        captured_options.update(kwargs)
        mock_ctx = MagicMock()
        mock_ctx.pages = []
        return mock_ctx

    monkeypatch.setattr("camoufox.async_api.AsyncNewBrowser", mock_camoufox_browser)

    mock_pw = MagicMock()
    mock_pw.stop = AsyncMock()

    class MockAsyncPlaywright:
        async def start(self):
            return mock_pw

    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: MockAsyncPlaywright())

    # Mock camoufox multiversion installed versions
    mock_version = MagicMock()
    mock_version.version = "152.0.4"
    mock_version.build = "beta.31"
    mock_version.full_string = "152.0.4-beta.31"

    mock_inst = MagicMock()
    mock_inst.version = mock_version
    mock_inst.path = Path("/mock/camoufox/152.0.4-beta.31")
    mock_inst.is_active = True

    monkeypatch.setattr("camoufox.multiversion.list_installed", lambda: [mock_inst])

    # 1. Profile with leading 'v' prefix
    profile_v = {
        "id": "prof-cam-v",
        "user_data_dir": str(tmp_path / "p-cam-v"),
        "browser_type": "camoufox",
        "browser_version": "v152.0.4-beta.31",
    }
    Path(profile_v["user_data_dir"]).mkdir(parents=True, exist_ok=True)

    running_v = await manager.launch(profile_v)
    assert running_v.profile_id == "prof-cam-v"
    assert running_v.cdp_port == 0
    # Browser option must strip leading 'v'
    assert captured_options["browser"] == "152.0.4-beta.31"
    # CDP URL must be None
    status = manager.get_status("prof-cam-v")
    assert status["cdp_url"] is None
    await manager.stop("prof-cam-v")

    # 2. Profile with nonexistent version falls back to installed Camoufox, NOT Chromium
    profile_unknown = {
        "id": "prof-cam-unknown",
        "user_data_dir": str(tmp_path / "p-cam-unknown"),
        "browser_type": "camoufox",
        "browser_version": "nonexistent-version",
    }
    Path(profile_unknown["user_data_dir"]).mkdir(parents=True, exist_ok=True)

    running_unknown = await manager.launch(profile_unknown)
    assert running_unknown.is_fallback is True
    assert captured_options["browser"] == "152.0.4-beta.31"
    await manager.stop("prof-cam-unknown")


@pytest.mark.asyncio
async def test_camoufox_fingerprint_coherence_screen_fonts_webgl(monkeypatch, tmp_path):
    manager = BrowserManager(NATIVE_RUNTIME)
    monkeypatch.setattr(manager, "is_binary_ready", lambda: True)
    monkeypatch.setattr(manager, "_ensure_camoufox_search_engine", AsyncMock())

    captured_options = {}

    async def mock_camoufox_browser(pw, **kwargs):
        captured_options.update(kwargs)
        mock_ctx = MagicMock()
        mock_ctx.pages = []
        return mock_ctx

    monkeypatch.setattr("camoufox.async_api.AsyncNewBrowser", mock_camoufox_browser)

    mock_pw = MagicMock()
    mock_pw.stop = AsyncMock()

    class MockAsyncPlaywright:
        async def start(self):
            return mock_pw

    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: MockAsyncPlaywright())

    mock_version = MagicMock()
    mock_version.version = "152.0.4"
    mock_version.build = "beta.31"
    mock_version.full_string = "152.0.4-beta.31"
    mock_inst = MagicMock()
    mock_inst.version = mock_version
    mock_inst.path = Path("/mock/camoufox/152.0.4-beta.31")
    mock_inst.is_active = True
    monkeypatch.setattr("camoufox.multiversion.list_installed", lambda: [mock_inst])

    profile = {
        "id": "prof-coherence",
        "user_data_dir": str(tmp_path / "p-coherence"),
        "browser_type": "camoufox",
        "screen_width": 1920,
        "screen_height": 1080,
        "webgl_vendor": "Apple",
        "webgl_renderer": "Apple M1",
    }
    Path(profile["user_data_dir"]).mkdir(parents=True, exist_ok=True)

    running = await manager.launch(profile)
    assert running.profile_id == "prof-coherence"

    cfg = captured_options["config"]

    # 1. Fonts: should NOT be restricted to hardcoded list when not set in profile
    assert "fonts" not in captured_options

    # 2. Screen & Window geometry coherence
    assert cfg["screen.width"] == 1920
    assert cfg["screen.height"] == 1080
    assert cfg["screen.availWidth"] == 1920
    assert cfg["screen.availLeft"] == 0
    assert cfg["screen.availTop"] + cfg["screen.availHeight"] <= cfg["screen.height"]
    assert cfg["window.outerWidth"] <= cfg["screen.availWidth"]
    assert cfg["window.outerHeight"] <= cfg["screen.availHeight"]

    # 3. WebGL parameter anisotropy (must always be 16 to avoid null detection anomaly)
    assert cfg["webGl:parameters"]["34047"] == 16
    assert cfg["webGl2:parameters"]["34047"] == 16

    # 4. Media devices defaults
    assert cfg["mediaDevices:enabled"] is True
    assert cfg["mediaDevices:micros"] == 1
    assert cfg["mediaDevices:webcams"] == 1

    # 5. User-Agent coherence: When user_agent is not explicitly set, do not inject custom UA
    # into cam_config so Camoufox engine generates authentic Firefox headers without path corruption.
    assert "navigator.userAgent" not in cfg
    assert "headers.User-Agent" not in cfg

    await manager.stop("prof-coherence")

    # 6. Verify default profile with None for WebGL vendor/renderer also sets 34047 == 16
    prof_default = {
        "id": "prof-default-webgl",
        "user_data_dir": str(tmp_path / "p-default-webgl"),
        "browser_type": "camoufox",
        "screen_width": 1920,
        "screen_height": 1080,
        "webgl_vendor": None,
        "webgl_renderer": None,
    }
    Path(prof_default["user_data_dir"]).mkdir(parents=True, exist_ok=True)
    running_def = await manager.launch(prof_default)
    cfg_def = captured_options["config"]
    assert cfg_def["webGl:parameters"]["34047"] == 16
    assert cfg_def["webGl2:parameters"]["34047"] == 16
    assert cfg_def["webGl:vendor"] is not None
    assert cfg_def["webGl:renderer"] is not None
    assert "navigator.userAgent" not in cfg_def
    assert "headers.User-Agent" not in cfg_def
    await manager.stop("prof-default-webgl")

    # 7. Custom User-Agent support for Camoufox
    prof_custom_ua = {
        "id": "prof-custom-ua",
        "user_data_dir": str(tmp_path / "p-custom-ua"),
        "browser_type": "camoufox",
        "user_agent": "CustomTestUA/1.0",
    }
    Path(prof_custom_ua["user_data_dir"]).mkdir(parents=True, exist_ok=True)
    await manager.launch(prof_custom_ua)
    cfg_custom = captured_options["config"]
    assert cfg_custom["navigator.userAgent"] == "CustomTestUA/1.0"
    assert cfg_custom["headers.User-Agent"] == "CustomTestUA/1.0"
    await manager.stop("prof-custom-ua")


@pytest.mark.asyncio
async def test_native_downloads_and_playwright_patch(monkeypatch, tmp_path):
    """Verify accept_downloads is set to internal-browser-default and download prefs are properly configured."""
    from backend.browser_manager import _ensure_playwright_internal_download_patch
    # Verify driver patch function runs safely
    _ensure_playwright_internal_download_patch()

    manager = BrowserManager(NATIVE_RUNTIME)
    monkeypatch.setattr(manager, "is_binary_ready", lambda: True)
    monkeypatch.setattr(manager, "_ensure_camoufox_search_engine", AsyncMock())

    captured_options = {}

    async def mock_camoufox_browser(pw, **kwargs):
        captured_options.update(kwargs)
        mock_ctx = MagicMock()
        mock_ctx.pages = []
        return mock_ctx

    monkeypatch.setattr("camoufox.async_api.AsyncNewBrowser", mock_camoufox_browser)

    mock_pw = MagicMock()
    mock_pw.stop = AsyncMock()

    class MockAsyncPlaywright:
        async def start(self):
            return mock_pw

    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: MockAsyncPlaywright())

    mock_version = MagicMock()
    mock_version.version = "152.0.4"
    mock_version.build = "beta.31"
    mock_version.full_string = "152.0.4-beta.31"
    mock_inst = MagicMock()
    mock_inst.version = mock_version
    mock_inst.path = Path("/mock/camoufox/152.0.4-beta.31")
    mock_inst.is_active = True
    monkeypatch.setattr("camoufox.multiversion.list_installed", lambda: [mock_inst])

    profile = {
        "id": "prof-cam-dl",
        "user_data_dir": str(tmp_path / "p-cam-dl"),
        "browser_type": "camoufox",
        "browser_version": "152.0.4",
    }
    Path(profile["user_data_dir"]).mkdir(parents=True, exist_ok=True)

    await manager.launch(profile)
    assert captured_options["accept_downloads"] == "internal-browser-default"
    prefs = captured_options["firefox_user_prefs"]
    assert prefs["browser.download.folderList"] == 2
    assert prefs["browser.download.useDownloadDir"] is True
    assert prefs["browser.download.panel.shown"] is True
    assert prefs["browser.download.alwaysOpenPanel"] is True
    assert prefs["browser.download.autohideButton"] is False
    assert prefs["browser.download.forbid_open_with"] is False
    assert prefs["browser.download.dir"] != ""
    await manager.stop("prof-cam-dl")

    # Verify CloakBrowser launch options accept_downloads
    captured_cloak_options = {}

    async def mock_launch_persistent(**kwargs):
        captured_cloak_options.update(kwargs)
        mock_ctx = MagicMock()
        mock_ctx.pages = []
        return mock_ctx

    monkeypatch.setattr("backend.browser_manager.launch_persistent_context_async", mock_launch_persistent)
    monkeypatch.setattr(manager, "_wait_for_cdp", AsyncMock())
    monkeypatch.setattr(manager, "_reset_cdp_download_behavior", AsyncMock())

    cloak_profile = {
        "id": "prof-cloak-dl",
        "user_data_dir": str(tmp_path / "p-cloak-dl"),
        "browser_type": "cloakbrowser",
        "browser_version": "145",
    }
    Path(cloak_profile["user_data_dir"]).mkdir(parents=True, exist_ok=True)

    await manager.launch(cloak_profile)
    assert captured_cloak_options["accept_downloads"] == "internal-browser-default"
    await manager.stop("prof-cloak-dl")






