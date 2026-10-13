# dehydrater v0.1 计划书：CLI 功能验证版

## 1. 目标

用一个命令行工具，把**一节课的录像或录音（加上可选的 PDF 课件）**处理成三份 Markdown：

| 产物 | 内容 |
| --- | --- |
| `raw.md` | 原始逐字稿：语音识别原文，每句带时间戳 |
| `dehydrated.md` | 脱水逐字稿：删去口癖、重复、闲聊，修正识别错误，合并成自然段，每段带时间戳 |
| `notes.md` | 课堂笔记：以课件为主线、融入老师讲解的完整笔记，含概览、课堂通知、术语表；讲解内容标注录音时间 |

本阶段要回答的问题：

1. 中英混杂的课堂录音，火山 ASR 的准确率够不够用？
2. 脱水时会不会删掉有用信息？
3. 笔记能不能代替听课用来复习？课堂通知能不能抓全？
4. 处理一节课要花多少钱、多长时间？

## 2. 约束

- **不在本地跑任何模型**：ASR 和 LLM 全部走 API，本地只做解码这类 CPU 工作。
- 只做 CLI，交互保持最简单。
- 一次只处理一节课，输入是一个带音轨的音视频文件（录像或录音，任意常见格式），加上零到多份 PDF 课件。
- 代码可读性优先：分层清晰，有类型，可测试。

## 3. API

测试阶段统一使用**火山引擎**，ASR 和 LLM 是两个产品，分别开通：

| 用途 | 服务 | 说明 |
| --- | --- | --- |
| ASR | **豆包语音**：录音文件识别标准版，默认 2.0（`volc.seedasr.auc`，0.8 元/小时），1.0（`volc.bigasr.auc`，2.3 元/小时）备用 | 返回毫秒级分句时间戳，提交任务后轮询结果。文档只列出音频 URL，但**实测 `audio.data` 内联 base64 可用**，无需对象存储。录音上传完后服务端要一两分钟才响应提交请求，因此开启 TCP keepalive，网络错误自动重试 |
| LLM | **火山方舟**：脱水用 `doubao-seed-2-1-lite`，大纲和笔记用 `doubao-seed-2-1-pro` | 兼容 OpenAI 接口。豆包模型**默认开启深度思考**，实测一句话的回答要 40 秒、1900 个推理 token；接入地址为方舟时程序自动关闭 |

每个任务的接入地址、模型、API Key 都可单独配置（见 §8）。

## 4. 处理流程

```text
录像/录音 ──► extract_audio ──► transcribe ──┬──► render_raw ──────────► raw.md
                                             │
                                             └──► dehydrate ──┬──► render_dehydrated ──► dehydrated.md
                                                              │
课件 PDF ──► ingest_slides ───────────────────────────────────┴──► outline ──► write_notes ──► render_notes ──► notes.md
```

| 阶段 | 输入 → 输出 | 实现要点 |
| --- | --- | --- |
| `extract_audio` | 录像或录音 → 16kHz 单声道 MP3（32kbps） | PyAV 解码，任何带音轨的格式都可以（mp4、ts、mkv、m4a、wav……）。2 小时约 29MB |
| `ingest_slides` | PDF → 每页文字 | PyMuPDF。没有课件时输出空课件，下游退化为只按讲课内容组织 |
| `transcribe` | 音频 → `Transcript`（原始分句） | 火山 ASR，分句时间戳精确到毫秒 |
| `dehydrate` | 原始分句 → `Transcript`（自然段） | 按约 2500 字分块并发调用 LLM，把口语讲解精炼改写为书面文字，保留全部信息点（实测压到原文的 24%）。**模型只返回"第几句到第几句合并成一段"，时间戳由原始分句推出**。脱水后字数不在原文 15%～60% 之间时告警 |
| `outline` | 课件 + 脱水稿 → `Outline` | 一次调用：以课件结构为主线分章，每章给出课件页码范围和对应的讲课段落（相当于由模型完成"讲解对齐到课件"，能处理跳讲、回翻、课件外插叙）；同时生成概览、术语、课堂通知。少于 90% 的段落被分配时要求模型重做 |
| `write_notes` | 每章的课件页 + 讲课段落 → 笔记正文 | 按章并发。直接输出 Markdown，来自讲解的内容用 `[@段落编号]` 标注，程序换成录音时间 |
| `render_*` | 结构化产物 → Markdown | Jinja2 模板。改排版不需要重新调用 LLM；每份输出各一个阶段，产出后立即可读 |

LLM 的输出都经过校验（JSON 用 pydantic，Markdown 检查引用编号和标题层级），不合格时把错误告诉模型，最多重试 3 次（`pipeline/structured.py`）。JSON 输出开启服务端 JSON 模式。

