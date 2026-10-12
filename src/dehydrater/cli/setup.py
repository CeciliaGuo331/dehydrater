"""`dehydrater setup`：逐个任务询问接入地址、模型和 API Key，验证后帮用户保存。"""

import asyncio
import logging

from dehydrater.bootstrap import load_settings
from dehydrater.cli.console import console
from dehydrater.cli.display import describe
from dehydrater.cli.prompts import Ask, terminal_ask
from dehydrater.cli.shell_profile import ShellProfile, detect_shell, write_env_file
from dehydrater.config import Field, Settings, Task, default_value, env_name, user_env_file
from dehydrater.service import verify_task

logger = logging.getLogger(__name__)


def run_setup(ask: Ask = terminal_ask, shell: ShellProfile | None = None) -> None:
    current = load_settings()
    console.print("设置 dehydrater。方括号内为默认值，直接回车即采用。")
    values: dict[str, str] = {}
    for number, task in enumerate(Task, start=1):
        console.print(f"\n[bold][{number}/{len(Task)}] {task.label}[/bold]")
        values |= _ask_task(ask, current, task, values)
    _persist(ask, values, shell or detect_shell())


def _ask_task(ask: Ask, current: Settings, task: Task, earlier: dict[str, str]) -> dict[str, str]:
    while True:
        answers: dict[str, str] = {}
        for field in Field:
            answers[env_name(task, field)] = _ask_field(
                ask, current, task, field, {**earlier, **answers}
            )
        error = _verify(Settings({**earlier, **answers}, []), task)
        if error is None:
            console.print("  [green]✓ 验证通过[/green]")
            return answers
        console.print(f"  [red]✗ 验证失败：{describe(error)}[/red]")
        # 必须在"验证中"的动画结束之后再提问，否则动画会不断覆盖提问所在的行
        if not ask("  重新输入这一项？(Y/n)", default="y").lower().startswith("y"):
            return answers


def _verify(settings: Settings, task: Task) -> Exception | None:
    with console.status("验证中……"):
        try:
            asyncio.run(verify_task(settings, task))
        except Exception as error:  # 网络、鉴权等各种失败都只需要告诉用户
            logger.exception("验证 %s 失败", task)
            return error
    return None


def _ask_field(
    ask: Ask, current: Settings, task: Task, field: Field, earlier: dict[str, str]
) -> str:
    label = {
        Field.URL: "接入地址",
        Field.MODEL: "资源 ID" if task == Task.TRANSCRIBE else "模型/接入点 ID",
        Field.KEY: "API Key",
    }[field]
    default = _default_for(current, task, field, earlier)
    while True:
        answer = ask(f"  {label}", default=default, secret=field == Field.KEY)
        if answer:
            return answer
        console.print(f"  [red]{label}不能为空[/red]")


def _default_for(current: Settings, task: Task, field: Field, earlier: dict[str, str]) -> str:
    """优先沿用已有设置；其次沿用之前同地址任务的 Key；最后是内置默认值。

    earlier 包含之前各任务以及本任务已回答的项。
    """
    existing = current.lookup(task, field)
    if existing and existing.source != "默认值":
        return existing.value
    if field == Field.KEY:
        url = earlier.get(env_name(task, Field.URL))
        for other in Task:
            if other != task and earlier.get(env_name(other, Field.URL)) == url:
                return earlier.get(env_name(other, Field.KEY), "")
        return ""
    return default_value(task, field) or ""


def _persist(ask: Ask, values: dict[str, str], shell: ShellProfile) -> None:
    env_file = user_env_file()
    options: list[tuple[str, str]] = []
    if shell.path:
        options.append(("rc", f"写入 {shell.path}（检测到你使用 {shell.name}）"))
    options.append(("env", f"保存到 {env_file}（仅本人可读，立即生效）"))
    options.append(("show", "只显示配置片段，我自己复制"))

    console.print("\n设置完成。请选择保存方式：")
    for number, (_, text) in enumerate(options, start=1):
        console.print(f"  {number}) {text}")
    while True:
        answer = ask("选择", default="1")
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            break
        console.print(f"[red]请输入 1–{len(options)}[/red]")

    match options[int(answer) - 1][0]:
        case "rc":
            shell.install(values)
            console.print(f"[green]✓ 已写入 {shell.path}[/green]")
            console.print(f"  执行 [bold]source {shell.path}[/bold] 或打开新终端后生效。")
            console.print("  注意：其中的 API Key 是明文，请勿把这个文件分享给他人。")
        case "env":
            write_env_file(env_file, values)
            console.print(f"[green]✓ 已保存到 {env_file}[/green]")
            console.print("  注意：已设置的同名环境变量和当前目录的 .env 优先于这个文件。")
        case _:
            console.print("\n把下面的内容加入 shell 启动文件（如 ~/.bashrc、~/.zshrc）：\n")
            console.print(shell.snippet(values), markup=False)
