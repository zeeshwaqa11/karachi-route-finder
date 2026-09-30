import re
from pathlib import Path


def marker_pair(name: str) -> tuple[str, str]:
    return f"<!-- BEGIN:{name} -->", f"<!-- END:{name} -->"


def inject(path: Path, name: str, content: str) -> None:
    begin, end = marker_pair(name)
    text = Path(path).read_text(encoding="utf-8")
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)
    if not pattern.search(text):
        raise ValueError(f"{path} has no {begin} ... {end} block")
    Path(path).write_text(pattern.sub(lambda _: f"{begin}\n{content.strip()}\n{end}", text, count=1), encoding="utf-8")


def markdown_table(headers: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines.extend("| " + " | ".join(str(c) for c in row) + " |" for row in rows)
    return "\n".join(lines)
