# Find-APK

输入应用关键词，快速获得安装包、WEBP 图标和开发者信息。

## 工作方式

1. 先搜索开发者官网和 Google Play，确认应用身份与官方入口。
2. 按 `sources.json` 的顺序搜索 APK 下载站；全部没有结果时再公开搜索。
3. 下载一个最佳 APK/XAPK/APKM/APKS 和一个 WEBP 图标，并保存一行开发者名称。
4. 下载需要人工操作或自动下载失败时，创建简短的 `download-note.txt`。
5. 在对话中返回开发者、包名、版本、官网、Google Play、下载来源和本地路径。

本 Agent 不执行签名取证、安全扫描、安装测试或逆向分析，也不生成报告和校验清单。

运行时只需要网页搜索、HTTP 下载和 Python。

## macOS 快速准备

在仓库根目录运行一次：

```bash
sh tools/setup_macos.sh
```

脚本会在仓库内创建 `.venv`，不会修改 macOS 系统 Python。它优先使用 Homebrew 或用户目录中较新的 Python，并兼容 Apple Silicon、Intel Mac，以及 Command Line Tools 自带的 Python 3.9。后续工具使用 `.venv/bin/python`：

```bash
.venv/bin/python tools/convert_icon.py icon.png icon.webp
```

Python 3.9 会自动安装兼容的 Pillow 11.x；Python 3.10 及以上使用 Pillow 12.x，避免运行中临时降级依赖。

其他系统可以手动创建隔离环境并安装依赖：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Windows 的解释器路径为 `.venv/Scripts/python.exe`。

## 下载公开文件直链

先生成当前应用在所有启用来源中的搜索入口，避免遗漏 APKPure 等优先来源：

```bash
.venv/bin/python tools/build_source_searches.py "Settlemate" --package-name "io.settlemate.app"
```

输出只用于本轮批量搜索，不写本地审计文件。查询记录、候选结果、精确页验证和实际下载是四个不同阶段；回复用户时不得混为一谈。
每行最后还会给出受阻时使用的外部限定域名查询。关键词和包名必须分别查询，不能合并成一个同时要求两者出现的查询；两条都完成后才能写“无匹配候选”。

取得当前版本下载页后，使用一体化工具解析真实链接并立即下载：

```bash
.venv/bin/python tools/download_from_page.py "https://example.com/app/download/apk" "downloads/example_1.2.3.xapk" --package-name "com.example.app" --version "1.2.3" --page-timeout 20 --download-timeout 20 --retries 1
```

工具输出 `download_link` 后会自动调用下载工具，不再需要手工复制临时签名链接。仅诊断页面且不保存文件时，仍可使用：

```bash
.venv/bin/python tools/extract_download_link.py "https://example.com/app/download/apk" --package-name "com.example.app" --version "1.2.3" --timeout 20
```

APKCombo 只返回“Downloading / Sorry, something went wrong”动态占位页时，工具输出
`classification=browser_required` 和 `pipeline_result=browser_required`。Agent 应自动在真实
Chrome 中打开同一精确页并点击唯一匹配版本，不应要求用户复制临时链接。
同样，Uptodown 的精确公开页对非浏览器客户端返回 `404` 或不下发动态
按钮时，也会返回 `browser_required`，由 Agent 在 Chrome 中自动完成。
APKPure 精确详情页只渲染“Download APK/XAPK”中间入口时也使用同一分类，
Agent 会自动进入 `/download` 页并提取 `d.apkpure.*` 公开文件链接。

`download_file.py` 首次 Python 请求遇到 TLS/连接错误时，第二次会自动使用 IPv4 +
HTTP/1.1 的系统 `curl` 从已收到的临时分片续传，以兼容 macOS 下会主动断开
HTTP/2 或大文件超时的 APK CDN，不会降级 HTTPS。

一体化工具会识别 APKCombo 的 `/r2?u=`、`/d?u=` 和普通变体链接。页面只是加载 reCAPTCHA/Turnstile 脚本或隐藏 badge 时不会误报验证码；只有可见验证码容器、iframe 或明确验证文字才返回 `captcha_required`。批量搜索只负责发现候选 URL；不得用批量请求的部分 HTML 或临时正则判断精确页“无直链”。

