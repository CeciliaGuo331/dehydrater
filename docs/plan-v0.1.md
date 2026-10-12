# dehydrater v0.1 计划书：CLI 功能验证版

## 1. 目标

用一个命令行工具，把**一节课的录像或录音**处理成三份 Markdown：

| 产物 | 内容 |
| --- | --- |
| `raw.md` | 原始逐字稿：语音识别原文，每句带时间戳 |
| `dehydrated.md` | 脱水逐字稿：删去口癖、重复、闲聊，修正识别错误，合并成自然段，每段带时间戳 |
| `guide.md` | 导读：概览、按时间排列的章节提要、术语表、课堂通知 |

本阶段要回答的问题：

1. 中英混杂的课堂录音，火山 ASR 的准确率够不够用？
2. 脱水时会不会删掉有用信息？
3. 导读能不能帮人快速决定该回看哪一段？课堂通知能不能抓全？
4. 处理一节课要花多少钱、多长时间？

## 2. 约束

- **不在本地跑任何模型**：ASR 和 LLM 全部走 API，本地只做解码这类 CPU 工作。
- 只做 CLI，交互保持最简单。
- 一次只处理一节课，输入是一个带音轨的音视频文件（录像或录音，任意常见格式）。
- 代码可读性优先：分层清晰，有类型，可测试。

## 3. API

测试阶段统一使用**火山引擎**，ASR 和 LLM 是两个产品，分别开通：

| 用途 | 服务 | 说明 |
| --- | --- | --- |
| ASR | **豆包语音**：录音文件识别标准版，默认 2.0（`volc.seedasr.auc`，0.8 元/小时），1.0（`volc.bigasr.auc`，2.3 元/小时）备用 | 返回毫秒级分句时间戳，提交任务后轮询结果。文档只列出音频 URL，但**实测 `audio.data` 内联 base64 可用**，无需对象存储。极速版也已实现，开通后设 `api = "flash"` 即可切换 |
| LLM | **火山方舟**：脱水用 `doubao-seed-2-1-lite`，导读用 `doubao-seed-2-1-pro` | 兼容 OpenAI 接口。豆包模型**默认开启深度思考**，实测一句话的回答要 40 秒、1900 个推理 token；配置中用 `extra_body = { thinking = { type = "disabled" } }` 关闭 |

每个任务的渠道、模型都可单独配置（见 §8）。

## 4. 处理流程

```text
录像/录音 ──► extract_audio ──► transcribe ──┬──► render_raw ──────────► raw.md
                                             │
                                             └──► dehydrate ──┬──► render_dehydrated ──► dehydrated.md
                                                              │
                                                              └──► write_guide ──► render_guide ──► guide.md
```

| 阶段 | 输入 → 输出 | 实现要点 |
| --- | --- | --- |
| `extract_audio` | 录像或录音 → 16kHz 单声道 MP3（32kbps） | PyAV 解码，任何带音轨的格式都可以（mp4、ts、mkv、m4a、wav……）。2 小时约 29MB |
| `transcribe` | 音频 → `Transcript`（原始分句） | 火山 ASR，分句时间戳精确到毫秒 |
| `dehydrate` | 原始分句 → `Transcript`（自然段） | 按约 2500 字分块并发调用 LLM。**模型只返回"第几句到第几句合并成一段"和改写后的文字，时间戳由原始分句推出**，不让模型编造时间。脱水后字数低于原文 30% 时告警 |
| `write_guide` | 脱水稿 → `Guide` | 整节课一次调用。同样只让模型引用段落编号，时间由编号换算 |
| `render_*` | 结构化产物 → Markdown | Jinja2 模板。改排版不需要重新调用 LLM；每份输出各一个阶段，产出后立即可读 |

LLM 的输出一律是 JSON，用 pydantic 校验格式，再做业务校验（编号是否越界、是否按顺序）。不合格时把错误告诉模型，让它重写一次（`pipeline/structured.py`）。

## 5. 数据模型

所有模型都用 pydantic 定义，按概念分文件放在 `domain/` 下，完整定义以代码为准。

```python
class Lecture:            # lecture.toml 的内容
    title: str
    date: date            # 上课日期
    recording: SourceFile # 录像或录音；大小和修改时间参与缓存键

class Transcript:
    segments: list[TranscriptSegment]   # start、end（秒）、text
    # 原始逐字稿中一个 segment 是一句话；脱水稿中是一个自然段

class Guide:
    overview: str
    sections: list[GuideSection]        # title、start（秒）、summary、key_points
    key_terms: list[GuideTerm]          # term、explanation
    notices: list[GuideNotice]          # text、at（秒）
```

## 6. 代码结构

