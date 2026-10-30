# 环境安装与换设备说明

## 先选择用法

| 用法 | 本机需要什么 | 是否调用 GPT | 适合情况 |
| --- | --- | --- | --- |
| GitHub 云端免模型版 | 浏览器和 GitHub 登录 | 否 | 手机、平板、新电脑、不想安装环境 |
| 本机免模型版（默认） | Python 3.10+；Windows / macOS / Linux | 否 | 自动下载、规则筛选、Google 摘要翻译与原文对照 |
| 本机模型版（手动选择） | Windows、Python、Codex 登录及可用额度 | 是 | 需要中文综合分析和论文证据核验 |

免模型版不调用 GPT/Codex，不需要 GPT 账号或模型 API Key。默认尝试用无需密钥的非官方 Google 网页翻译接口生成中文摘要，标题和作者原始摘要也会保留；这不能替代模型式精读，评分仅作相关性和阅读线索排序。

## 方案一：只有浏览器也能用

1. 打开本仓库的 [Actions 页面](https://github.com/sez956/-sez/actions)。
2. 选择 **Free embodied AI digest**。若 GitHub 提示需要启用 Actions，按页面提示启用；Fork 出来的仓库也可能需要手动启用定时任务。
3. 点击 **Run workflow** 手动运行，等待完成。以后按 `01:00 UTC`（北京时间 09:00）计划执行。
4. 打开该次运行的 **Summary**，直接阅读带论文链接的日报；也可在 **Artifacts** 下载 `embodied-digest-运行编号`，解压后打开 `latest.html`。

云端无需本机开机、Python、Codex 或密钥。它会使用 GitHub Actions 运行与存储资源，是否计费取决于仓库和账户套餐，不等同于无限免费。任务只请求仓库读取权限，不向源码分支回写日报。

GitHub 定时运行可能排队延迟，不能保证 09:00 准时完成；公开仓库长期没有活动时定时任务可能被 GitHub 暂停。报告产物配置保留 30 天，需登录并拥有相应仓库访问权限才能下载。云端结果在 Actions 页面查看，不会弹出你电脑的本地通知。

近 30 天去重记录通过 Actions 缓存延续；缓存若被清理，会重新以最近 7 天建立候选列表。云端历史与各台本机独立。多设备/本机与云端共享出口时，请错开手动运行，遵守 arXiv 总体限频要求。

## 方案二：Windows 本机

### 1. 下载源码

在仓库点击 **Code → Download ZIP** 并解压，或使用 Git 克隆。解压到长期使用的文件夹，不要直接在 ZIP 内运行。

### 2. 安装 Python

如果尚未安装 Python，从 [Python 官网](https://www.python.org/downloads/)安装 Python 3.10 或更高版本。可使用官网提供的 Python install manager；安装后打开新终端确认以下任一命令正常：

```powershell
python --version
py -3 --version
```

自动安装入口不会替你在系统中下载并安装 Python。若检测不到，会显示官方下载地址；没有安装软件权限时，可直接用方案一。

### 3. 双击三个入口

1. `安装环境.cmd`：查找 Python，创建本目录的 `.venv`，检查版本、目录写入权限及 arXiv 网络连接。
2. `立即汇总.cmd`：运行免模型版，成功后打开 `最新日报.html` 阅读。
3. `安装定时任务.cmd`：安装或切换为每天北京时间 09:00 的免模型任务。

只有 Python 标准库，无需安装任何 pip 包。`requirements.txt` 仅说明无第三方依赖；`.venv` 使用 `--without-pip` 创建，也不需要联网下载包。计划任务记录实际的 Python 路径，避免另一台机器的用户名和安装目录不同导致失效。

任务名：`EmbodiedAI-Daily-0900`。安装脚本将触发时间明确设为 `+08:00`；电脑需开机、联网、当前 Windows 账户登录。错过触发时间后补跑，失败每 15 分钟重试，最多 2 次。可用暂停、恢复入口管理。

### 手动命令

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\bootstrap.ps1 -NetworkCheck
.\.venv\Scripts\python.exe .\free_digest.py
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install_schedule.ps1 -Engine free
```

只有明确希望使用 GPT 时，双击 `模型版汇总.cmd`。如需把定时任务切回模型版：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install_schedule.ps1 -Engine model
```

## 方案三：macOS / Linux

免模型脚本可跨平台使用；系统需先有 Python 3.10+。Windows 的 `.cmd`、PowerShell 通知和任务计划不适用。

```bash
python3 --version
python3 -m venv --without-pip .venv
.venv/bin/python check_environment.py --network
.venv/bin/python free_digest.py --quiet
```

可用 cron 或系统自带调度工具运行。下面示例假设系统时区已经设为 `Asia/Shanghai`，请将两个绝对路径替换成实际目录：

```cron
0 9 * * * cd /absolute/path/to/repository && /absolute/path/to/repository/.venv/bin/python free_digest.py --quiet >> /absolute/path/to/repository/outputs/cron.log 2>&1
```

系统时区不是北京时间时，需要自行换算；不能只把 `TZ` 写进命令就认定调度时间也改变。使用 cron 前先手动成功运行一次，确保 `outputs` 目录已创建。

## 输出、配置与换设备

- `outputs/free/latest.html`、`latest.md`：免模型最新日报；默认运行时也更新根目录 `最新日报.html`。
- `outputs/free/reports/`：历次 HTML、Markdown、JSON。
- `outputs/free/status.json`：免模型运行状态与错误原因。
- `outputs/free/history.json`：免模型近 30 天的已报道记录。
- `outputs/free/translation_cache.json`：完整成功译文的缓存；云端也通过独立缓存延续。
- 旧模型版的 `日报/`、`日志/`、`运行状态.json` 保持独立。

在 `config.free.json` 调整 `max_items`（1–20）、`min_score`（相关性阈值）和检索词。正文、摘要和备注中的线索按公开的 `RULES` 权重计分；这不能客观证明论文的重要性。默认回看最近 7 天以补漏，旧摘要和备注未改变时不重复报道，版本更新也会标注未核对全文差异。

换设备时下载源码后重新运行环境安装入口，**不要直接复制 `.venv`**。若需要延续免模型去重历史，可单独复制 `outputs/free/history.json`；登录信息和 Python 环境不随仓库迁移。移动文件夹后，也应重建 `.venv` 并重新安装定时任务。

## 网络与常见问题

### Google 摘要翻译

`config.free.json` 的 `translation.enabled` 默认为 `true`，目标为简体中文（`zh-CN`）。仅将入选论文的公开摘要发到 `translate.googleapis.com`，不传登录凭据，不使用 GPT 或 Google Cloud 密钥，不安装额外包。若不希望发送摘要，将 `enabled` 设为 `false`。

接入的是**非官方网页接口**，不是具有稳定服务承诺的 Google Cloud Translation API；不能保证永久可用或无限使用。Google Cloud 正式接口有其免费额度、配置和计费规则，本工具不会自动切到该付费接口。

长摘要自动按句段拆分，完整译文成功后缓存，原始摘要始终保留。遇到 403/429、连接失败或异常响应，本轮停止后续翻译请求，已有缓存仍可使用；不更换出口或接口来绕过限制。失败条目显示原因并提供 Google 手动翻译入口，长摘要可复制原文过去翻译。

只补翻译最近一期已生成日报，不重新抓取或改变已报道历史：

```powershell
.\.venv\Scripts\python.exe .\free_digest.py --translate-latest --quiet
```

macOS/Linux 使用 `.venv/bin/python free_digest.py --translate-latest --quiet`。该命令也适合接口恢复后重试。`--force` 只代表重新执行筛选，仍会跳过已报道论文，因此补翻译时应使用 `--translate-latest`。

| 现象 | 处理 |
| --- | --- |
| 找不到 Python / 打开 Microsoft Store | 安装官网 Python，重新开终端；再次运行 `安装环境.cmd` |
| 复制后解释器路径失效 | 删除该项目内的 `.venv`，重新运行环境安装入口 |
| `venv` 不可用（部分 Linux 发行版） | 安装系统发行版提供的 `python3-venv` 支持，或改用云端 |
| 全部来源连接失败 | 先检查网络；在终端运行环境检查的 `--network`；查看 `outputs/free/status.json` |
| API 失败但 RSS 成功 | 报告显示覆盖受限；RSS 只能保证公告窗口，不保证完整最近 7 天 |
| 今天再次运行被跳过 | 使用 `--force`；双击入口已带该参数。历史去重仍然生效 |
| 不弹通知 | 检查 Windows 通知/勿扰设置；直接打开 `latest.html`，macOS/Linux/云端无此通知 |
| 中文摘要显示翻译失败 | 查看条目错误；接口限流时稍后用 `--translate-latest` 重试，或点击手动翻译入口；日报原文仍可阅读 |
| 想要深入的重要度判断和证据核验 | Google 翻译只转换语言；需要人工精读或明确选择消耗额度的模型版 |

如网络需要代理，可把 `config.free.json` 中的 `proxy` 改为本机实际地址，例如 `http://127.0.0.1:7897`；**端口因设备而异，不要直接照搬示例**。也支持 `DIGEST_PROXY` 环境变量；配置为空时使用 Python 的系统/环境代理设置。云端通常保持为空。

不要把带账号密码的代理地址提交到仓库。对于定时任务，配置文件中的本机代理地址更容易保持一致；任务仍要求代理程序在执行时可用。脚本按至少 3.2 秒间隔串行访问 arXiv，遇到限制按规则重试。

参考：[Python Windows 安装说明](https://docs.python.org/3/using/windows.html)、[arXiv API 手册](https://info.arxiv.org/help/api/user-manual.html)、[arXiv RSS](https://info.arxiv.org/help/rss.html)、[arXiv 使用与限频规则](https://info.arxiv.org/help/api/tou.html)、[GitHub 定时事件说明](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)、[Google 网页翻译库对稳定性的说明](https://py-googletrans.readthedocs.io/en/latest/#note-on-library-usage)、[Google Cloud 正式翻译接口计费](https://cloud.google.com/products/translate/pricing)。
