from typing import NoReturn

import typer
from rich.console import Console

console = Console(highlight=False)


def fail(message: str) -> NoReturn:
    console.print(f"[red]{message}[/red]")
    raise typer.Exit(1)