## 5. 数据模型

所有模型都用 pydantic 定义，按概念分文件放在 `domain/` 下，完整定义以代码为准。

```python
class Lecture:            # lecture.toml 的内容
    title: str
    date: date            # 上课日期
    recording: SourceFile # 录像或录音；大小和修改时间参与缓存键
    slides: SourceFile | None

class Transcript:
    segments: list[TranscriptSegment]   # start、end（秒）、text
    # 原始逐字稿中一个 segment 是一句话；脱水稿中是一个自然段

class Outline:
    overview: str
    chapters: list[OutlineChapter]      # title、pages（课件页码范围或 None）、paragraphs（段落范围列表）
    key_terms: list[Term]
    notices: list[Notice]               # text、at（秒）

class LectureNotes:
    overview: str
    chapters: list[NoteChapter]         # title、pages、start（秒）、body（Markdown）
    key_terms: list[Term]
    notices: list[Notice]
```

## 6. 代码结构

```text
dehydrater/
├── pyproject.toml                # 依赖、ruff、basedpyright、import-linter 配置
├── flake.nix                     # devShell
├── .github/workflows/ci.yml      # 三平台：格式、lint、类型、分层、测试
├── src/dehydrater/
│   ├── domain/                   # 数据模型与纯函数（timecode、chunking）
│   ├── ports.py                  # AudioExtractor, SlideReader, Transcriber, ChatModel
│   ├── adapters/
│   │   ├── audio_pyav.py
│   │   ├── slides_pymupdf.py
│   │   ├── asr_volcengine.py     # 豆包语音（私有协议）
│   │   └── llm_openai_compat.py  # 火山方舟等兼容 OpenAI 的 LLM
│   ├── pipeline/
│   │   ├── artifacts.py          # 阶段之间传递的产物清单
│   │   ├── workspace.py          # 目录布局、lecture.toml、产物读写
│   │   ├── stage.py              # Stage 基类与 StageContext
│   │   ├── cache.py              # 阶段级缓存
│   │   ├── memo.py               # 块级缓存：阶段内每次 LLM 调用各自落盘
│   │   ├── structured.py         # LLM 输出 → 校验 → 不合格重试
│   │   ├── templating.py         # Jinja2 模板加载与摘要
│   │   ├── runner.py             # 按顺序执行、跳过缓存、汇报事件
│   │   ├── events.py
│   │   ├── lecture.py            # 一节课的处理入口
│   │   └── stages/               # 每个阶段一个文件
│   ├── prompts/*.j2              # LLM 提示词，只放文本
│   ├── templates/*.md.j2         # Markdown 输出模板
│   ├── config.py                 # 各任务的地址、模型、Key 及查找顺序
│   ├── bootstrap.py              # 组合根：读配置，构造 adapters，注入各阶段
│   ├── service.py                # 整理一节课的应用流程（CLI 与将来的 UI 共用）
│   └── cli/                      # 交互式与脚本式命令行
└── tests/
    ├── unit/                     # domain、config、模板，不访问网络
    ├── pipeline/                 # 调度、缓存；用预设回复的假模型测 LLM 阶段
    └── adapters/                 # 合成音频；模拟 HTTP 服务
```

**分层规则**（import-linter 强制，见 `pyproject.toml`）：

```text
cli → service → bootstrap → config → pipeline | adapters → ports → domain
```

- 上层可以依赖下层，反之不行；`pipeline` 与 `adapters` 互不依赖。
- `domain`、`ports`、`pipeline` 不得 import `av`、`pymupdf`、`openai`、`httpx`。

**编码约定**：basedpyright strict；依赖一律构造函数注入，无全局状态；第三方库的类型不越出 adapter；提示词写在 `.j2` 文件里。

## 7. 工作区与缓存

```text
输出目录/
├── lecture.toml        # 课堂名称、日期、录音与课件路径（用户可编辑）
├── notes.md  dehydrated.md  raw.md
└── cache/
    ├── audio.mp3       # 提取的音频
    ├── dehydrater.log  # 这节课的整理日志
    ├── artifacts/      # 各阶段产物（JSON）
    ├── stages/         # 各阶段缓存元数据：缓存键、耗时、token 用量
    └── <阶段名>/       # 阶段自己的中间文件：dehydrate/chunks、write_notes/chapters
```

日志：命令行入口配置 `logging`，模块各自 `logging.getLogger(__name__)`。整理日志写到 `cache/dehydrater.log`，全局日志写到用户日志目录（轮转）。httpx/httpcore 的 DEBUG 日志一并记录，用于排查网络问题；不记录 API Key（已用真实运行的日志核对过）。

