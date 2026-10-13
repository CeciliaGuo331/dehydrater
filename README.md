# dehydrater

把课堂录像或录音（加上可选的 PDF 课件）"脱水"成三份 Markdown：

- `raw.md`：原始逐字稿，每句带时间戳
- `dehydrated.md`：脱水逐字稿，删去口癖、重复、闲聊，修正识别错误
- `notes.md`：课堂笔记，以课件为主线、融入老师讲解，含概览、课堂通知和术语表

当前为 v0.1 功能验证版，只提供 CLI。计划见 [docs/plan-v0.1.md](docs/plan-v0.1.md)。

## 快速上手

```bash
# 安装
uv tool install git+https://github.com/CeciliaGuo331/dehydrater

# 首次使用：填写各项服务的接入地址、模型和 API Key
dehydrater setup        

# 交互式整理一节课
dehydrater         

# 更新
uv tool upgrade dehydrater
```

也可以复制 [`.env.example`](.env.example) 为 `.env` 来配置。脚本用法（`process`、`status`、`check`）、配置细节和常见问题见 **[使用指南](docs/usage.md)**。

## 开发

```bash
uv run ruff format && uv run ruff check   # 格式与 lint
uv run basedpyright                        # 类型检查（strict）
uv run lint-imports                        # 分层约束
uv run pytest
```

## 许可证

AGPL-3.0-or-later
