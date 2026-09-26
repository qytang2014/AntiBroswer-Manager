<p align="center">
  <h1 align="center">AntiBrowser-Manager</h1>
  <p align="center">
    <strong>支持双引擎（Camoufox & CloakBrowser）的自托管防关联指纹浏览器管理面板</strong>
  </p>
  <p align="center">
    <a href="README.md">English</a> | <a href="README_CN.md">简体中文</a>
  </p>
</p>

---

## 项目简介

**AntiBrowser-Manager** 是一个开源的自托管指纹浏览器环境管理面板。它可以在本地（macOS / Windows）或服务器（Linux Docker）上集中管理彼此隔离的浏览器环境（Profile）。每个环境均拥有完全独立的用户数据目录、指纹硬件参数、网络代理以及 Cookie 会话。

本项目同时集成了 **Camoufox**（基于 Firefox 的开源抗检测引擎）与 **CloakBrowser**（基于 Chromium 的指纹混淆引擎），并内置了基于 **sing-box** 的多协议代理导入测速与 S3/WebDAV 端到端加密云备份功能。

## 核心功能

### 1. 双内核引擎支持
- **Camoufox 引擎**：基于 Firefox 的开源抗指纹浏览器内核，支持无限制多开，开箱即用，无需任何商业授权。
- **CloakBrowser 引擎**：基于 Chromium 的深度指纹混淆内核，提供对 Chromium 生态及反指纹测试页面的伪装支持。
- **内核集中管理**：支持在线检测、下载、版本切换与删除，可为不同的 Profile 自由分配对应的浏览器类型与版本号。

### 2. sing-box 代理管理与订阅导入
- **全协议兼容**：直接支持主流现代代理协议，包括 VLESS、VMESS、Trojan、Hysteria2、TUIC、Shadowsocks、WireGuard、AnyTLS、SSH、SOCKS5 与 HTTP。
- **节点导入与订阅分组**：支持单节点链接快速粘贴与订阅链接批量拉取、更新及折叠分组管理。
- **物理网卡测速**：基于 1-RTT 与网卡直连机制进行低延迟测速，避免本地系统全局代理造成的干扰。
- **列表协议徽标**：在侧边栏 Profile 列表中直观标注每个配置所使用的具体代理协议（如 VLESS、SOCKS5、Hysteria2 等）。

### 3. 多重指纹与硬件隔离
- **环境完全隔离**：每个 Profile 拥有独立的存储空间（Cache、Cookie、LocalStorage、IndexedDB 与历史记录），彼此互不交叉。
- **硬件特征配置**：支持自定义 WebGL 厂商与渲染器（Vendor / Renderer）、Canvas 噪点、Audio 噪点、CPU 核心数、内存大小及屏幕分辨率。
- **网络与时区联动**：支持根据代理出口 IP 自动匹配时区、语言（Locale）以及地理位置（GeoIP），防止由于网络出口与系统时区不一致导致的指纹异常。

### 4. 插件与扩展中心
- **双引擎插件适配**：
  - Chromium 引擎：直接支持 Chrome Web Store 扩展在线搜索、一键下载与加载。
  - Firefox (Camoufox) 引擎：集成官方 Firefox Add-ons 市场搜索与批量安装。
- **本地复用**：已下载的扩展保存在本地仓库，可在不同 Profile 间按需勾选关联。

### 5. 云端备份与安全还原
- **标准存储协议**：支持 WebDAV 与 AWS S3 兼容对象存储（如 Cloudflare R2、MinIO、阿里云 OSS 等）。
- **端到端加密（E2EE）**：备份数据在本地完成加密打包后再行上传，密钥文件实施严格的本地权限保护。
- **完整性校验**：内置 SHA-256 完整性校验与流式上传下载，支持断点重试与实时进度反馈。

### 6. 自动化与跨平台视图
- **原生独立窗口**：Windows 与 macOS 支持在原生桌面窗口中直接启动和操作各个浏览器实例。
- **容器与 Web 视图**：Linux 环境下通过 Docker + KasmVNC 即可在 Web 界面中直接查看与操作远程浏览器。
- **CDP 自动化接口**：运行中的 CloakBrowser (Chromium) Profile 提供独立的 Chrome DevTools Protocol (CDP) 端点，支持无缝接入 Playwright 或 Puppeteer 进行自动化控制（注：Camoufox 基于 Firefox，不支持 Chromium CDP 接口）。

## 快速上手

### 系统要求
- **macOS / Windows**：Python 3.10+，Node.js 18+
- **Linux (Docker)**：Docker 20.10+，Docker Compose

### 方式一：源码一键运行（推荐日常使用与调试）

1. **克隆仓库**：
   ```bash
   git clone https://github.com/your-username/AntiBrowser-Manager.git
   cd AntiBrowser-Manager
   ```

