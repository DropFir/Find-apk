# Find-APK

输入应用关键词，快速获得安装包、WEBP 图标和开发者信息。

## 工作方式

1. 先搜索开发者官网和 Google Play，确认应用身份与官方入口。
2. 按 `sources.json` 的顺序搜索 APK 下载站；全部没有结果时再公开搜索。
3. 下载一个最佳 APK/XAPK/APKM/APKS 和一个 WEBP 图标，并保存一行开发者名称。
4. 下载需要人工操作或自动下载失败时，创建简短的 `download-note.txt`。
5. 在对话中返回开发者、包名、版本、官网、Google Play、下载来源和本地路径。

同名或近似名称出现多个候选时，Agent 不会暂停询问。它会优先沿用当前任务中已由 Google Play/官网核验的同关键词包名，再依据 Google Play、开发者官网、标题匹配、上架状态和更新时间自动选择证据最完整的应用；最终只需说明自动选择依据。

包名必须从当前可访问的 Google Play 精确页最终 URL 的 `id=` 原样提取，并同时核对标题和开发者。Agent 记忆、自己输入的查询、未打开的旧搜索摘要或历史失败说明都不能证明包名。当前官方页与旧包名冲突时，必须以官方当前 `id=` 重建完整来源计划；包名精确搜索为零但标题应用仍存在时，必须先重新核对身份，不能直接写成所有镜像无候选。

官方包名始终优先；但该包名在全部来源和后备中确实没有可下载文件时，会继续审计同名不同包名候选。标题相同之外还会核对开发者、品牌、图标和用途；符合条件的 `stg`、`beta`、地区版、旧发行包或预发布包可以作为最后回退。下载时使用候选自己的实际包名，文件名添加必要后缀，最终同时列出官方包名、实际包名和候选性质，绝不会把测试包写成官方生产包。付费应用、MOD/破解禁令以及用户明确指定包名的要求不受该回退影响。

通用关键词不会默认选 Android TV。发现同一品牌存在手机、TV 或地区包时，Agent 会先核对标题、开发者、包名、平台和地区；首个包名失效时，还会执行不含既定包名的同名变体审计。`404/410` 等失败只绑定到具体来源、包名和 URL，不能扩展成整个应用或整个来源已删除。用户给出的精确 URL 始终覆盖此前自动选择。

多关键词任务只有在每个关键词都取得安装包、确认付费后跳过，或生成最终下载说明后才算完成。中途汇总只能作为进度，不能把剩余关键词留到用户再次提醒；“按顺序”只影响处理和输出顺序，身份与来源搜索仍按批次执行。

官方当前页面明确显示价格和“购买”，或开发者明确说明是付费/高级版时，该关键词直接记为“付费应用已跳过”并继续下一项。此时不搜索镜像或 `free download`，不尝试 MOD、Unlocked、破解包、Chrome、Cloudflare 或 CDN，也不创建本地目录和下载说明；最终只返回官方购买页面。“包含应用内购买”但可以直接安装的免费应用不算付费。官方当前限时免费且显示“安装”时仍按普通免费应用处理。

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

计划中的每个 `search_url` 必须使用候选解析工具读取，不能只看搜索页标题或探测状态：

```bash
.venv/bin/python tools/extract_search_candidates.py "https://apkpure.com/search?q=Settlemate" --package-name "io.settlemate.app" --timeout 20
```

工具输出 `candidate_found` 后必须立即打开其 `candidate_url` 并验证精确页；在验证完成前不得改用 Chrome 搜索其他来源或创建下载说明。`no_candidates` 只表示这一次完整响应没有包名匹配结果；`generic_search_redirect`、`network_error` 和超时都不能写成“无候选”。

输出只用于本轮批量搜索，不写本地审计文件。查询记录、候选结果、精确页验证和实际下载是四个不同阶段；回复用户时不得混为一谈。
每行最后还会给出受阻时使用的外部限定域名查询。关键词和包名必须分别查询，不能合并成一个同时要求两者出现的查询；两条都完成后才能写“无匹配候选”。

