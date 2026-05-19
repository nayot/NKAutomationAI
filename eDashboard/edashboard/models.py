from dataclasses import dataclass, field


@dataclass
class CheckResult:
    name: str
    count: int
    items: list[str] = field(default_factory=list)
    error: str | None = None
