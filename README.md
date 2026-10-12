# dehydrater

把课堂录像或录音"脱水"成三份 Markdown：

- `raw.md`：原始逐字稿，每句带时间戳
- `dehydrated.md`：脱水逐字稿，删去口癖、重复、闲聊，修正识别错误
- `guide.md`：导读，包括概览、章节提要、术语表和课堂通知

当前为 v0.1 功能验证版，只提供 CLI。计划见 [docs/plan-v0.1.md](docs/plan-v0.1.md)。

## 使用

```bash
uv sync
uv run dehydrater config init          # 生成 ~/.config/dehydrater/config.toml，按需修改
uv run dehydrater key list             # 每个渠道一把密钥，查看应填的变量名与当前来源
# 填写密钥，三选一：环境变量 / .env 文件 / uv run dehydrater key set <渠道名>（系统钥匙串）
uv run dehydrater config check

uv run dehydrater init L03 -r 录像或录音.mp4 --date 2026-10-12
uv run dehydrater run L03              # 命中缓存的阶段会跳过
uv run dehydrater run L03 --from dehydrate  # 从某个阶段起强制重跑
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