网页搜索/打开工具报“无法打开”、安全 URL 错误、后端网络错误或空响应时，只表示工具层失败，不代表来源无结果。此时先用 `probe_url.py` 复核同一个搜索 URL；若返回 `ok`，必须继续运行 `extract_search_candidates.py`，不能停留在标题检查或改用 Chrome。外部 `site:` 查询批次整体超时且没有返回独立结果时，允许把关键词和包名各自单独重发一次。没有取得可读完整响应的查询状态是“未检查”，不能写成“已查询”或“无匹配候选”。

APKPure 搜索还要核对最终 URL：关键词结果页出现包名匹配的详情页时必须优先打开；包名查询若被重定向到没有 `q` 参数的通用 `/search` 页面，只表示该条站内查询不可用，不得覆盖关键词查询已经发现的候选。

取得精确下载页后，使用一体化工具解析真实链接并立即下载：

```bash
.venv/bin/python tools/download_from_page.py "https://example.com/app/download/apk" "downloads/example_1.2.3.xapk" --package-name "com.example.app" --version "1.2.3" --page-timeout 20 --download-timeout 20 --retries 1
```

默认版本策略是 `prefer-latest`：传入的版本仅作参考，页面实际版本更新时采用更新版；最新版不可下载时允许选择版本最高的可信旧版。用户明确指定版本时才追加 `--version-policy exact`。工具输出 `detected_version` 后，文件名和最终回复都使用该实际版本。

传入 APKPure 精确详情页也可以：如果详情页只包含“Download APK/XAPK”中间入口，工具会自动追加 `/download`、重新解析公开 `d.apkpure.*` 文件链接并继续下载。输出会包含 `transition=apkpure_download_page`。部分应用的详情页会间歇出现 Cloudflare，或旧式 `/download` 路径返回 `404`/`410`，但标准 `d.apkpure.com/b/XAPK|APK/<package>?version=latest` 文件入口仍然有效；对于搜索工具已找到或用户已提供的精确包名 URL，工具会先用 HEAD 核对跳转后的包名、格式、类型和长度，再输出 `transition=apkpure_cdn_fallback` 并直接下载，同时从 CDN 文件名采用实际版本。APKPure 的 `/b/APK/` 入口也可能最终返回 XAPK，所以格式必须由跳转后文件名扩展名和内容类型共同确认，不能把 XAPK 保存成 `.apk`。搜索页已经返回 `candidate_found` 时，后续下载失败不得倒写成“APKPure 没搜到”。只有 `/download` 与 CDN 后备都失败时才允许进入 Chrome 或下一个来源。

APKMirror 的精确变体页也由同一工具处理：程序会自动进入页面内带 `key` 的 `/download/` 中间页，再解析 `/wp-content/themes/APKMirror/download.php` 文件入口并立即下载。输出包含 `transition=apkmirror_download_page`。探测、页面解析和最终入口使用 `tools/http_headers.py` 中统一的浏览器请求身份，避免因 User-Agent 不一致把 Cloudflare `403` 误报为网络超时。

工具输出 `download_link` 后会自动调用下载工具，不再需要手工复制临时签名链接。仅诊断页面且不保存文件时，仍可使用：

```bash
.venv/bin/python tools/extract_download_link.py "https://example.com/app/download/apk" --package-name "com.example.app" --version "1.2.3" --timeout 20
```

APKCombo 只返回“Downloading / Sorry, something went wrong”动态占位页时，工具输出
`classification=browser_required` 和 `pipeline_result=browser_required`。Agent 应自动在真实
Chrome 中打开同一精确页并点击唯一匹配版本，不应要求用户复制临时链接。
同样，Uptodown 的精确公开页对非浏览器客户端返回 `404` 或不下发动态
按钮时，也会返回 `browser_required`，由 Agent 在 Chrome 中自动完成。
APKPure 精确详情页只渲染“Download APK/XAPK”中间入口时，一体化工具会自动进入
`/download` 页并提取 `d.apkpure.*` 公开文件链接；若 `/download` 已失效，还会验证并使用
APKPure 标准 CDN 入口。该确定性转换和 CDN 后备都不再依赖 Agent 或 Chrome。

