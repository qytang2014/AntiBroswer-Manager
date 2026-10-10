# Changelog

All notable changes to AntiBrowser-Manager are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.6] - 2026-10-09

### Added
- **Dual-engine architecture: Camoufox (Firefox) joins CloakBrowser (Chromium).** Profiles can now run on either the Chromium-based CloakBrowser engine or the Firefox-based Camoufox engine, each with isolated downloads, version catalogs, and fingerprinting. Includes a kernel manager modal with resumable downloads, per-profile kernel version selection, separate extension and profile handling for Camoufox, Firefox add-ons search with a popular list, and engine-tabbed settings.
- **Encrypted cloud backup & restore.** Back up profiles and app settings to WebDAV or S3-compatible storage with end-to-end encryption and integrity verification. Streaming transfers with in-place progress and a global progress banner, SSE keepalive pings, hardened secret-file permissions (0o600), portable archives that auto-realign paths on restore, and no more macOS keychain blocking prompts thanks to a local master key.
- **Proxy & subscription management center.** Central proxy manager with subscription support, sing-box powered routing (AnyTLS, TUIC, Hysteria2, HTTP/SOCKS5 and more), fast node speed testing, collapsible subscription groups, manual node editing, and direct native probing for standard proxies.
- **Extension manager.** Top-bar manager with profile multi-select, webstore search and resumable downloads with progress feedback, proxy-aware webstore requests, update checking, and per-profile GeoIP matching.
- **Multiple license management** with dynamic profile binding; the configured license now syncs with the kernel manager and unlocks Pro downloads.
- **Dynamic port allocation and single-instance upgrade**, plus a sidebar access badge for the running instance.
- **Chinese README** (README_CN) covering dual-engine features, sing-box proxying, and acknowledgements.

### Changed
- **Renamed to AntiBrowser-Manager** across the UI (previously CloakBrowser Manager).
- **Build tooling migrated to uv** for dependency and build management.
- **Profile form revamp**: cleaner layout, custom select component, hardware fingerprint controls, and WebGL vendor/renderer support.
- **Chromium/kernel downloads decoupled from startup** into a kernel manager modal with resumable progress.
- **Docker image adapted for the dual-engine architecture** (release workflow updated, container port aligned to 52341).

### Fixed
- **Stealth & anti-detection**: `--enable-automation` is now ignored to remove the infobar, Camoufox bot score reduced, WebRTC/timezone leaks plugged on proxy profiles, and native WebAuthn disabled in Camoufox to prevent a macOS API deadlock.
- **Camoufox stability**: version conflicts, `properties.json` launch errors, user-agent path corruption, session loss / auto-stop issues, and kernel version resolution.
- **Proxy reliability**: sing-box pipe deadlock, NAT timeouts, DNS timeouts on standard proxies, orphan sing-box process cleanup, and license seat failover.
- **Backup robustness**: timeouts and UI freezing on failure, stuck progress reporting, hardcoded paths decoupled from archives with auto-realign on restore, and extension selections now persist across backup/restore.
- **Packaging**: PyInstaller child-process stability, multiprocessing popup bug on Windows, and Camoufox bundling fixes.
- **CI**: hermetic GeoIP fallback test to stop flaky failures; Ubuntu/Windows CI fixes.

## [0.1.5] - 2026-08-30

### Fixed
- **Profiles failed to launch on some Windows systems with a "Failed to launch browser" error.** On a Windows console using a non-Unicode (legacy) codepage, a status message printed while fetching the stealth binary could abort every launch. This build bundles the updated CloakBrowser engine (0.5.10), which makes that output safe so the launch always proceeds.

## [0.1.4] - 2026-08-21

### Fixed
- **Memory leak when a browser closed on its own.** If a browser exited outside the Stop button (a crash, or closing Chrome from inside the profile window), a helper process was left running and holding around 130 MB. These built up over time on a long-running manager. The manager now releases it on that path as well.

### Added
- **License and seat limits now surface in a banner.** When a profile fails to launch because the plan's concurrent-session limit is reached or the license key is invalid, the Manager shows a dismissible top banner with an Upgrade link instead of failing silently.
- **Automated multi-architecture Docker releases.** Version tags now build Linux AMD64 and ARM64 images on native GitHub-hosted runners, combine them under one Docker tag, and publish both the release version and `latest` alongside the Windows and macOS installers.

### Changed
- **Safer release validation.** Docker architecture digests, provenance, and the combined manifest are validated before publication, and `latest` is promoted only from a complete verified release. Release tags are validated as canonical semantic versions, and workflow dependencies are pinned to immutable revisions.

## [0.1.3] - 2026-08-19

### Fixed
- **macOS app failed to launch profiles on a fresh machine.** On a Mac that had never run CloakBrowser before, launching a profile with a license key set could fail with an internal library-loading error while the app fetched the stealth binary. The macOS build now bundles a self-contained TLS library, so the download works on a clean machine and profiles launch as expected. (Intel and Apple Silicon.)

