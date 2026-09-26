<p align="center">
  <h1 align="center">AntiBrowser-Manager</h1>
  <p align="center">
    <strong>Self-hosted anti-detect browser profile manager supporting dual engines (Camoufox & CloakBrowser)</strong>
  </p>
  <p align="center">
    <a href="README.md">English</a> | <a href="README_CN.md">简体中文</a>
  </p>
</p>

---

## Overview

**AntiBrowser-Manager** is an open-source, self-hosted management panel for anti-detect browser profiles. It lets you run isolated browser environments locally (macOS / Windows) or on a server (Linux Docker). Each profile maintains its own dedicated user data directory, fingerprint hardware configuration, network proxy, and cookie storage.

The project natively integrates both **Camoufox** (an open-source anti-detect engine based on Firefox) and **CloakBrowser** (a stealth engine based on Chromium). It also features built-in multi-protocol proxy management and speed testing powered by **sing-box**, alongside end-to-end encrypted (E2EE) cloud backups via S3 / WebDAV.

## Key Features

### 1. Dual Engine Support
- **Camoufox Engine**: Open-source anti-detect browser based on Firefox. Completely free, supports unlimited concurrent profiles out-of-the-box, and requires no commercial license.
- **CloakBrowser Engine**: Stealth engine based on Chromium, providing patched Chromium identity spoofing.
- **Centralized Kernel Management**: Download, switch, and delete multiple engine versions directly within the interface. Assign specific engines and versions to each profile.

### 2. sing-box Proxy & Subscription Management
- **Modern Protocol Support**: Parses and manages proxy protocols natively, including VLESS, VMESS, Trojan, Hysteria2, TUIC, Shadowsocks, WireGuard, AnyTLS, SSH, SOCKS5, and HTTP.
- **Node & Subscription Import**: Import single node links or batch-sync subscription URLs with collapsible group management.
- **Physical Interface Latency Test**: Low-latency 1-RTT connectivity testing bound directly to the active network interface, preventing interference from local system proxies.
- **Protocol Badges**: The profile sidebar displays the exact proxy protocol badge (e.g., `VLESS`, `SOCKS5`, `Hysteria2`) for instant clarity.

### 3. Fingerprint & Hardware Isolation
- **Strict Data Isolation**: Every profile operates in a separate data directory (Cache, Cookies, LocalStorage, IndexedDB, and History).
- **Hardware Configuration**: Customizable WebGL Vendor & Renderer, Canvas noise, Audio noise, CPU core count, RAM allocation, and display resolutions.
- **GeoIP & Timezone Sync**: Automatically aligns browser timezone, language (Locale), and geolocation with the proxy exit IP to prevent fingerprint inconsistencies.

### 4. Extension & Add-on Management
- **Dual-Engine Extensions**:
  - Chromium engine: Search, download, and load extensions directly from the Chrome Web Store.
  - Firefox (Camoufox) engine: Search and install add-ons directly from the official Firefox Add-ons directory.
- **Local Repository**: Downloaded extensions are cached locally and can be bound across multiple profiles with a click.

### 5. Encrypted Cloud Backup & Restore
- **Standard Storage Providers**: Supports WebDAV and AWS S3-compatible object storage (e.g., Cloudflare R2, MinIO, Alibaba Cloud OSS).
- **End-to-End Encryption (E2EE)**: Archives are encrypted on your local machine before upload. Credentials are stored securely with restricted file permissions.
- **Integrity Verification**: Built-in SHA-256 verification, streaming uploads/downloads, and real-time progress indicators.

### 6. Automation & Cross-Platform Viewers
- **Native Desktop Windows**: Launches browser profiles directly in native desktop windows on Windows and macOS.
- **Web VNC Viewer**: Linux / Docker environments provide embedded browser interaction through KasmVNC / noVNC inside the web interface.
- **CDP Automation Endpoint**: Running CloakBrowser (Chromium) profiles expose a Chrome DevTools Protocol (CDP) endpoint for Playwright / Puppeteer automation (Note: Camoufox is Firefox-based and does not support Chromium CDP).

## Quick Start

### Requirements
- **macOS / Windows**: Python 3.10+, Node.js 18+
- **Linux (Docker)**: Docker 20.10+, Docker Compose

### Option 1: One-Click Run from Source (Recommended for Daily Use)

