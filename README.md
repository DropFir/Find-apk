# Find-APK

输入应用关键词，快速获得安装包、WEBP 图标和开发者信息。

## 工作方式

1. 先搜索开发者官网和 Google Play，确认应用身份与官方入口。
2. 按 `sources.json` 的顺序搜索 APK 下载站；全部没有结果时再公开搜索。
3. 下载一个最佳 APK/XAPK/APKM/APKS 和一个 WEBP 图标，并保存一行开发者名称。
4. 下载暂时受阻时可创建简短的 `download-note.txt` 记录进度，但继续处理，不能把它当作完成。
5. 在对话中返回开发者、包名、版本、官网、Google Play、下载来源和本地路径。

同名或近似名称出现多个候选时，Agent 不会暂停询问。它会优先沿用当前任务中已由 Google Play/官网核验的同关键词包名，再依据 Google Play、开发者官网、标题匹配、上架状态和更新时间自动选择证据最完整的应用；最终只需说明自动选择依据。

包名必须从当前可访问的 Google Play 精确页最终 URL 的 `id=` 原样提取，并同时核对标题和开发者。Agent 记忆、自己输入的查询、未打开的旧搜索摘要或历史失败说明都不能证明包名。当前官方页与旧包名冲突时，必须以官方当前 `id=` 重建完整来源计划；包名精确搜索为零但标题应用仍存在时，必须先重新核对身份，不能直接写成所有镜像无候选。

官方包名始终优先；但该包名在全部来源和后备中确实没有可下载文件时，会继续审计同名不同包名候选。标题相同之外还会核对开发者、品牌、图标和用途；符合条件的 `stg`、`beta`、地区版、旧发行包或预发布包可以作为最后回退。下载时使用候选自己的实际包名，文件名添加必要后缀，最终同时列出官方包名、实际包名和候选性质，绝不会把测试包写成官方生产包。付费应用、MOD/破解禁令以及用户明确指定包名的要求不受该回退影响。

通用关键词不会默认选 Android TV。发现同一品牌存在手机、TV 或地区包时，Agent 会先核对标题、开发者、包名、平台和地区；首个包名失效时，还会执行不含既定包名的同名变体审计。`404/410` 等失败只绑定到具体来源、包名和 URL，不能扩展成整个应用或整个来源已删除。用户给出的精确 URL 始终覆盖此前自动选择。

多关键词任务只有在每个关键词都取得安装包，或确认付费后跳过才算完成。下载说明只是进度检查点。中途汇总只能作为进度，不能把剩余关键词留到用户再次提醒；“按顺序”只影响处理和输出顺序，身份与来源搜索仍按批次执行。

用户要求下载时，单个关键词只有“安装包保存并验证成功”或“官方确认付费后跳过”才算完成。无候选、网络超时、Cloudflare、浏览器限制和 `download-note.txt` 都只是处理中状态；Agent 会继续换格式、可信旧版本、同名不同包名候选及后备来源。单轮搜索时间到只结束该轮，不会发送失败终稿或等待用户再次提醒。多关键词任务会在批次末尾重新处理未完成队列。

大批量任务采用固定轮转队列：先批量确认身份和来源候选，下载阶段按用户原始顺序让每个未完成关键词各获得一次新的有效尝试；单项仍失败时移到轮末，不能连续多轮重复同一 URL。恢复任务时会重新验证已有安装包，并依据原始列表重建未完成队列；空目录、下载说明、旧失败回复或临时 `blocked` 状态都不会被当作完成。单轮边界只会留下包含未完成顺序和下一动作的进度检查点，由后续继续机制自动续跑。

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

ZIP 校验通过只代表文件没有损坏，不代表它是可独立安装的单体 APK。`download_file.py` 会读取二进制 `AndroidManifest.xml`：APK 声明 `requiredSplitTypes` 或 `com.android.vending.splits.required=true` 时，会直接判定它是缺少必要配置分包的 App Bundle base APK，并拒绝保存；旧的 `splits*.xml`、原生引擎标记与缺少 `.so` 的高置信度检查仍然保留。完整 XAPK/APKM/APKS 除了包含 base APK，还必须包含 Manifest 指定的 ABI、屏幕密度等必要分包；原生应用的 ABI split 还必须实际带有 `.so`。