结果为 `classification=download_link`、`pipeline_result=download_failed` 时，表示链接存在但 Python/curl 下载失败。此时必须改用真实 Chrome 在同一页面点击已确认的唯一版本链接，并用浏览器原生下载一次；不能报告成“无直链”。

下载工具以临时文件下载并原子保存，只重试一次；第一次 Python TLS 连接失败时，第二次自动使用系统 `curl`。它会拒绝 HTML 验证页和不是 ZIP 格式的伪 APK。图标转换脚本保持原尺寸并生成无损 WEBP；来源已经是 WEBP 时直接保存。不要求安装 Android SDK、ADB 或逆向工具。

## 受阻页面快速探测

镜像站出现 Cloudflare、`403`、`404` 或 `410` 时，使用标准库工具快速判断原因：

```bash
.venv/bin/python tools/probe_url.py "https://example.com/app/package.name"
```

工具会使用完整浏览器导航请求头，并返回 `ok`、`cloudflare_challenge`、`gone`、`not_found`、`rate_limited` 或站点错误。它不保存 Cookie，也不需要 Selenium、Playwright 或 `requests`。

优先探测精确应用页，不要用镜像站首页判断整个站点是否可用。`200` 只表示页面可访问；最终安装包响应仍需确认不是 HTML 或验证页。搜索页遇到 Cloudflare 时先用外部 `site:` 查询继续检索，但如果外部查询没有候选或该来源仍是最高优先级，必须执行下述真实 Chrome 优先后备。

### Cloudflare 后备

公开 APK 搜索页、详情页或下载页确认出现 Cloudflare 挑战时，先复用用户当前的真实 Chrome；45 秒内仍受阻或没有可控会话时，再使用 [onlyGuo/Cloudflare-Faker](https://github.com/onlyGuo/Cloudflare-Faker)。这样通常不需要安装额外运行环境，并能直接复用同一浏览器中的验证状态。

Chrome 通过后继续使用同一浏览器会话，不导出或打印 Cookie；仍依赖浏览器验证状态的文件使用 Chrome 原生下载。Cloudflare-Faker 固定版本为 `5b0f2a4759d7b84c36e37afbe5c2e6400706b6c6`，本地放在 `tools/vendor/Cloudflare-Faker/`，不提交到 Git。

Cloudflare-Faker 需要 GUI、Chrome、JDK 24 和开发者模式扩展；缺少前置条件时明确提示，不静默安装系统组件。服务只能监听本机回环地址，不能暴露端口 `8080`。真实 Chrome 与 Cloudflare-Faker 各最多 45 秒、合计最多 75 秒，并计入每关键词 150 秒总时限。二者都失败后才能创建 `download-note.txt`。

## 快速模式

默认时限来自 `sources.json` 的 `searchPolicy`：

- 普通来源操作最多 20 秒；确认 Cloudflare 后使用单独的后备预算，真实 Chrome 与 Cloudflare-Faker 合计最多 75 秒。
- 公开文件直链每次最多 20 秒，只重试一次。
- 第 120 秒停止搜索，开始保存已有结果。
- 每个关键词最多 150 秒。
- 官方身份查询和独立镜像查询分别批量执行。
- 多关键词任务按“身份、镜像、解析下载”三个阶段批量处理，不逐项串行跑完整流程。
- 相同查询批次不重复提交，直接复用已有结果。
- 找到当前版本安装包立即结束；只有旧版本时写入 `download-note.txt` 后结束。
- 普通页面不自动启动可见浏览器；确认是公开 APK 页面上的 Cloudflare 挑战时，必须先复用现有 Chrome，会话仍受阻时再使用 Cloudflare-Faker。

“可见浏览器”是 Agent 控制的真实浏览器窗口。它能执行 JavaScript 并在浏览器内部保留验证状态。普通页面仍遵循快速流程；真实 Chrome 和 Cloudflare-Faker 是确认挑战后的限定例外。

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
sh tools/setup_macos.sh
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
