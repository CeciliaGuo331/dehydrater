# Dehydrater 架构设计与开发计划（v1 / Python）

> 本文是对 `plan.md` 的细化与修订。`plan.md` 保留为讨论记录，本文为实施依据。
> 标注 **【待验证】** 的地方是我不确定、需要写代码前花 10 分钟实测确认的事实。

---

## 0. 对原计划的主要修订

| 原计划 | 修订 | 理由 |
| --- | --- | --- |
| 4 周直接上 Tauri | v1 用 Python 验证管线和 Prompt，v2 再用 Tauri + Rust 重写 | 你已决定"写两遍"。v1 的价值在于把**数据格式、Prompt、对齐算法**打磨定型，这三样会原样带进 v2 |
| 关键词滑动窗口对齐 | 全局最优路径对齐（Viterbi/DP），可融合"视频画面"信号 | 局部窗口在老师回翻、跳讲时会连锁出错；全局 DP 代码量相当，但鲁棒得多 |
| 无缓存设计 | 每个阶段产物落盘 + 内容哈希缓存 | 调 Prompt 时不能每次重跑 ASR（慢且花钱）。这是 v1 迭代效率的关键 |
| 没提用户编辑 | 生成稿与用户稿分离，重新生成绝不覆盖用户改过的文件 | UI 有编辑功能，这是必须先想清楚的数据所有权问题 |
| 只抽课件文字 | 同时渲染每页图片，嵌入讲义；可选交给多模态模型读图 | 操统课件大量是图（页表、调度甘特图、状态机），只取文字会丢一半信息 |
| 手写 OS 术语纠错表 | 从课件自动提取术语表，喂给 ASR 提示词和 LLM | 课件里本来就有正确拼写的术语，通用且零维护；手写表只作补充 |
| PyMuPDF | 优先 `pypdfium2` | PyMuPDF 是 **AGPL**，会传染整个项目的许可证。若你本就打算 AGPL/GPL 发布则无所谓 |
| 第二阶段"全局组装"重写全文 | 第二阶段只生成导言/大纲/速查表，正文由各节拼接 | 让 LLM 长篇复写正文既贵又会丢细节、产生幻觉 |
| v1 单文件可执行 | v1 用 `uv tool install` + Nix flake 分发；单文件打包留给 v2 | PyInstaller 打包 numpy/onnxruntime 的坑多，v1 的用户是你和懂技术的同学，不值得 |
| 25MB 上传限制要按静音切分 | 保留，但优先级降低 | 16kHz 单声道 Opus @ 24kbps，90 分钟约 16MB，常规课程触发不到 |

---

## 1. 总体架构

### 1.1 分层（端口与适配器 / 六边形架构）

```text
┌────────────────────────────────────────────────────────────┐
│  入口层   cli (Typer)          ui (NiceGUI)                  │  ← 薄，只做参数/交互
├────────────────────────────────────────────────────────────┤
│  组合根   bootstrap.py  ── 读配置，把具体适配器注入流水线      │
├────────────────────────────────────────────────────────────┤
│  应用层   pipeline/  Stage、Runner、缓存、进度事件、取消       │
├──────────────────────────────┬─────────────────────────────┤
│  领域层   domain/  数据模型    │  端口  ports.py (Protocol)   │
│          align/   纯算法      │                             │
├──────────────────────────────┴─────────────────────────────┤
│  适配器   adapters/  媒体 · ASR · 文档 · LLM · 工作区存储      │  ← 所有第三方库只出现在这里
└────────────────────────────────────────────────────────────┘
```