1. **Clone the repository**:
   ```bash
   git clone https://github.com/your-username/AntiBrowser-Manager.git
   cd AntiBrowser-Manager
   ```

2. **Launch the application**:
   * **macOS**:
     ```bash
     ./run-macos.sh
     ```
   * **Windows**:
     ```bat
     run-windows.bat
     ```

   The script initializes a Python virtual environment, installs dependencies using `uv`, builds the frontend UI, and starts the local server.

3. **Open the panel**:
   Once started, visit:
   ```text
   http://127.0.0.1:52341
   ```

### Option 2: Development Mode

**Backend (Python)**:
```bash
# Recommended with uv
uv sync
uv run python run.py
```

**Frontend (React + Vite)**:
```bash
cd frontend
npm install
npm run dev
```

### Option 3: Build as Native Desktop Application (macOS / Windows)

You can compile standalone desktop packages that do not require pre-installed Python or Node environments. Outputs are generated in `dist_native/`:

* **macOS (.app / .dmg)**:
  ```bash
  ./packaging/build_macos.sh
  ```
  > **Note**: The build script bundles the frontend and freezes the backend, producing a `.dmg` installer inside `dist_native/`. If macOS warns about an unsigned application on first launch, run `xattr -rc /Applications/AntiBrowser-Manager.app` in Terminal, or approve it under **System Settings → Privacy & Security → Open Anyway**.

* **Windows (.exe / Setup installer)**:
  ```powershell
  powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
  ```
  > **Note**: Uses PyInstaller and Inno Setup (if installed) to generate `AntiBrowser-Manager-Setup.exe` inside `dist_native\`. If Windows SmartScreen displays a warning, click **More info → Run anyway**.

### Option 4: Docker Deployment (Linux Server)

```bash
docker compose up --build -d
```
The manager runs inside the container and serves the web UI and VNC viewer.

## Engine & License Notes

- **Camoufox Engine**: Open-source (GPL-3.0). Can be downloaded and used directly inside AntiBrowser-Manager with no concurrency limits and no license key required.
- **CloakBrowser Engine**: If you choose to launch profiles using the CloakBrowser Chromium binary, enter your CloakBrowser license key in Settings.

## CDP Automation

> [!NOTE]
> **Scope**: CDP (Chrome DevTools Protocol) debugging endpoints are **only available for CloakBrowser (Chromium) profiles**.
> **Camoufox Note**: Camoufox is based on the Firefox (Gecko) engine and does not implement Chromium's CDP protocol. To automate Camoufox, use the `camoufox` Python package directly in your scripts.

When a **CloakBrowser** profile is running, its dedicated CDP endpoint is accessible for Playwright automation:

```python
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        # Only for CloakBrowser profiles; replace <PROFILE_ID> with the running profile ID
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:52341/api/profiles/<PROFILE_ID>/cdp")
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://browserleaks.com/ip")
        print("Page Title:", await page.title())

asyncio.run(main())
```

## Tech Stack

- **Backend**: Python 3.10+ / FastAPI / Uvicorn / SQLite / sing-box
- **Frontend**: React / TypeScript / Tailwind CSS / Lucide Icons / Vite
- **Browser Engines**: [Camoufox](https://github.com/daijro/camoufox) (Firefox) & [CloakBrowser](https://github.com/CloakHQ/CloakBrowser) (Chromium)
- **Window Viewers**: Native desktop windows on Windows/macOS; noVNC / KasmVNC on Linux Docker

## Acknowledgements

AntiBrowser-Manager is built upon and inspired by the work of the following projects:

- [CloakBrowser-Manager](https://github.com/CloakHQ/CloakBrowser-Manager) & [CloakBrowser](https://github.com/CloakHQ/CloakBrowser): This project originated as a fork of CloakBrowser-Manager. We appreciate the CloakHQ team's foundational design of the self-hosted profile architecture.
- [Camoufox](https://github.com/daijro/camoufox): Created by [daijro](https://github.com/daijro), providing an outstanding open-source anti-detect Firefox browser engine.
- [sing-box](https://github.com/SagerNet/sing-box): The universal proxy platform powering our network routing, subscription handling, and low-latency testing.

## License

- The management panel source code is licensed under the [MIT License](LICENSE).
- Third-party browser binaries and components (CloakBrowser, Camoufox, sing-box) are subject to their respective open-source licenses or official terms.
