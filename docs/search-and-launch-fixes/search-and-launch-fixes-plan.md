# 搜索引擎设置与多实例启动冲突修复实施方案

## 1. 背景与目标
【功能名称】search-and-launch-fixes
【背景】
用户反馈了两个问题：
1. 预设搜索引擎（如百度）的 URL 中缺少 `ie={inputEncoding}` 参数。同时，对于 CloakBrowser，设置除 Google 外的预设引擎（如 Bing）时未生效，启动后默认变成了 360 搜索。
2. 在已启动 CloakBrowser 的情况下，再启动 Camoufox 配置文件时，系统弹出了“AntiBrowser-Manager 已在运行中，请查看 Dock 或已打开的窗口”的 macOS 多实例冲突提示。

【目标】
- 完善搜索引擎预设 URL，补充编码参数。
- 修复中文版 Chromium 下因为名称不匹配导致无法自动设置为默认搜索引擎的问题。
- 解决在启动 Camoufox 内核时错误触发主程序（AntiBrowser-Manager）多实例检测提示的问题。

【核心功能点】
- 更新预设引擎（Baidu）的 URL 以包含正确的字符编码参数。
- 增强 Playwright 操作 `chrome://settings/searchEngines` 的脚本鲁棒性，通过行内容匹配替代单纯的 `aria-label` 匹配。
- 在 `app_entry.py` 入口点增加环境变量和启动参数的检测，防止子进程（如 Playwright 启动 node）意外触发多实例弹窗。

【边界】
- 不涉及浏览器内核下载逻辑的调整。
- 不影响正常的单一实例应用启动和监听端口逻辑。

【关键假设】
- 搜索引擎无法设置默认的问题是由于中文 Chromium 界面中元素的 `aria-label` 发生变化导致的匹配失败。
- 多实例错误提示是由于 macOS 在 PyInstaller 打包环境下，Playwright 创建子进程时环境继承导致主入口脚本被唤醒。

## 2. 需求分析
### 2.1 功能需求
- 修复 ProfileForm 中的百度搜索引擎链接。
- 修改 `browser_manager.py` 中的 `make_default_js`，增强设置默认搜索引擎的识别率。
- 在 `app_entry.py` 中绕过由 Playwright 子进程带来的二次启动检测。

### 2.2 非功能需求
- 保持界面交互流畅。
- 后台兼容现有逻辑，不产生副作用。

## 3. 技术方案
### 3.1 预设搜索引擎修改
在 `ProfileForm.tsx` 中，将百度的 URL `https://www.baidu.com/s?wd=%s` 修改为 `https://www.baidu.com/s?ie={inputEncoding}&wd=%s`。

### 3.2 搜索引擎自动配置鲁棒性增强
修改 `browser_manager.py` 中的 Playwright 评估脚本。由于 Chromium 汉化版中，“Bing”可能显示为“必应”，原来的 `label.includes('{name}')` 会失效。新逻辑改为向上遍历找到整行的 `SETTINGS-SEARCH-ENGINE-ENTRY` 或 `TR`，并通过 `textContent` 匹配 `{keyword}`（如 `bing.com`），确保无论界面语言是什么，都能精准点击对应搜索引擎的“更多操作”菜单。

### 3.3 子进程启动拦截隔离
在 `app_entry.py` 的 `_resolve_server_port` 流程中，增加检查机制。若 `sys.argv` 包含浏览器特有参数（如 `-no-remote`, `--type=renderer`），或 `os.environ` 包含 Playwright 特有环境变量（如 `PW_LANG_NAME`），则静默退出，不再弹出系统通知。这阻止了子进程引起的误报。

## 4. 实施计划
| 任务 | 描述 | 优先级 | 预估复杂度 | 状态 |
|------|------|--------|-----------|------|
| 1 | 修复 Baidu URL 模板 | P0 | S | 已完成 |
| 2 | 重构搜索引擎选择脚本 | P0 | S | 已完成 |
| 3 | 拦截 PyInstaller 子进程多实例弹窗 | P0 | S | 已完成 |

## 5. 风险与应对
| 风险 | 影响 | 概率 | 应对措施 |
|------|------|------|---------|
| Chromium 界面结构变更 | 无法设置默认引擎 | 中 | 已采用兼容 `TR` 和 `SETTINGS-SEARCH-ENGINE-ENTRY` 的向上遍历方式，兼容性极高。 |

## 6. 验收标准
- [x] 在前端创建配置时，百度的链接带有 `ie={inputEncoding}`。
- [x] 设置 Bing 为默认引擎时，启动的浏览器默认搜索即为 Bing，不再是 360 搜索。
- [x] 先启动 CloakBrowser，然后再启动 Camoufox 时，系统不再弹出“AntiBrowser-Manager 已在运行中”的错误通知。