**依赖规则**（用 [import-linter](https://github.com/seddonym/import-linter) 在 CI 中强制，防止腐化成面条）：

1. `domain`、`align` 不 import 任何 IO 或第三方 SDK（numpy/pydantic 除外）。
2. `pipeline` 只依赖 `domain`、`align`、`ports`，**不认识任何具体适配器**。
3. `adapters` 实现 `ports`，彼此之间不互相 import。
4. 只有 `bootstrap` 同时认识 `pipeline` 和 `adapters`。
5. `cli` 和 `ui` 只通过 `bootstrap` 拿到装配好的服务。

这样做的直接收益：换 ASR 厂商 = 新增一个文件；测流水线 = 注入假适配器；v2 重写时 `domain`/`align` 是一对一翻译到 Rust 的最小集合。

### 1.2 处理流水线

```text
 输入: 视频/音频 ×1..n  +  课件(PDF/PPTX) ×0..n
   │
   ├─ extract_audio   视频 → 16kHz 单声道 Opus（必要时按静音切块）
   ├─ ingest_slides   课件 → 每页文本 + 每页 PNG + 术语表
   ├─ transcribe      音频 + 术语提示 → 带时间戳的逐字稿 (Transcript)
   ├─ extract_notices 原始逐字稿 → 课堂通知（签到、考试、作业 DDL、调课…）
   ├─ clean           逐字稿分块 → 去口癖/纠术语的"可读全文"（保信息量，不做摘要）
   ├─ align           可读全文 × 课件页 → 每页对应的时间区间 (Alignment)
   ├─ write_sections  每页(组)：课件文本/图 + 对应讲解 → 结构化笔记 (SectionNote)
   ├─ synthesize      所有 SectionNote → 导言、大纲、速查表、考点汇总
   └─ render          模板渲染 → lecture.generated.md（+ 可选 PDF）
```

注意 `extract_audio → transcribe → {extract_notices, clean}` 与 `ingest_slides` 是独立分支，Runner 可以并发执行。没有课件时 `align`/`write_sections` 退化为"按时间分节"，流水线仍可用。

`extract_notices` 必须读**原始**逐字稿而不是清洗后的：通知在讲课内容里属于"废话"，`clean` 会把它删掉。两者都只依赖 `transcribe`，可以并发执行。

---

## 2. 选型（优先开源现成项目）

### 2.1 v1 依赖清单

| 职责 | 选用 | 备选 / 说明 |
| --- | --- | --- |
| 项目与依赖管理 | **uv** | — |
| 代码质量 | **ruff**（lint+format）、**basedpyright** strict、**import-linter** | mypy 也可，二选一 |
| 测试 | **pytest**、pytest-asyncio、**respx**（mock HTTP）、**syrupy**（快照） | — |
| 数据模型 | **pydantic v2** | 顺带导出 JSON Schema，作为 v2 的契约 |
| 配置 | **pydantic-settings** + TOML，路径用 **platformdirs** | 跨平台配置目录不用自己判断 |
| 密钥存储 | **keyring** | 走系统钥匙串（Win Credential / macOS Keychain / Secret Service），不明文存 Key |
| 音视频解码 | **PyAV**（`av`） | wheel 自带 FFmpeg 库，用户无需装 ffmpeg，NixOS 友好 |
| 云端 ASR | **openai** SDK（OpenAI 兼容 `/audio/transcriptions`） | Groq、OpenAI 均兼容。**【待验证】** 硅基流动的 SenseVoice 接口是否返回时间戳——若不返回则无法对齐，只能作"无时间戳"降级 |
| 本地 ASR | **sherpa-onnx** + SenseVoice/Paraformer 模型 | 中文效果明显好于 Whisper，ONNX 无需 PyTorch，内置 Silero VAD，**并且有 Android/iOS 支持，v2 移动端可直接复用**。**【待验证】** SenseVoice 在 sherpa-onnx 中的 token 时间戳精度。备选 faster-whisper |
| PDF | **pypdfium2** | 文本抽取 + 页面渲染，Apache/BSD 许可。v2 对应 Rust 的 `pdfium-render`，同一个引擎 |
| PPTX | 调用 **LibreOffice** headless 转 PDF，再走 PDF 流程 | 统一成一条路径，且得到页面图片。没有 LibreOffice 时回退 **python-pptx** 只抽文本 |
| 扫描版课件 OCR（可选） | **RapidOCR**（onnxruntime） | 中文好，轻量，`[ocr]` extra |
| 文本相似度 | **scikit-learn** `TfidfVectorizer(analyzer="char_wb", ngram_range=(2,4))` | 字符 n-gram 天然处理中英混排，免分词。可选：OpenAI 兼容 embeddings 接口（如 bge-m3）作更强信号 |
| 画面切换检测（可选） | **PySceneDetect** | 录屏类视频的翻页检测，`[vision]` extra |
| LLM 调用 | **openai** SDK + `base_url` | 覆盖 DeepSeek/硅基流动/Groq/OpenRouter/Ollama/LM Studio。不引入 LangChain 一类的重框架 |
| 结构化输出 | pydantic 校验 + **tenacity** 重试 | 不依赖各家不一致的 JSON mode 细节 |
| 限流 | **aiolimiter** | 令牌桶，按 provider 配 RPM |
| Prompt 模板 | **Jinja2**，模板放独立 `.j2` 文件 | v2 用 Rust 的 **minijinja**，语法兼容，Prompt 文件原样复用 |
| CLI | **Typer** + **rich** | — |
| UI | **NiceGUI** | 见 2.2 |
| PDF 导出（可选） | 调用外部 **pandoc** + **typst** 引擎 | 中文排版好；作为可选外部工具，不打包 |

### 2.2 UI 方案的取舍

| 方案 | 开发成本 | v2 可复用 | 结论 |
| --- | --- | --- | --- |
| **NiceGUI**（纯 Python，浏览器渲染） | 低 | 否 | **推荐** |
| FastAPI + Svelte 前端 | 高（两种语言、两套构建） | 前端可进 Tauri | v1 不值得 |
| Gradio / Streamlit | 最低 | 否 | 状态管理和布局控制太弱，做编辑器很别扭 |
| PySide6 | 中 | 否 | 原生但 Markdown 预览要自己拼，NixOS 上 Qt 依赖烦 |

理由：v1 的 UI 是**一次性的**，它的使命是让你能用上、并验证交互流程；真正的前端在 v2。NiceGUI 自带所需全部组件：

- `ui.upload`（拖拽上传）
- `ui.codemirror(language="markdown")`（编辑）+ `ui.markdown`（预览）左右分栏
- `ui.video`（播放原视频，点击讲义中的时间戳跳转）
- `ui.stepper` / `ui.linear_progress`（流水线进度）

默认用浏览器模式运行（`dehydrater ui` 打开 localhost）。`native=True`（pywebview 窗口）作可选项——在 NixOS 上 pywebview 的 GTK/WebKit 依赖不太好配，不要让它成为默认路径。

**【待验证】** `ui.markdown` 对 KaTeX 公式和 Mermaid 的支持程度；若不足，预览改用 `markdown-it-py` 渲染 + `ui.html` 并在页面注入 KaTeX。

另外：重度编辑场景不必在 v1 里做到 Typora 水平，提供"在外部编辑器中打开"按钮（Obsidian/Typora/VS Code），文件变更时自动刷新预览即可。

---

## 3. 数据设计（v1 最需要做对的部分）

数据格式是跨越 v1→v2 的**唯一稳定契约**。所有模型用 pydantic 定义，CI 中导出 JSON Schema 到 `schemas/`，v2 的 Rust 端用 serde 读同一份数据，并用同一批 fixture 做对照测试。

### 3.1 工作区（Workspace）目录结构

一节课 = 一个目录，可以直接放进网盘或 git：

```text
os-2026/                         # 课程 (Course)
├── course.toml                  # 课程级设置：名称、术语表补充、默认模型
├── notices.md                   # 全课程通知汇总（程序生成，只读视图）
├── notices.ics                  # 可选：有明确日期的通知导出为日历
├── notices.state.toml           # 用户对通知的"已处理/忽略"标记（用户拥有）
└── L03-进程调度/                 # 讲次 (Lecture)
    ├── lecture.toml             # 输入文件清单、上课日期、讲次级覆盖设置
    ├── sources/                 # 用户上传的原件（复制或硬链接）
    │   ├── recording.mp4
    │   └── ch3-scheduling.pdf
    ├── .cache/                  # 各阶段产物，可随时删除重建
    │   ├── extract_audio/  { meta.json, audio.opus }
    │   ├── ingest_slides/  { meta.json, deck.json, pages/001.png ... }
    │   ├── transcribe/     { meta.json, transcript.json }
    │   ├── extract_notices/{ meta.json, notices.json }
    │   ├── clean/          { meta.json, cleaned.json }
    │   ├── align/          { meta.json, alignment.json }
    │   ├── write_sections/ { meta.json, sections.json }
    │   └── synthesize/     { meta.json, synthesis.json }
    ├── lecture.generated.md     # 最近一次生成结果（程序拥有）
    ├── lecture.md               # 用户稿（用户拥有，程序只在首次或用户确认后写入）
    └── assets/                  # 讲义引用的页面图片
```

**所有权规则**：

- `.cache/` 和 `*.generated.md` 归程序，可随时覆盖。
- `lecture.md` 归用户。重新生成时：若 `lecture.md` 的哈希等于上次写入时记录的哈希（用户没改过），直接更新；否则只更新 `lecture.generated.md`，UI 提示"有新版本"并提供 diff 视图，由用户决定。

### 3.2 核心领域模型（草图）

```python
# domain/models.py —— 只有数据，没有行为以外的依赖

class Seconds(float): ...                       # 或直接 NewType

class TranscriptSegment(BaseModel):
    start: Seconds
    end: Seconds
    text: str

class Transcript(BaseModel):
    language: str
    segments: list[TranscriptSegment]
    has_timestamps: bool = True                 # 某些 ASR 不给时间戳，下游据此降级

class SlidePage(BaseModel):
    deck_id: str
    index: int                                  # 从 1 开始，与课件页码一致
    text: str
    title: str | None
    image: Path | None                          # 相对 workspace 的路径

class Deck(BaseModel):
    id: str
    source: Path
    pages: list[SlidePage]
    glossary: list[str]                         # 自动抽取的术语

class AlignedSpan(BaseModel):
    page: tuple[str, int] | None                # (deck_id, index)；None = 课外拓展/未匹配
    start: Seconds
    end: Seconds
    confidence: float

class Alignment(BaseModel):
    spans: list[AlignedSpan]                    # 按时间有序、首尾相接、覆盖全程

class SectionNote(BaseModel):
    pages: list[tuple[str, int]]
    heading: str
    key_points: list[Cited]                     # 课件上有、老师讲到的要点
    elaborations: list[Cited]                   # 老师口头补充、课件上没有的内容（最有价值）
    exam_hints: list[Cited]                     # "这个要考"、"注意"、反复强调
    open_questions: list[str]                   # 没听清/疑似识别错误，留给人看

class NoticeKind(StrEnum):
    ATTENDANCE = "attendance"                   # 签到、点名、签到码
    EXAM = "exam"                               # 考试时间/地点/范围/形式
    ASSIGNMENT = "assignment"                   # 作业、实验、DDL、提交方式
    SCHEDULE = "schedule"                       # 调课、停课、补课、教室变更
    GRADING = "grading"                         # 成绩构成、评分规则
    OTHER = "other"

class Notice(BaseModel):
    kind: NoticeKind
    summary: str                                # 一句话："Lab2 截止时间改为 11 月 3 日 23:59"
    quote: str                                  # 原始逐字稿片段，ASR 可能听错数字/日期，留原文供核对
    at: Seconds                                 # 在本讲视频中的时间点
    due: date | datetime | None                 # 解析出的绝对日期（基于上课日期换算"下周三"）
    due_phrase: str | None                      # 原话中的时间表达："下周三上课前"
    lecture_id: str                             # 课程级汇总时追溯来源

class Cited(BaseModel):
    text: str
    at: Seconds                                 # 回链到视频时间点
```

关键设计：`SectionNote` 是**结构化**的，Markdown 由 `render/` 里的 Jinja 模板生成。这样"内容"与"排版"分离：改讲义样式不需要重新调用 LLM，UI 也能针对考点等字段做专门展示。

### 3.3 阶段缓存

```python
# pipeline/stage.py

class Stage(Protocol[InT, OutT]):
    name: ClassVar[str]
    version: ClassVar[int]          # 改了阶段逻辑或 Prompt 就 +1，使旧缓存失效

    def cache_key_parts(self, inputs: InT) -> Mapping[str, object]: ...
    async def run(self, inputs: InT, ctx: StageContext) -> OutT: ...
```

`cache_key = sha256(name, version, 输入产物的哈希, 本阶段相关的配置项)`，写入 `meta.json`。Runner 执行前比对，命中则直接读盘。

- Prompt 模板的文件哈希自动计入相关阶段的 key：改 Prompt 只重跑 `clean` 之后的阶段，ASR 不动。
- 换 LLM 模型只影响 LLM 阶段；换 ASR 才会重跑转录。
- `clean` 和 `write_sections` 内部是按块/按节并发调用的，**块级**也做缓存（`.cache/clean/chunks/<hash>.json`），中途失败或取消后重跑只补缺的块。

> 也考察过 Hamilton、Prefect 等 DAG 框架：它们解决的是更大规模的问题，对 7 个阶段的线性 DAG 而言，引入的概念比省下的代码多。自写 Runner 预计 < 150 行，这是本项目唯一刻意"自己造"的基础设施。

### 3.4 进度与取消

Runner 通过一个事件回调向外报告，`cli` 用 rich 进度条消费，`ui` 用 NiceGUI 组件消费，流水线本身不知道谁在听：

```python
class StageStarted(Event): stage: str
class StageProgress(Event): stage: str; done: int; total: int
class StageFinished(Event): stage: str; cached: bool
class StageFailed(Event): stage: str; error: str
```

取消用 `asyncio` 任务取消即可；因为有块级缓存，取消不会浪费已完成的调用。

---

## 4. 关键模块设计

### 4.1 音频提取 `extract_audio`

- PyAV 解码任意容器的音轨 → 重采样 16kHz 单声道 → 编码 Opus 24kbps（`.ogg`）。
- 若超出所选 ASR 的大小上限（由 ASR 适配器声明 `max_upload_bytes`），按"目标时长附近能量最低点"切块：解码出 PCM 后用 numpy 算短时能量，取窗口内最小值处切开。约 30 行，不值得为此引入依赖。块之间记录时间偏移，转录后统一校正。
- 本地 ASR（sherpa-onnx）自带 VAD，不需要这一步切块。

### 4.2 课件解析 `ingest_slides`

- PDF：pypdfium2 逐页抽文本 + 渲染 PNG（150 DPI 足够）。
- PPTX：LibreOffice `--headless --convert-to pdf` → 走 PDF 路径；保留 python-pptx 抽出的备注栏（speaker notes 往往有讲稿）。
- 页标题：取首行/最大字号行（pypdfium2 可拿到字符的字号信息）。
- **术语表**：从全部页文本中抽取英文词、缩写（`TLB`、`PCB`、`fork()`）及中英对照模式（`页表 (page table)`），按 TF-IDF 取前 N 个。用途：①作为 ASR 的 `prompt`/热词，②放进 LLM 纠错上下文。`course.toml` 可手动追加。
- 扫描版（某页抽出文本为空但有图）：有 `[ocr]` 时跑 RapidOCR，否则标记该页"仅图片"，交给后续多模态模型或只嵌图。

### 4.3 转录 `transcribe`

```python
class Transcriber(Protocol):
    capabilities: TranscriberCapabilities   # 是否给时间戳、单次上限、是否支持提示词
    async def transcribe(self, audio: AudioChunk, hints: TranscriptionHints) -> Transcript: ...
```

- 云端：`response_format="verbose_json"`，取 segment 级时间戳即可，词级时间戳不是必需的（对齐粒度是"句"）。
- 中文 Whisper 常见问题：输出繁体、标点缺失、静音段幻觉（重复句子）。处理：提示词里给一句规范的简体带标点中文；后处理去除完全重复的相邻段。
- 产物同时导出一份 `transcript.md`（带 `[mm:ss]`），M1 阶段就能直接给你用。

### 4.4 通知提取 `extract_notices`

课堂上的签到、考试安排、作业 DDL、调课等信息与知识内容性质完全不同：时效性强、错过代价高、需要跨讲次汇总。所以单独成为一个阶段，而不是作为 `SectionNote` 的一个字段。

- **为什么单独一个阶段，而不是让 `clean` 顺便提取**：单一职责的 Prompt 召回率更高；可独立缓存和调参；用便宜的 `models.fast` 再读一遍原文，一节课的成本可以忽略。
- **输入**：原始逐字稿分块（与 `clean` 共用 `domain/chunking.py`）+ 上课日期 + 星期几。
- **上课日期**：来自 `lecture.toml`；缺省时依次尝试视频元数据的 `creation_time`（PyAV 可读）、文件修改时间，并在 UI 中提示用户确认——相对日期（"下周三"、"两周后"）全靠它换算。
- **Prompt 策略**：**宁多勿漏**。漏掉一个 DDL 的代价远大于多列一条无关信息；不确定的条目照样输出，由用户删。日期由 LLM 结合上课日期换算，但必须同时输出原话 `due_phrase` 和原文 `quote`，因为 ASR 对数字和日期的识别最不可靠。
- **块边界**：通知可能跨块（"作业……我说一下……下周五交"），切块重叠要比 `clean` 大一些；块内结果按 `(kind, due, summary)` 近似去重。
- **输出位置**：
  1. 讲次内：`lecture.md` 开头的"📢 本讲通知" callout，每条带 `[▶ mm:ss]` 跳转，方便听原话核对。
  2. 课程级：`render` 后由一个轻量的课程级汇总步骤生成 `notices.md`——按类别分组、有日期的按日期排序、已过期的折叠；标注来源讲次。
  3. 可选：有明确日期的条目导出 `notices.ics`（用 **icalendar** 库），导入手机/系统日历。
- **用户状态**：UI 中"已处理/忽略"的勾选存在课程目录下的 `notices.state.toml`（用户拥有，以通知内容哈希为键），与生成的 `notices.md` 分开，重新生成不会丢勾选——与 3.1 的所有权规则一致。
- **通知被更新的情况**（"上次说的考试时间改了"）：v1 不自动合并，按时间顺序全部列出、标注来源讲次，让人判断；后续可加一个 LLM 合并步骤，输入只是通知列表，体量很小。

### 4.5 清洗 `clean`

- 按 token 预算（约 3k–4k 字）在句子边界切块，块间重叠 1–2 句避免断句。
- 输入：块文本（每句带 `[mm:ss]`）+ 术语表 + 该时间段附近的课件文本（在对齐之前没有精确页，这一步可以先给全部术语表，不给课件正文）。
- 任务约束写死在 Prompt 中：**只删除**口癖、重复、点名、课堂通知（已由 `extract_notices` 单独提取）、闲聊、"大家听得到吗"；**修正**明显的术语识别错误；**不得**总结、不得增加原文没有的信息；保留时间戳标记。
- 输出：清洗后的句子列表（保留时间戳），而不是自由 Markdown。可以做一个简单校验：清洗后字数占比若低于阈值（如 30%），视为 LLM 过度删减，重试或告警。

### 4.6 对齐 `align`（核心算法）

把问题建模为隐马尔可夫链上的最优路径：

1. 把清洗后的全文切成约 20–30 秒的窗口 `w_1 … w_T`。
2. 状态集合 = 所有课件页 `p_1 … p_N` + 一个"课外"状态 `∅`。
3. 发射分数 `E[t, n]` = `sim(w_t, p_n)`，用字符 n-gram TF-IDF 余弦相似度；`E[t, ∅]` = 常数阈值 τ。
4. 转移分数：停留 0；前进 1 页 小惩罚；前进多页 中惩罚（跳过的页）；后退 较大惩罚（回翻）；进出 `∅` 中惩罚。
5. Viterbi 求全局最优路径，合并相邻相同状态得到 `AlignedSpan`，置信度取路径上的平均边际分数。

纯 numpy，约 60 行，放在 `align/viterbi.py`，**无 IO，极易单测**（构造合成数据：已知翻页点的文本 → 检查恢复出的翻页点误差）。

可选信号融合（`[vision]`）：若视频是录屏且画面里有课件，用 PySceneDetect 找画面切换点，抽关键帧与课件 PNG 做感知哈希匹配，得到"画面所示页"的观测，加到发射分数上。录屏课这个信号比文本可靠得多；有摄像头画中画或纯板书时自动降权。两种信号走同一个 Viterbi，只是发射矩阵不同——这是把算法设计成"打分矩阵 + 通用解码器"的好处。

**评测**：手工标注 1–2 节课的真实翻页时间（拖一遍视频，半小时），写成 `tests/fixtures/*.alignment.json`。指标 = 被正确归属的时长占比。每次调参都跑一遍，不再凭感觉调。

### 4.7 分节笔记 `write_sections`

- 将对齐后的连续页（讲解很短的页）合并成节，避免每页一次调用、每页只有两句话。
- 每节输入：课件页文本 + 页图（若模型支持视觉）+ 该节的清洗文本 + 术语表。
- 输出：`SectionNote` JSON（见 3.2），pydantic 校验失败则带错误信息重试一次。
- 并发 + aiolimiter 限流 + tenacity 指数退避（只对 429/5xx/超时重试）。
- `∅` 状态的片段归入"课外拓展"节，不强行挂到某页。

### 4.8 汇总 `synthesize` 与渲染 `render`

- `synthesize` 只读各节的 `heading` + `key_points` + `exam_hints`（体量很小），生成：一段导言、章节大纲（可选 Mermaid 思维导图）、术语速查表、考点汇总。**不重写正文。**
- `render` 用 `render/templates/lecture.md.j2` 组装：本讲通知 → 导言 → 大纲 → 各节（嵌入页图、要点、口头补充、考点 callout、`[▶ 12:34]` 时间戳链接）→ 课外拓展 → 速查表。
- 时间戳链接格式 `[▶ 12:34](sources/recording.mp4#t=754)`：外部编辑器里也可点击，UI 中被拦截为播放器跳转。

### 4.9 LLM 适配器

```python
class ChatModel(Protocol):
    capabilities: ModelCapabilities          # 上下文长度、是否支持视觉
    async def complete(self, messages: Sequence[Message]) -> str: ...

async def complete_structured(model: ChatModel, messages, schema: type[T]) -> T:
    """放在 pipeline 层的通用函数：调用 → 抽取 JSON → pydantic 校验 → 失败带错误重试。"""
```

不同阶段可配置不同模型（如 `clean` 用便宜快模型，`write_sections` 用强模型），配置中按"角色"而不是按阶段命名：`models.fast`、`models.strong`、`models.vision`。

---

## 5. 代码目录

```text
dehydrater/
├── pyproject.toml              # uv 管理；extras: local-asr, ocr, vision
├── flake.nix                   # devShell + package（NixOS）
├── .importlinter               # 分层约束
├── docs/
│   ├── design.md               # 本文
│   └── adr/                    # 架构决策记录，一事一文，v2 重写时最有用的资料
├── schemas/                    # 自动导出的 JSON Schema（v2 契约）
├── src/dehydrater/
│   ├── domain/
│   │   ├── models.py           # 3.2 中的模型
│   │   ├── timecode.py         # 秒 ↔ mm:ss
│   │   └── chunking.py         # 按句/按 token 切块（纯函数）
│   ├── align/
│   │   ├── similarity.py       # 文本 → 发射矩阵
│   │   ├── viterbi.py          # 通用解码器
│   │   └── visual.py           # 画面 → 发射矩阵（可选）
│   ├── ports.py                # Transcriber, SlideLoader, ChatModel, AudioExtractor, Workspace
│   ├── adapters/
│   │   ├── media_pyav.py
│   │   ├── asr_openai_compat.py
│   │   ├── asr_sherpa.py
│   │   ├── slides_pdf.py
│   │   ├── slides_pptx.py
│   │   ├── llm_openai_compat.py
│   │   └── workspace_fs.py
│   ├── pipeline/
│   │   ├── stage.py            # Stage 协议、缓存键
│   │   ├── runner.py           # 依赖调度、缓存、事件、取消
│   │   ├── events.py
│   │   ├── structured.py       # complete_structured
│   │   └── stages/             # 每个阶段一个文件，各自 < 150 行
│   │       ├── extract_audio.py
│   │       ├── ingest_slides.py
│   │       ├── transcribe.py
│   │       ├── extract_notices.py
│   │       ├── clean.py
│   │       ├── align.py
│   │       ├── write_sections.py
│   │       ├── synthesize.py
│   │       └── render.py
│   ├── prompts/                # *.j2，只有文本，没有代码
│   │   ├── notices.system.j2
│   │   ├── clean.system.j2
│   │   ├── clean.user.j2
│   │   ├── section.system.j2
│   │   └── ...
│   ├── render/templates/lecture.md.j2
│   ├── config.py               # pydantic-settings
│   ├── bootstrap.py            # 组合根：config → adapters → pipeline
│   ├── cli.py
│   └── ui/
│       ├── app.py
│       ├── pages/              # course_list.py, lecture.py, settings.py
│       └── components/         # uploader.py, pipeline_status.py, editor.py, player.py
└── tests/
    ├── unit/                   # domain, align, chunking, render —— 毫秒级，无网络
    ├── pipeline/               # 用假适配器跑完整流水线
    ├── adapters/               # respx 录制的 HTTP 交互
    └── fixtures/               # 短音频、小课件、手标对齐
```

### 可读性约定（写进 CONTRIBUTING，CI 能查的都交给 CI）

- basedpyright strict 零报错；公共函数必须有类型；禁止 `Any` 外泄出 adapters。
- 依赖只通过构造函数注入；无全局可变状态、无模块级单例（配置也通过 `bootstrap` 传入）。
- 函数做一件事，单个模块超过 ~300 行就该拆。
- 第三方库的类型不跨出 adapter 边界（例如 `openai` 的响应对象在适配器内就转成领域模型）。
- Prompt 不写在 Python 字符串里。
- 注释解释"为什么"，不复述"做了什么"。
- 每个非显然的取舍写一篇 ADR（如"为什么不用 PyMuPDF"、"为什么对齐用 Viterbi"）。

---

## 6. 开发计划

原则：**尽早可用**。你现在就有一门课要刷，所以 M3 结束时就应当能产出可读的笔记，而 UI 放在算法稳定之后。

| 里程碑 | 内容 | 完成标志 | 预估 |
| --- | --- | --- | --- |
| **M0 骨架** | uv 项目、ruff/basedpyright/import-linter/pytest、GitHub Actions（三平台跑测试）、`domain/models.py`、`flake.nix` devShell | CI 绿 | 0.5 天 |
| **M1 转录** | `extract_audio`、`transcribe`（先只做 OpenAI 兼容云端）、Workspace、Stage/Runner/缓存、CLI `dehydrater transcribe <video>` | 拿到带时间戳的 `transcript.md`；重复执行秒级命中缓存 | 2 天 |
| **M2 课件** | `ingest_slides`（PDF；PPTX 经 LibreOffice）、术语表抽取、术语回灌 ASR 提示词 | `deck.json` + 页图；对比加术语前后的转录质量 | 1 天 |
| **M3 清洗与通知** ⭐ | LLM 适配器、`complete_structured`、`clean` 与 `extract_notices` 阶段及 Prompt、限流重试、块级缓存、课程级 `notices.md` | **第一次可用**：干净、带时间戳的全文 + 通知清单 | 2.5 天 |
| **M4 对齐** | 手标 1 节课真值、`similarity` + `viterbi`、评测脚本 | 正确归属时长 ≥ 85%（先定这个目标，按实测调整） | 2–3 天 |
| **M5 讲义** | `write_sections`、`synthesize`、`render` 模板、用户稿/生成稿所有权逻辑 | 完整讲义 Markdown | 2–3 天 |
| **M6 UI** | NiceGUI：课程/讲次列表、拖拽上传、流水线进度与单阶段重跑、编辑+预览、保存、视频时间戳跳转、课程页通知面板（按 DDL 排序、可勾选已处理）、设置页（keyring） | 不碰命令行完成全流程 | 3–4 天 |
| **M7 发布** | README + 示例、`uv tool install`、Nix flake package、AUR `PKGBUILD`（python 包）、PyPI | 别人能装上 | 1–2 天 |
| M8 可选增强 | 本地 ASR（sherpa-onnx）、画面对齐（`[vision]`）、OCR、多模态读图、PDF 导出、通知 `.ics` 导出与跨讲次合并 | 按需 | — |

每个里程碑结束时：更新 ADR、确认 `schemas/` 的变更是有意为之。

---

## 7. v2 展望（写第二遍时）

v1 结束时应当沉淀下来、v2 直接复用的资产：

1. **数据契约**：`schemas/*.json` 与 workspace 目录结构 → v2 可以直接打开 v1 的工作区。
2. **Prompt**：`prompts/*.j2` → minijinja 原样加载。
3. **对齐算法**：`align/` 一对一翻译成 Rust，用同一批 fixture 做对照测试。
4. **评测集**：手标的对齐真值 + 若干节课的产出样本。
5. **ADR**：哪些路走过、为什么不走。

v2 技术栈初步设想：

- **Tauri 2**（桌面三平台 + iOS/Android）+ Svelte 5 或 Vue 前端。
- Rust workspace：`core`（不依赖 Tauri，纯逻辑）、`cli`、`app`。
- ASR：云端 `reqwest`；本地 sherpa-onnx（有 C API，可绑定；移动端官方支持）或 whisper.cpp（`whisper-rs`）。
- PDF：`pdfium-render`（与 v1 同一引擎）。LLM：`async-openai`。
- Markdown 编辑器：**Vditor**（类 Typora 即时渲染，中文社区维护）或 **Milkdown**，或 CodeMirror 6 + markdown-it 双栏。
- 分发：Tauri bundler 产出 msi/dmg/AppImage/deb；Arch 用 AUR `-bin` 包；NixOS 用 flake（`rustPlatform.buildRustPackage` + 前端构建）。
- 移动端：本地推理吃力，默认云端 ASR；可以考虑只做"查看/编辑讲义 + 发起云端处理"。

---

## 8. 风险与待决问题

| 问题 | 影响 | 应对 |
| --- | --- | --- |
| ASR 不返回时间戳 | 无法对齐、无法跳转 | `Transcript.has_timestamps` 降级路径：按字数比例估算时间，标注"时间戳不精确" |
| LLM 删过头或编造内容 | 讲义失真 | 清洗阶段字数占比校验；所有要点必须带时间戳引用；UI 可一键跳原文核对 |
| 通知中的日期/数字识别错误 | 错过 DDL | 永远附带原话 `quote` 与时间戳跳转；日期由上课日期换算且上课日期需用户确认；UI 中把"日期解析存疑"的条目高亮 |
| 老师大量板书/演示代码，课件无对应 | 对齐置信度低 | 归入 `∅` 课外节；`[vision]` 可抽关键帧嵌入讲义 |
| 许可证 | 依赖传染 | 确定项目许可证（建议 MIT 或 Apache-2.0；若想用 PyMuPDF 等则选 AGPL），CI 加 `pip-licenses` 检查 |
| 课程视频版权 | 分享产物的合规性 | 工具纯本地运行、不托管任何内容；README 声明仅供个人学习 |

**需要你拍板的事**：

1. 项目名（目录叫 `dehydrater`，`plan.md` 里倾向 Dehydrate）——影响包名、CLI 命令名，越早定越好。
2. 许可证（决定能否使用 AGPL 依赖）。
3. 你的课程视频是否为录屏且画面中有课件？若是，画面对齐应从 M8 提前到 M4，它会让对齐几乎不成问题。
4. 课程语言：纯中文 / 中英混杂 / 英文授课？决定 ASR 默认选 SenseVoice 还是 Whisper。
