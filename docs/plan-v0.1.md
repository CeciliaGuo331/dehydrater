# dehydrater v0.1 计划书：CLI 功能验证版

## 1. 目标

用一个命令行工具，把**一节课的录像 + PDF 课件**处理成三份 Markdown：

| 产物 | 内容 |
| --- | --- |
| `transcript.md` | 带时间戳的逐字稿，已去掉口癖、修正术语 |
| `notices.md` | 课堂通知：签到、考试、作业 DDL、调课等 |
| `lecture.md` | 按课件页组织的讲义：要点、老师口头补充、考点提示，每条带时间戳 |

本阶段要回答的问题：

1. 中英混杂的课堂录音，哪家 ASR API 的准确率够用？
2. LLM 清洗时，会不会删掉有用信息？
3. 通知能不能抓全？
4. 只靠文本相似度，能把讲解对齐到课件页吗？还是必须用画面信号？
5. 处理一节课要花多少钱、多长时间？

## 2. 约束

- **不在本地跑任何模型**，ASR 和 LLM 全部走 API，本地只做解码、PDF 解析、数值计算这类 CPU 工作。
- 只做 CLI，交互保持最简单。
- 一次只处理一节课，输入为 1 个视频加 0 或 1 个 PDF。
- 代码可读性优先：分层清晰，有类型，可测试。

## 3. 需要你准备的 API

测试阶段统一使用**火山引擎**。注意它的 ASR 和 LLM 是两个不同的产品，需要分别开通：

| 用途 | 服务 | 何时需要 | 说明 |
| --- | --- | --- | --- |
| ASR | **豆包语音**：大模型录音文件识别 | S1 起 | 中英混杂表现好，支持热词（直传最多 5000 个），返回分句和逐字时间戳。接口是火山的私有协议（提交任务 + 轮询结果），需要单独写一个 adapter。**标准版只接受音频 URL，不能上传本地文件**，上传方案在 S1 确定 |
| LLM | **火山方舟**：豆包或方舟上托管的 DeepSeek | S4 起 | 接口兼容 OpenAI（`https://ark.cn-beijing.volces.com/api/v3`） |

每个任务的 API 渠道都可以单独配置（见 §9）。如果 S1 发现火山 ASR 不理想，可以换成其他渠道对比（例如 Groq `whisper-large-v3`），只需改配置，不用改代码。

## 4. 处理流程

```text
lecture.mp4 ──► extract_audio ──► transcribe ──┬──► extract_notices ──► notices.md
                                       ▲        │
slides.pdf ──► ingest_slides ──────────┤        └──► clean ──► transcript.md
                     │            (术语表)                │
                     └────────────────────────► align ◄──┘
                                                  │
                                                  ▼
                                           write_sections ──► render ──► lecture.md
```

| 阶段 | 输入 → 输出 | 实现要点 |
| --- | --- | --- |
| `extract_audio` | 视频 → 16kHz 单声道 Opus | PyAV 解码；90 分钟约 16MB。如果超过 ASR adapter 声明的单次上传上限，就按能量最低点切块（numpy） |
| `ingest_slides` | PDF → 每页文本 + 页面 PNG + 术语表 | PyMuPDF。术语表 = 课件中的英文词、缩写、中英对照，按频率取前 N 个 |
| `transcribe` | 音频 + 术语表 → `Transcript` | 术语表放进 ASR 的 `prompt` 参数，提高 `TLB`、`fork()` 等词的识别率 |
| `extract_notices` | **原始**逐字稿 + 上课日期 → `list[Notice]` | 必须读原始稿，因为 `clean` 会把通知当废话删掉。原则是宁多勿漏 |
| `clean` | 逐字稿 + 术语表 → 清洗后的句子 | 只删不写：去口癖、去重复、修正术语，保留时间戳。清洗后字数低于原文 30% 就告警 |
| `align` | 清洗稿 × 课件页 → `Alignment` | 字符 n-gram TF-IDF 计算相似度，再用 Viterbi 求全局最优的翻页序列（见 §6） |
| `write_sections` | 每节（若干连续页 + 对应讲解）→ `SectionNote` | LLM 输出 JSON，用 pydantic 校验，失败时带上错误信息重试一次 |
| `render` | 所有结构化结果 → 三份 Markdown | Jinja2 模板。改排版不需要重新调用 LLM |