2. **启动服务**：
   * **macOS**：
     ```bash
     ./run-macos.sh
     ```
   * **Windows**：
     ```bat
     run-windows.bat
     ```

   启动脚本会自动初始化 Python 虚拟环境、使用 `uv` 安装所需依赖、编译前端 UI，并在本地启动管理面板。

3. **打开面板**：
   启动完成后，浏览器访问：
   ```text
   http://127.0.0.1:52341
   ```

### 方式二：手动开发模式

**后端（Python）**：
```bash
# 推荐使用 uv 管理虚拟环境
uv sync
uv run python run.py
```

**前端（React + Vite）**：
```bash
cd frontend
npm install
npm run dev
```

### 方式三：编译为原生桌面应用 (macOS / Windows)

如果希望打包成无需依赖系统 Python / Node 环境的独立桌面软件（打包产物位于 `dist_native/`）：

* **macOS (.app / .dmg)**：
  ```bash
  ./packaging/build_macos.sh
  ```
  > **说明**：打包脚本会自动完成前端静态构建与 Python 后端冻结，并在 `dist_native/` 下生成 `.dmg` 安装镜像。若初次打开未签名的应用提示已损坏或无法验证，可在终端执行 `xattr -rc /Applications/AntiBrowser-Manager.app`，或在 **系统设置 → 隐私与安全性** 中点击“仍要打开”。

* **Windows (.exe / 安装包)**：
  ```powershell
  powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
  ```
  > **说明**：脚本将自动调用 PyInstaller 与 Inno Setup（如已安装），在 `dist_native\` 下生成便携 `.exe` 或 `AntiBrowser-Manager-Setup.exe` 安装包。若 Windows SmartScreen 提示拦截，点击“更多信息 → 仍要运行”即可。

### 方式四：Docker 部署 (Linux 服务器)

```bash
docker compose up --build -d
```
服务将在容器中启动并通过 Web 端口（默认 8080）提供控制面板与 VNC 视图。

## 浏览器引擎说明

- **Camoufox 引擎**：开源项目（遵循 GPL-3.0 协议），在 AntiBrowser-Manager 中可以直接下载使用，无并发多开数量限制，不需要任何授权 Key。
- **CloakBrowser 引擎**：若需使用基于 Chromium 的 CloakBrowser 内核，需在系统设置中填入相应的 CloakBrowser License Key。

## CDP 自动化接入说明

> [!NOTE]
> **适用范围**：CDP（Chrome DevTools Protocol）调试端点**仅适用于 CloakBrowser (Chromium) 引擎**。
> **Camoufox 说明**：Camoufox 基于 Firefox (Gecko) 内核构建，底层不兼容 Chromium 的标准 CDP 接口。若需要对 Camoufox 进行自动化操作，建议直接在 Python 脚本中调用官方 `camoufox` 库独立使用。

当启动某个基于 **CloakBrowser** 的 Profile 后，控制面板会显示该环境的独立 CDP 调试端点。可以直接使用 Playwright 接入进行自动化操作：

```python
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        # 仅适用于 CloakBrowser 引擎环境，将 PROFILE_ID 替换为实际的环境 ID
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:52341/api/profiles/<PROFILE_ID>/cdp")
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://browserleaks.com/ip")
        print("Page Title:", await page.title())

asyncio.run(main())
```

## 技术架构

- **后端**：Python 3.10+ / FastAPI / Uvicorn / SQLite / sing-box
- **前端**：React / TypeScript / Tailwind CSS / Lucide Icons / Vite
- **浏览器引擎**：[Camoufox](https://github.com/daijro/camoufox) (Firefox) & [CloakBrowser](https://github.com/CloakHQ/CloakBrowser) (Chromium)
- **桌面与视窗**：macOS / Windows 原生窗口；Linux noVNC / KasmVNC

## 鸣谢 (Acknowledgements)

AntiBrowser-Manager 的实现与演进离不开以下优秀的开源项目与底层技术，特此致谢：

- [CloakBrowser-Manager](https://github.com/CloakHQ/CloakBrowser-Manager) & [CloakBrowser](https://github.com/CloakHQ/CloakBrowser)：本项目最初源自 CloakBrowser-Manager，感谢原作者团队在 Chromium 防关联与自托管架构上的杰出探索。
- [Camoufox](https://github.com/daijro/camoufox)：由 [daijro](https://github.com/daijro) 开发的开源定制版 Firefox 反指纹浏览器，为本项目提供了强大的免授权防指纹内核支持。
- [sing-box](https://github.com/SagerNet/sing-box)：通用代理网络核心平台，为本项目的高速代理路由与节点测速提供了强有力的底层保障。

## 开源协议 (License)

- 本仓库管理面板代码采用 [MIT License](LICENSE) 授权开源。
- 第三方浏览器内核（CloakBrowser / Camoufox）与代理核心（sing-box）遵循各自的开源协议或官方授权声明。