```text
dehydrater/
├── pyproject.toml                # 依赖、ruff、basedpyright、import-linter 配置
├── flake.nix                     # devShell
├── .github/workflows/ci.yml      # 三平台：格式、lint、类型、分层、测试
├── src/dehydrater/
│   ├── domain/                   # 数据模型与纯函数（timecode、chunking）
│   ├── ports.py                  # AudioExtractor, Transcriber, ChatModel
│   ├── adapters/
│   │   ├── audio_pyav.py
│   │   ├── asr_volcengine.py     # 豆包语音（私有协议）
│   │   ├── asr_openai_compat.py  # 兼容 OpenAI 的 ASR，备用
│   │   ├── llm_openai_compat.py  # 火山方舟等兼容 OpenAI 的 LLM
│   │   └── keychain_keyring.py   # 系统钥匙串
│   ├── pipeline/
│   │   ├── artifacts.py          # 阶段之间传递的产物清单
│   │   ├── workspace.py          # 目录布局、lecture.toml、产物读写
│   │   ├── stage.py              # Stage 基类与 StageContext
│   │   ├── cache.py              # 阶段级缓存
│   │   ├── memo.py               # 块级缓存：阶段内每次 LLM 调用各自落盘
│   │   ├── structured.py         # LLM → JSON → 校验 → 不合格重试
│   │   ├── templating.py         # Jinja2 模板加载与摘要
│   │   ├── runner.py             # 按顺序执行、跳过缓存、汇报事件
│   │   ├── events.py
│   │   ├── lecture.py            # 一节课的处理入口
│   │   └── stages/               # 每个阶段一个文件
│   ├── prompts/*.j2              # LLM 提示词，只放文本
│   ├── templates/*.md.j2         # Markdown 输出模板
│   ├── config.py                 # 渠道与任务配置
│   ├── config.example.toml
│   ├── credentials.py            # 密钥查找
│   ├── bootstrap.py              # 组合根：读配置，构造 adapters，注入各阶段
│   └── cli.py
└── tests/
    ├── unit/                     # domain、config、模板，不访问网络
    ├── pipeline/                 # 调度、缓存；用预设回复的假模型测 LLM 阶段
    └── adapters/                 # 合成音频；模拟 HTTP 服务
```

**分层规则**（import-linter 强制，见 `pyproject.toml`）：

```text
cli → bootstrap → config → pipeline | adapters → credentials → ports → domain
```

- 上层可以依赖下层，反之不行；`pipeline` 与 `adapters` 互不依赖。
- `domain`、`ports`、`pipeline` 不得 import `av`、`openai`、`httpx`、`keyring`。

**编码约定**：basedpyright strict；依赖一律构造函数注入，无全局状态；第三方库的类型不越出 adapter；提示词写在 `.j2` 文件里。

## 7. 工作区与缓存

```text
L03/
├── lecture.toml        # 录音路径、标题、上课日期（用户可编辑）
├── .cache/
│   ├── artifacts/      # 各阶段产物（JSON）
│   ├── stages/         # 各阶段缓存元数据：缓存键、耗时、token 用量
│   └── files/          # 音频、LLM 分块结果等中间文件
├── raw.md
├── dehydrated.md
└── guide.md
```

- 缓存键 = `sha256(阶段名, 版本号, 输入产物的摘要, 模型与参数, 提示词模板的摘要)`。改提示词只重跑下游 LLM 阶段，不会重新转写。
- 脱水按块缓存：中断后再执行，只补齐没完成的块；`--from dehydrate` 强制重跑时，内容和参数都没变的块直接复用。
- 三份 `.md` 每次运行都会覆盖。需要手改的话，请先复制一份。

## 8. CLI、配置与密钥

```bash
dehydrater init L03 -r 录像.ts --date 2026-09-30   # 创建工作区
dehydrater run L03                    # 执行全部阶段（缓存命中的跳过）
dehydrater run L03 --from dehydrate   # 从某阶段起强制重跑
dehydrater run L03 --until transcribe # 执行完某阶段后停止
dehydrater status L03                 # 各阶段状态、耗时、token 用量
dehydrater config init | check        # 生成示例配置 / 校验配置与密钥
dehydrater key list | set | unset     # 管理各渠道的密钥
```

**配置**（`~/.config/dehydrater/config.toml`）分两层：渠道（怎么连接一个 API 账号，每个渠道一把密钥）和任务（`transcribe`、`dehydrate`、`guide` 各用哪个渠道、模型、参数）。示例配置为每个任务单独定义了一个渠道；想共用密钥时让任务指向同一个渠道即可。

**密钥**按渠道名查找：环境变量 `DEHYDRATER_KEY_<渠道名>` → 当前目录向上的 `.env` → 配置目录下的 `.env` → 系统钥匙串（`key set` 写入）。`run` 和 `config check` 在开始前列出所有缺密钥的渠道。

## 9. 依赖

| 用途 | 库 |
| --- | --- |
| 工程 | uv、ruff、basedpyright、import-linter、pytest、pytest-asyncio |
| 数据、配置、密钥 | pydantic、platformdirs、keyring、python-dotenv |
| 媒体 | av（PyAV，wheel 自带 FFmpeg） |
| API | openai（兼容 OpenAI 的渠道，自带重试）、httpx（火山 ASR） |
| 模板与 CLI | jinja2、typer、rich |

## 10. 步骤

| 步骤 | 内容 | 完成标准 |
| --- | --- | --- |
| **S0** 骨架 ✅ | 项目结构、工具链、CI | 测试和类型检查全部通过 |
| **S1** 转写 ✅ | 音频抽取（兼容录像与录音）、火山 ASR、密钥管理、`raw.md` | 一节真实的课得到原始逐字稿 |
| **S2** 脱水与导读 | `dehydrate`、`write_guide`、三份模板 | 一节真实的课端到端产出三份 Markdown |
| **S3** 评估 | 人工通读一节课的三份产出，对比 ASR 2.0 与 1.0，调提示词 | 逐条回答 §1 的四个问题 |

## 11. 后续阶段（本阶段不做）

- 课件：读取 PDF，抽取术语表作为 ASR 热词和 LLM 纠错依据；ASR 2.0 还支持把课件图片作为上下文
- 讲义：把讲解对齐到课件页（文本相似度 + Viterbi，可融合画面信号），按页生成笔记
- 课程级汇总：跨讲次的通知清单、日历导出
- UI、打包分发

设计思路见 `docs/design.md`（备忘录，非当前计划）。