`extract_notices` 和 `clean` 互不依赖，可以并发执行；`ingest_slides` 也可以和音频分支并发。

## 5. 数据模型

所有模型都用 pydantic 定义，按概念分文件放在 `domain/` 下（`lecture.py`、`transcript.py`、`slides.py`、`notices.py`、`notes.py`）。下面是核心字段，完整定义以代码为准。

```python
class TranscriptSegment(BaseModel):
    start: float  # 秒
    end: float
    text: str


class Transcript(BaseModel):
    segments: list[TranscriptSegment]


class SlidePage(BaseModel):
    index: int  # 从 1 开始，等于 PDF 页码
    text: str
    image: Path  # 相对 workspace


class Deck(BaseModel):
    pages: list[SlidePage]
    glossary: list[str]


class NoticeKind(StrEnum):
    ATTENDANCE = "attendance"  # 签到、点名
    EXAM = "exam"  # 考试时间、范围、形式
    ASSIGNMENT = "assignment"  # 作业、实验、DDL
    SCHEDULE = "schedule"  # 调课、停课、换教室
    GRADING = "grading"  # 成绩构成
    OTHER = "other"


class Notice(BaseModel):
    kind: NoticeKind
    summary: str  # "Lab2 截止时间改为 11 月 3 日 23:59"
    quote: str  # 原话。ASR 最容易听错数字和日期，必须保留以便核对
    at: float  # 在视频中的时间点
    due: date | datetime | None  # 根据上课日期换算后的绝对时间
    due_phrase: str | None  # 原话中的时间表达："下周三上课前"


class AlignedSpan(BaseModel):
    page: int | None  # None 表示未匹配到任何页（课外拓展、闲聊）
    start: float
    end: float


class Alignment(BaseModel):
    spans: list[AlignedSpan]  # 按时间排序、首尾相接、覆盖整节课


class Cited(BaseModel):
    text: str
    at: float


class SectionNote(BaseModel):
    pages: list[int]
    heading: str
    key_points: list[Cited]  # 课件上有、老师讲到了的内容
    elaborations: list[Cited]  # 老师口头补充、课件上没有的内容
    exam_hints: list[Cited]  # "这个要考"、反复强调的内容
```

## 6. 对齐算法

1. 把清洗后的全文切成约 30 秒一段的窗口 `w_1…w_T`。
2. 状态集合为课件页 `1…N`，再加一个"未匹配"状态 `∅`。
3. 发射分数 = 窗口与页面文本的 TF-IDF 余弦相似度（`analyzer="char_wb"`，`ngram_range=(2,4)`，中英混排不需要分词）。`∅` 的发射分数取常数阈值。
4. 转移分数：停在同一页为 0，前进一页罚分很小，跳页罚分中等，回翻罚分较大。
5. 用 Viterbi 求最优路径，再把相邻的同一状态合并成 `AlignedSpan`。

这部分是纯 numpy 函数，大约 60 行，不涉及 IO。

**评测**：手动标注一节课的真实翻页时间，存为 `tests/fixtures/<课>.alignment.json`。指标是"归属正确的时长占比"，目标 ≥ 85%。如果达不到，下一阶段就引入画面信号：录像里有课件，可以抽取关键帧与课件 PNG 做匹配，加到发射分数里，Viterbi 部分不用改。

## 7. 代码结构

