# dehydrater

把课堂录像和 PDF 课件"脱水"成三份 Markdown：

- `transcript.md`：去掉口癖、修正术语、带时间戳的逐字稿
- `notices.md`：签到、考试、作业 DDL、调课等课堂通知
- `lecture.md`：按课件页组织的讲义

当前为 v0.1 功能验证版，只提供 CLI。计划见 [docs/plan-v0.1.md](docs/plan-v0.1.md)。

## 使用

```bash
uv sync
uv run dehydrater config init          # 生成 ~/.config/dehydrater/config.toml，按需修改
export ARK_API_KEY=...                 # 配置文件中 api_key_env 指定的环境变量
export VOLC_SPEECH_API_KEY=...
uv run dehydrater config check

uv run dehydrater init L03 --video lecture.mp4 --slides ch3.pdf --date 2026-10-12
uv run dehydrater run L03              # 命中缓存的阶段会跳过
uv run dehydrater run L03 --from clean # 从某个阶段起强制重跑
uv run dehydrater run L03 --until transcribe
uv run dehydrater status L03
```

NixOS 用户可以用 `nix develop` 进入开发环境。

## 开发

```bash
uv run ruff format && uv run ruff check   # 格式与 lint
uv run basedpyright                        # 类型检查（strict）
uv run lint-imports                        # 分层约束
uv run pytest
```

## 许可证

AGPL-3.0-or-later