### Changed
- **Dropped a redundant browser launch flag.** The Manager no longer passes an extra Chromium flag at launch; the CloakBrowser engine already handles that behavior internally, so the flag added nothing.

## [0.1.2] - 2026-08-19

### Fixed
- **First launch on a fresh Windows machine no longer fails.** The packaged app has no console, so a status message printed during the first stealth-binary download could abort the launch on some systems. Startup output is now handled safely and the launch proceeds.

### Added
- **Update notification.** When a newer Manager release is available, a dismissible banner appears at the top of the app; clicking Download opens the release page in your default browser. The check is fail-soft and cached, so it never delays or interferes with normal use.
- **Richer diagnostics in `manager.log`.** Startup now records a one-line environment fingerprint (app version, OS, architecture, packaged-vs-source, license tier/plan, binary version, data directory). Uncaught errors from any background thread or task, and each profile launch's context (with proxy credentials redacted), are now logged with full detail, and output from the underlying CloakBrowser engine is mirrored into the log. This makes crash reports diagnosable from the log alone.

## [0.1.1] - 2026-08-19

### Added
- **Restore previous tabs on launch.** Each profile can reopen the tabs that were open when it was last stopped. Enabled by default; toggle it off per profile in the Behavior section.
- **Clone / duplicate a profile.** Copy an existing profile's full configuration and fingerprint into a fresh profile with its own `user_data_dir`, ready to launch independently.
- **Proxy test button.** Test a profile's proxy from the form and see the exit IP, geolocation, and latency before launching.
- **Last-browser-screenshot preview.** The profile shows a preview image captured from its last browser session.
- **Drag-and-drop reordering** of the profile list.
- **Profile reset.** Wipe a profile's browser state and re-roll its fingerprint in one action.
- **Transient confirmation on form buttons.** Save and Reset now show an inline "Saved" / "Reset done" confirmation.

### Changed
- README: restored the "Browser Profile Manager" headline and tightened the tagline.

## [0.1.0] - 2026-08-19

### Added
- **Native desktop app for macOS and Windows.** Installers bundle the Manager and stealth Chromium binary into a single application, so end users no longer need Python, Node, git, or a build step. Runs the browser directly on the host while the existing Linux Docker/KasmVNC server mode is preserved. Run-from-source (`run.py`) stays available for developers. The builds are unsigned for now — on first launch macOS needs a one-time Gatekeeper approval and Windows a SmartScreen click-through (see the README).
- **Standalone application window.** The native app now opens in its own dedicated window (WKWebView on macOS, WebView2 on Windows) carrying the app icon, instead of a tab in your default browser. The window remembers its size and position between launches, and closing it cleanly stops the server and all running browsers. Relaunching the app focuses the existing window instead of starting a second copy. Both the packaged app and `run.py` share the same window code path.
- **In-app Settings panel.** A gear-icon panel lets you set the CloakBrowser Pro license key and release channel from inside the app; changes are hot-applied with no restart.
- **CloakBrowser Pro licensing wired app-wide.** A license key and release channel configured once (native Settings, or a `.env` for server mode) are passed to every profile launch so the Pro stealth binary is used. The binary is resolved and pre-downloaded at startup, keeping it off the launch path.
- **License tier and binary-version status badge** in the top bar, reporting the active tier and the real Chromium binary version.
- **Keyless empty-state prompt.** When no license key is set, the empty view shows a "No license key set" call-to-action with links to enter a key, get a free key, or view Pro plans, instead of the generic "Select a profile" text.
- **Quit / Power control.** A Power button cleanly stops the server and all running browsers and exits; the shutdown endpoint is same-origin (CSRF) guarded so no website can trigger it.
- **Unauthenticated `/api/health` probe** returning only `{"status": "ok"}` with no system details, for health checks.
- **Third-party cookie compatibility control** per profile (defaults on for new profiles).
- **Google set as the default search engine** for new profiles on first launch, with an opt-out toggle.
- GeoIP enabled by default for new profiles.

### Changed
- **`/api/status` now requires authentication.** It previously leaked running-session count, binary version, and profile totals to unauthenticated scanners; health checks now use the new `/api/health` probe instead.
- **Simplified profile configuration.** Removed obsolete override fields and moved unrestricted Chromium arguments under an Advanced section. Existing profiles are migrated automatically to the new schema.
- **Clipboard sync is now limited to the Linux VNC mode.** Clipboard controls are hidden and injection is skipped in the native macOS and Windows apps.
- Per-profile clipboard preferences are now persisted.

### Fixed
- Native launcher readiness poll now targets `/api/health`, fixing a startup hang where the app never opened the browser when an auth token was set.