```text
dehydrater/
├── pyproject.toml                # 依赖、ruff、basedpyright、import-linter 配置
├── flake.nix                     # devShell
├── .github/workflows/ci.yml      # 三平台：格式、lint、类型、分层、测试
├── src/dehydrater/
│   ├── domain/                   # §5 的数据模型，以及 timecode 等纯函数
│   ├── ports.py                  # AudioExtractor, SlideReader, Transcriber, ChatModel
│   ├── adapters/
│   │   ├── audio_pyav.py
│   │   ├── slides_pymupdf.py
│   │   ├── asr_volcengine.py     # 豆包语音（私有协议）
│   │   ├── asr_openai_compat.py  # 兼容 OpenAI 的 ASR（Groq 等），备用
│   │   └── llm_openai_compat.py  # 火山方舟、DeepSeek 等兼容 OpenAI 的 LLM
│   ├── pipeline/
│   │   ├── artifacts.py          # 阶段之间传递的产物清单
│   │   ├── workspace.py          # 目录布局、lecture.toml、产物读写
│   │   ├── stage.py              # Stage 基类与 StageContext
│   │   ├── cache.py              # 缓存键计算与命中判断
│   │   ├── runner.py             # 按顺序执行、跳过缓存、汇报事件
│   │   ├── events.py
│   │   ├── lecture.py            # 一节课的处理入口
│   │   └── stages/               # 每个阶段一个文件
│   ├── config.py                 # 渠道与任务配置
│   ├── config.example.toml
│   ├── bootstrap.py              # 组合根：读配置，构造 adapters，注入各阶段
│   └── cli.py
└── tests/
    ├── unit/                     # domain、config，不访问网络
    ├── pipeline/                 # 用假阶段测调度与缓存
    └── adapters/                 # 用合成的音频、PDF 测 adapter
```

后续步骤会新增：`domain/chunking.py`、`align/`（S5）、`pipeline/structured.py`、`prompts/*.j2`、`templates/*.md.j2`（S4）。

**分层规则**（用 import-linter 强制，见 `pyproject.toml`）：

```text
cli → bootstrap → config → pipeline | adapters → ports → domain
```

- 上层可以依赖下层，反之不行；`pipeline` 与 `adapters` 互不依赖。
- `domain`、`ports`、`pipeline` 不得 import `av`、`pymupdf`、`openai`、`httpx`。
- 只有 `bootstrap` 同时引用 `pipeline` 和 `adapters`。

**编码约定**：

- basedpyright 用 strict 模式。
- 依赖一律通过构造函数注入，不用全局状态。
- 第三方库的类型不能越出 adapter 的边界。
- Prompt 写在 `.j2` 文件里，不写在 Python 字符串里。

## 8. 工作区与缓存

```text
L03-进程调度/
├── lecture.toml        # 视频路径、课件路径、上课日期
├── .cache/<stage>/     # 每个阶段一个目录：meta.json（缓存键、token 用量、耗时）+ 产物
├── transcript.md
├── notices.md
├── lecture.md
└── assets/             # 讲义引用的页面图片
```

- 缓存键 = `sha256(阶段名, 阶段版本号, 输入产物的哈希, 相关配置, 所用 prompt 文件的哈希)`。修改 prompt 只会让下游阶段重跑，不会重新调用 ASR。
- LLM 阶段按块缓存。中断后再执行，只会补齐还没完成的块。
- 三份 `.md` 各由一个 `render_*` 阶段生成，每次运行都会覆盖。需要手改的话，请先复制一份。
- `meta.json` 记录 token 用量和耗时，运行结束时打印汇总，用来回答 §1 的问题 5。

## 9. CLI

```bash
dehydrater init L03 --video lecture.mp4 --slides ch3.pdf --date 2026-10-12   # 创建工作区
dehydrater run L03                    # 执行全部阶段（缓存命中的阶段跳过）
dehydrater run L03 --from clean       # 强制从某个阶段开始重跑
dehydrater run L03 --until transcribe # 执行完某个阶段后停止
dehydrater status L03                 # 列出各阶段状态和累计花费
dehydrater config init                # 生成示例配置
dehydrater config check               # 校验配置，检查密钥环境变量（连通性测试在 S2 加入）
```

### 配置：渠道与任务分离

配置文件为 `~/.config/dehydrater/config.toml`，用 platformdirs 定位。配置分两层：

- **渠道（provider）**：一个 API 账号怎么连，包括协议类型、地址、密钥。
- **任务（task）**：每个需要调用 API 的阶段，各自指定用哪个渠道、哪个模型。