任务重启或目录内已有旧安装包时，Agent 必须先运行 `tools/validate_package.py <local-package>`，不能仅凭文件存在或体积判断已经完成。该工具会复检 APK Manifest 的强制 split 声明，并对 XAPK/APKM/APKS 执行完整外层 ZIP/CRC、内含 APK、Manifest 指定的 ABI/屏幕密度分包以及可识别原生应用的 ABI split 检查；`invalid_package` 会被当作未完成候选。

下载工具会为每个输出路径创建单写入锁，防止两个 Agent 同时写入或重命名同一个隐藏分片。遇到 `another download is already writing target` 时只等待现有传输并验证结果，不能启动第二个进程；检测到并发的成品必须通过完整 ZIP/CRC 检查，否则隔离后由单一进程重下。

### MI9 完整拆分包后备

全部首选来源与可信公开搜索没有可下载完整包时，来源计划会追加 `MI9 APK Downloader` 的 `browser_generator`。Agent 在一个复用的 Chrome 工作标签页中输入已确认包名，只生成一次，并核对结果页上的标题、开发者、包名和实际版本。MI9 结果页或 Aptoide 的公开 AAB 元数据列出 base APK 与所有配置 split 时，不再只保存 base APK，而是把全部 `downloads.androidcontents.com` 或 `pool.apk.aptoide.com` 组件链接交给：

```bash
.venv/bin/python tools/download_split_archive.py "downloads/example_1.2.3.xapk" --package-name "com.example.app" --app-name "Example" --version "1.2.3" --split-url "<base-url>" --split-url "<config-url>" --split-url "<remaining-config-url>" --timeout 20 --retries 1
```

工具逐个验证 APK 组件、生成 XAPK `manifest.json`、原子保存并执行完整拆分包检查。只出现 base、组件 URL 的包名或域名不符、缺少 ABI split 都不会作为成功。

### 完整交付复检

安装包通过 `validate_package.py` 只代表包本身可作为候选，不代表关键词目录交付完整。安装包、清晰 WEBP 图标和只含开发者名称的 `developer.txt` 全部写入后，必须运行：

```bash
.venv/bin/python tools/validate_delivery.py "downloads/YYYY-MM-DD/<keyword-folder>"
```

只有输出 `classification=valid_delivery` 才能把关键词计为完成或写入最终汇总。缺图标、缺开发者文件或只有 `download-note.txt` 的目录仍是未完成状态。

### Chrome 标签管理

连接 Chrome 后先记录任务开始时已有的标签页 ID；这些用户标签绝不关闭，也不用于下载。整批任务只复用一个 Agent 工作标签页，必要时最多再开一个官方核对页；Agent、页面脚本、弹窗或点击在任务开始后产生的标签都计入 Agent 标签，硬上限为两个。

每次导航、点击、搜索提交或 MI9 `Generate` 后立即检查新标签。只有当前关键词/包名、当前来源计划域名、Google Play/开发者官网和下载工具允许的文件 CDN 页面可以保留；任何广告、购物、博彩、通知订阅、安装器推广、无关搜索结果或其他非关键词标签都立即关闭，不读取正文、不点击。若无关页面占用当前工作标签，则直接关闭该工作标签并用一个干净标签重新打开原目标，不能在广告页返回、刷新或继续交互。

`sources.json.browserSessionPolicy.blockedDomains` 保存永久浏览器域名黑名单。`playafterdark.com`、它的广告跳转域名 `iccku.com` 及其子域已列入黑名单；MI9 等页面弹出这些域名时立即关闭，不读取、不点击、不再次访问，也不因关闭广告而重复提交同一次生成请求。