- 缓存键 = `sha256(阶段名, 版本号, 输入产物的摘要, 模型与参数, 提示词模板的摘要)`。改提示词只重跑下游 LLM 阶段，不会重新转写。
- 脱水按块、笔记按章缓存：中断后再执行，只补齐没完成的部分；强制重跑时，内容和参数都没变的块直接复用。
- 修改阶段的后处理逻辑（不涉及提示词和模型）时，把该阶段的 `version` 加一即可让产物重新生成，块级缓存仍然有效，不会重复调用模型。
- 三份 `.md` 每次运行都会覆盖。需要手改的话，请先复制一份。

## 8. CLI 与配置

完整用法见 [docs/usage.md](usage.md)。

```bash
dehydrater --help       # 简短的使用说明
dehydrater setup        # 交互式设置，验证连通性，帮用户保存（shell 启动文件 / 配置目录 / 只显示片段）
dehydrater              # 交互式整理：课堂名称、课堂资料（一个录音 + 零到多个 PDF）、输出路径
dehydrater process -n 名称 -i 录音 -i 课件.pdf -o 输出目录 [--date] [--redo 步骤]   # 脚本用
dehydrater status 输出目录
dehydrater check        # 检查设置完整性与连通性
```

**配置**：四个任务（`transcribe`、`dehydrate`、`outline`、`write_notes`）各有接入地址、模型、API Key 三项，变量名为 `DEHYDRATER_<任务>_{URL,MODEL,KEY}`。查找顺序：环境变量 → 当前目录向上的 `.env` → 用户配置目录下的 `env` → 内置默认值（只有地址和模型有）。地址为方舟时自动关闭深度思考。`.env.example` 有逐项说明。

**命令行代码结构**：`cli/` 只负责交互和显示（`app.py` 命令定义、`lecture.py` 整理流程、`setup.py` 设置向导、`display.py` 进度界面、`shell_profile.py` 写入 shell 启动文件、`prompts.py` 输入与路径补全）；整理流程本身在 `service.py`，将来的 UI 复用它。面向用户的"步骤"与内部阶段的对应关系在 `pipeline/steps.py`。

## 9. 依赖

| 用途 | 库 |
| --- | --- |
| 工程 | uv、ruff、basedpyright、import-linter、pytest、pytest-asyncio |
| 数据与配置 | pydantic、platformdirs、python-dotenv |
| 媒体与文档 | av（PyAV，wheel 自带 FFmpeg）、pymupdf（AGPL，因此本项目为 AGPL-3.0） |
| API | openai（兼容 OpenAI 的大模型服务，自带重试）、httpx（火山 ASR） |
| 模板与 CLI | jinja2、typer、rich、prompt_toolkit（交互输入与路径补全） |

## 10. 步骤

| 步骤 | 内容 | 完成标准 |
| --- | --- | --- |
| **S0** 骨架 ✅ | 项目结构、工具链、CI | 测试和类型检查全部通过 |
| **S1** 转写 ✅ | 音频抽取（兼容录像与录音）、火山 ASR、`raw.md` | 一节真实的课得到原始逐字稿 |
| **S2** 脱水与笔记 ✅ | `dehydrate`、课件读取、`outline`、`write_notes`、三份模板 | 一节真实的课端到端产出三份 Markdown |
| **S3** 收尾 ✅ | 交互式与脚本式 CLI、设置向导、日志、按步骤统计耗时与 token、三平台 CI、在多门课程上验证 | 逐条回答 §1 的四个问题 |

### §1 的结论

1. **ASR 准确率**：豆包录音文件识别 2.0 对中英混杂的课堂录音效果良好，`raw.md` 可直接阅读。
2. **脱水**：精炼改写后约为原文的四分之一，信息点保留完整。
3. **笔记与通知**：以课件为主线的笔记可以用于复习；在多门课程上验证效果良好。课堂通知能抓到，偶尔混入老师的一般性提醒。
4. **用量与时间**：2 小时的课约 15 分钟处理完，其中语音转写 9–11 分钟（上传约 2 分钟，服务端响应约 1.5 分钟，其余为识别）。大模型约 8 万输入 token、2 万输出 token（`dehydrater status` 按步骤列出）。

## 11. 后续阶段（本阶段不做）

- 课件图片：把含图表的页渲染成图片嵌入笔记；或交给多模态模型读图
- 术语表作为 ASR 热词；ASR 2.0 支持把课件图片作为识别上下文
- 课程级汇总：跨讲次的通知清单、日历导出
- 超长录音按静音切分
- UI、打包分发

设计思路见 `docs/design.md`（备忘录，非当前计划）。
