# Find-APK

输入应用关键词，快速获得安装包、WEBP 图标和开发者信息。

## 工作方式

1. 先搜索开发者官网和 Google Play，确认应用身份与官方入口。
2. 按 `sources.json` 的顺序搜索 APK 下载站；全部没有结果时再公开搜索。
3. 下载一个最佳 APK/XAPK/APKM/APKS 和一个 WEBP 图标，并保存一行开发者名称。
4. 下载需要人工操作或自动下载失败时，创建简短的 `download-note.txt`。
5. 在对话中返回开发者、包名、版本、官网、Google Play、下载来源和本地路径。

本 Agent 不执行签名取证、安全扫描、安装测试或逆向分析，也不生成报告和校验清单。

运行时只需要网页搜索、HTTP 下载和 Python。在 `Find-apk` 目录中安装图标转换依赖：

```bash
python -m pip install -r requirements.txt
```

macOS 没有 `python` 命令时使用 `python3`。转换图标：

```bash
python tools/convert_icon.py icon.png icon.webp
```

脚本保持原尺寸并生成无损 WEBP。来源已经是 WEBP 时直接保存。不要求安装 Android SDK、ADB 或逆向工具。

## 受阻页面快速探测

镜像站出现 Cloudflare、`403`、`404` 或 `410` 时，使用标准库工具快速判断原因：

```bash
python tools/probe_url.py "https://example.com/app/package.name"
```

macOS 没有 `python` 命令时使用 `python3`。工具会使用完整浏览器导航请求头，并返回 `ok`、`cloudflare_challenge`、`gone`、`not_found`、`rate_limited` 或站点错误。它不保存 Cookie，也不需要 Selenium、Playwright 或 `requests`。

优先探测精确应用页，不要用镜像站首页判断整个站点是否可用。`200` 只表示页面可访问；最终安装包响应仍需确认不是 HTML 或验证页。搜索页遇到 Cloudflare 时立即改用外部 `site:` 查询，不自动启动浏览器。

## 快速模式

默认时限来自 `sources.json` 的 `searchPolicy`：

- 每个来源最多 20 秒。
- 第 120 秒停止搜索，开始保存已有结果。
- 每个关键词最多 150 秒。
- 官方身份查询和独立镜像查询分别批量执行。
- 找到当前版本安装包立即结束；只有旧版本时写入 `download-note.txt` 后结束。
- 默认禁止自动启动可见浏览器。只有用户明确要求浏览器尝试，并且已有精确当前版本下载页时才使用。

“可见浏览器”是 Agent 控制的真实浏览器窗口。它能执行 JavaScript 和保留临时 Cookie，但启动、Cloudflare 等待和人工验证都可能显著增加耗时，因此不属于默认快速搜索流程。

## 迁移到另一台电脑

Agent 的长期行为已经保存在 `AGENTS.md`、`sources.json`、README、`requirements.txt` 和 `tools/` 中，不依赖当前对话历史。

### 当前电脑

提交后将仓库推送到私人 Git 远程：

```bash
git remote add origin <PRIVATE_REPOSITORY_URL>
git push -u origin main
```

如果已经配置 `origin`，只需运行 `git push`。不使用远程仓库时，也可以复制整个 `Find-apk` 目录；不要只复制 `AGENTS.md`。

### Windows 新电脑

```powershell
git clone <PRIVATE_REPOSITORY_URL> Find-apk
Set-Location Find-apk
python -m pip install -r requirements.txt
```

### macOS 新电脑

```bash
git clone <PRIVATE_REPOSITORY_URL> Find-apk
cd Find-apk
python3 -m pip install -r requirements.txt
```

然后在 Codex 中直接打开 `Find-apk` 目录，新建任务并发送：

```text
请完整读取 AGENTS.md、sources.json 和 README.md，检查 requirements.txt 与 tools/，只回复“已准备好”。
```

收到“已准备好”后即可逐个发送应用关键词。`downloads/` 是本地结果目录，不会进入 Git；需要迁移旧 APK 和图标时应单独复制该目录。

## 本地文件

```text
downloads/YYYY-MM-DD/<keyword-folder>/
  <apk-stem>_<version>.<apk|xapk|apkm|apks>
  <apk-stem>_<version>.webp
  developer.txt
  download-note.txt  # 仅下载受阻时存在
```

例如关键词 `DTA Connect` 使用 `downloads/YYYY-MM-DD/dta-connect/`。`developer.txt` 使用 UTF-8 编码，内容只放开发者名称。`download-note.txt` 最多四行，只说明人工下载原因与入口，不作为报告。

`downloads/` 不会进入 Git。目录名、文本换行和相对路径均兼容 Windows 与 macOS。

## 调整优先网站

编辑 `sources.json` 的 `preferredSources`。数组顺序就是搜索优先级；`enabled: false` 表示暂时跳过该网站。

来源可以只提供旧式 `url`，也可以分别配置：

- `baseUrl`：来源域名和相对链接基准。
- `searchUrlTemplate`：站内搜索地址，使用 `{query}` 表示 URL 编码后的关键词。
- `searchMode: externalSiteQuery`：没有已验证站内入口时，明确使用外部 `site:` 查询。
- `homepageRequired`：为 `false` 时按搜索模板或搜索模式执行，不访问首页。

当前搜索方式：

- APKPure：`https://apkpure.com/search?q={query}`。
- APKPac Canada：`https://ca.apkpac.com/search?q={query}`。
- APKCombo：`https://apkcombo.com/search?q={query}`，站点可能重定向到 `/search/<slug>`。
- CNET Download：没有已验证的站内模板，使用 `site:download.cnet.com` 外部查询。

前三个来源均不要求访问首页。首页即使返回 Cloudflare `403`，也不会阻止 Agent 使用搜索页和具体应用页。

详细规则见 `AGENTS.md`。