`download_file.py` 首次 Python 请求遇到 TLS/连接错误时，第二次会自动使用 IPv4 +
HTTP/1.1 的系统 `curl` 从已收到的临时分片续传，以兼容 macOS 下会主动断开
HTTP/2 或大文件超时的 APK CDN，不会降级 HTTPS。50 MiB 及以上的安装包会自动把
传输预算按文件体积提升到 60–900 秒，一体化工具的父进程也会等待完整预算。最终仍因可重试网络
错误失败时，工具会输出 `partial=` 与 `partial_bytes=` 并保留固定隐藏分片；下一次
相同 URL 会从该分片继续，而不是从零开始。

一体化工具会识别 APKCombo 的 `/r2?u=`、`/d?u=` 和普通变体链接。页面只是加载 reCAPTCHA/Turnstile 脚本或隐藏 badge 时不会误报验证码；只有可见验证码容器、iframe 或明确验证文字才返回 `captcha_required`。批量搜索只负责发现候选 URL；不得用批量请求的部分 HTML 或临时正则判断精确页“无直链”。

结果为 `classification=download_link`、`pipeline_result=download_failed` 时，表示链接存在但 Python/curl 下载失败。此时必须改用真实 Chrome 在同一页面点击已确认的唯一版本链接，并用浏览器原生下载一次；不能报告成“无直链”。

下载工具以临时文件下载并原子保存，只重试一次；第一次 Python TLS 连接失败时，第二次自动使用系统 `curl`。它会拒绝 HTML 验证页和不是 ZIP 格式的伪 APK。图标转换脚本保持原尺寸并生成无损 WEBP；来源已经是 WEBP 时直接保存。不要求安装 Android SDK、ADB 或逆向工具。

ZIP 校验通过只代表文件没有损坏，不代表它是可独立安装的单体 APK。`download_file.py` 会额外检查高置信度的缺 split 组合：APK 含 `splits*.xml`，DEX 明确引用 Unity/Cocos/Unreal/Godot 原生引擎，但包内没有任何 `lib/<ABI>/*.so`。命中时会报告 `missing its required ABI split` 并拒绝保存，Agent 必须改下同版本 XAPK/APKM/APKS。完整拆分包应包含 base APK；原生应用还必须包含实际带 `.so` 的 ABI split。

任务重启或目录内已有旧安装包时，Agent 必须先运行 `tools/validate_package.py <local-package>`，不能仅凭文件存在或体积判断已经完成。该工具会复检 APK 的 split 状态，并对 XAPK/APKM/APKS 执行完整外层 ZIP/CRC、内含 APK 以及可识别原生应用的 ABI split 检查；`invalid_package` 会被当作未完成候选。

下载工具会为每个输出路径创建单写入锁，防止两个 Agent 同时写入或重命名同一个隐藏分片。遇到 `another download is already writing target` 时只等待现有传输并验证结果，不能启动第二个进程；检测到并发的成品必须通过完整 ZIP/CRC 检查，否则隔离后由单一进程重下。

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
- 普通公开文件直链默认最多 20 秒；50 MiB 及以上且已核验的安装包按体积使用 60–900 秒独立传输预算，单次命令内只重试一次。
- 第 120 秒停止搜索，开始保存已有结果。
- 每个关键词的搜索和候选验证最多 150 秒；已验证并开始的大文件传输允许在独立的最长 900 秒预算内完成。
- 官方身份查询和独立镜像查询分别批量执行。
- 多关键词任务按“身份、镜像、解析下载”三个阶段批量处理，不逐项串行跑完整流程。
- 相同查询批次不重复提交，直接复用已有结果。
- 找到可下载的最新稳定版立即结束；最新版不可取得时，下载已验证候选中版本最高的可信旧版。用户明确指定版本时仍严格匹配。
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
- APKMirror：没有稳定站内模板，使用 `site:apkmirror.com` 外部查询。
- CNET Download：没有已验证的站内模板，使用 `site:download.cnet.com` 外部查询。

前三个来源均不要求访问首页。首页即使返回 Cloudflare `403`，也不会阻止 Agent 使用搜索页和具体应用页。

详细规则见 `AGENTS.md`。