页面用完立即关闭 Agent 自己创建的重复搜索页、错误页和空白页，任务结束关闭全部 Agent 任务标签。扩展断线只重连一次，重连期间不继续开标签；仍失败就切换 Cloudflare-Faker、MI9 公开组件或下一个来源。公开页面的常规后备不逐项询问用户，遇到需要人工验证码的页面直接换来源。

## 受阻页面快速探测

镜像站出现 Cloudflare、`403`、`404` 或 `410` 时，使用标准库工具快速判断原因：

```bash
.venv/bin/python tools/probe_url.py "https://example.com/app/package.name"
```

工具会使用完整浏览器导航请求头，并返回 `ok`、`cloudflare_challenge`、`gone`、`not_found`、`rate_limited` 或站点错误。它不保存 Cookie，也不需要 Selenium、Playwright 或 `requests`。

优先探测精确应用页，不要用镜像站首页判断整个站点是否可用。`200` 只表示页面可访问；最终安装包响应仍需确认不是 HTML 或验证页。搜索页遇到 Cloudflare 时先用外部 `site:` 查询继续检索，但如果外部查询没有候选或该来源仍是最高优先级，必须执行下述真实 Chrome 优先后备。

### Cloudflare 后备

公开 APK 搜索页、详情页或下载页确认出现 Cloudflare 挑战时，先复用用户当前的真实 Chrome；浏览器控制必须明确选择扩展连接的真实 Chrome 会话，不能由 URL 自动选择到内置或隔离浏览器。45 秒内仍受阻或没有可控会话时，再使用 [onlyGuo/Cloudflare-Faker](https://github.com/onlyGuo/Cloudflare-Faker)。

Chrome 通过后继续使用同一浏览器会话，不导出或打印 Cookie；仍依赖浏览器验证状态的文件使用 Chrome 原生下载。Cloudflare-Faker 固定版本为 `5b0f2a4759d7b84c36e37afbe5c2e6400706b6c6`，本地放在 `tools/vendor/Cloudflare-Faker/`，不提交到 Git。

Cloudflare-Faker 需要 GUI、Chrome、JDK 24 和开发者模式扩展；缺少前置条件时明确提示，不静默安装系统组件。macOS 配置完成后使用 `sh tools/cloudflare_faker.sh start` 启动、`sh tools/cloudflare_faker.sh check` 检查本机服务与扩展的实际执行能力，只有显示 `Chrome extension is connected and executable` 才算可用；`sh tools/cloudflare_faker.sh stop` 用于停止。搜索页通过 `extract_search_candidates.py ... --cloudflare-faker --faker-timeout 45` 重试，精确页通过 `download_from_page.py ... --cloudflare-faker --faker-timeout 45` 重试。工具使用 `remote-html`，不会调用受 Chrome CSP 限制的 `remote-script`。扩展目录可由 `sh tools/cloudflare_faker.sh extension-path` 输出。该辅助脚本当前仅支持 macOS，并会强制服务只监听本机 `127.0.0.1:8080`；其他系统按上游说明手动启动并保持相同的回环限制。真实 Chrome 与 Cloudflare-Faker 各最多 45 秒、合计最多 75 秒，并计入每关键词 150 秒总时限。Chrome 标题为 `Error` 时仍要读取正文；明确的 404/410 页面按精确页失效处理，不能误报成网络超时或 Cloudflare。二者都失败后才能创建 `download-note.txt`。

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

例如关键词 `DTA Connect` 使用 `downloads/YYYY-MM-DD/dta-connect/`。`developer.txt` 使用 UTF-8 编码，内容只放开发者名称。`download-note.txt` 最多四行，只说明自动下载待续跑的原因与精确入口，不作为报告，也不要求用户接管。

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
- MI9 APK Downloader：只在首选来源耗尽后按已确认包名生成一次；读取结果页公开 split 链接并由 `download_split_archive.py` 合成 XAPK。

前三个来源均不要求访问首页。首页即使返回 Cloudflare `403`，也不会阻止 Agent 使用搜索页和具体应用页。

详细规则见 `AGENTS.md`。