```toml
[providers.volc-speech]
kind = "volcengine-asr"
api_key_env = "VOLC_SPEECH_API_KEY"     # 密钥只写环境变量名，不在配置里写明文

[providers.volc-ark]
kind = "openai-compatible"
base_url = "https://ark.cn-beijing.volces.com/api/v3"
api_key_env = "ARK_API_KEY"

[tasks.transcribe]
provider = "volc-speech"
model = "volc.seedasr.auc"              # 火山 ASR 填资源 ID：豆包录音文件识别模型 2.0

[tasks.extract_notices]
provider = "volc-ark"
model = "doubao-seed-2-1-pro-260915"

[tasks.clean]
provider = "volc-ark"
model = "doubao-seed-2-1-pro-260915"

[tasks.write_sections]
provider = "volc-ark"
model = "doubao-seed-2-1-pro-260915"
temperature = 0.3
```

（以上模型名只是示意，以开通后控制台显示的为准。）

实现要点：

- `config.py` 用 pydantic 校验这份配置。`task.provider` 引用了不存在的渠道、或者渠道 `kind` 与任务类型不匹配（例如把 LLM 渠道配给 `transcribe`）时，启动阶段就报错。
- `bootstrap.py` 按 `kind` 为每个任务构造一个 adapter 实例，注入对应的 stage。stage 只看得到 `Transcriber` 或 `ChatModel` 接口，不知道背后是哪家。
- 同一渠道下的多个任务共享一个限流器（S4 加入，届时在渠道配置中增加 `max_concurrency`、`rpm`）。
- 缓存键包含该任务的 `provider + model + 参数`（不包含密钥），所以换渠道或换模型只会重跑受影响的阶段。
- `dehydrater config check` 检查所有任务的渠道是否连得通。

## 10. 依赖

| 用途 | 库 |
| --- | --- |
| 工程 | uv、ruff、basedpyright、import-linter、pytest、pytest-asyncio、respx |
| 数据与配置 | pydantic、pydantic-settings、platformdirs |
| 媒体与文档 | av（PyAV，wheel 自带 FFmpeg）、pymupdf |
| 文本与算法 | numpy、scikit-learn |
| API | openai（所有兼容 OpenAI 的渠道）、httpx（火山 ASR 私有接口）、tenacity（重试）、aiolimiter（限流） |
| 模板与 CLI | jinja2、typer、rich |

PyMuPDF 使用 AGPL 许可，所以项目许可证定为 **AGPL-3.0**。

## 11. 步骤

| 步骤 | 内容 | 完成标准 |
| --- | --- | --- |
| **S0** 骨架 ✅ | 项目结构、工具链、领域模型、`flake.nix`、GitHub Actions | `uv run pytest` 和类型检查全部通过 |
| **S1** ASR 选型 | 用一个脚本抽取音频，从你的课程里截 5 分钟（要有中英混杂和通知），调用火山 ASR 转写，有需要再换其他渠道对比 | 你人工看过结果，选定 ASR |
| **S2** 转写管线 | `config`（渠道与任务）、`workspace`、`cache`、`runner`、`extract_audio`、`transcribe`、CLI 的 `init`/`run`/`status`/`config check` | 一节完整的课得到原始逐字稿；第二次 `run` 时全部命中缓存 |
| **S3** 课件 | `ingest_slides`、术语表，并把术语表回灌到 ASR 提示词 | 对比加入术语表前后的转写结果 |
| **S4** 清洗与通知 | `structured.py`、`clean`、`extract_notices`、两份模板 | **第一次可用**：拿到 `transcript.md` 和 `notices.md` |
| **S5** 对齐 | 手动标注一节课、`similarity`、`viterbi`、评测脚本 | 得到准确率数字，并据此决定要不要做画面对齐 |
| **S6** 讲义 | `write_sections`、`lecture.md.j2` | 一节真实的操作系统课，端到端产出 `lecture.md` |

S6 结束后做一次复盘，逐条回答 §1 的五个问题，再决定下一阶段的范围（UI、画面对齐、课程级通知汇总等）。

## 12. 本阶段不做

UI、本地模型、PPTX、多视频输入、课程级通知汇总与日历导出、PDF 导出、多模态读图、打包分发。
