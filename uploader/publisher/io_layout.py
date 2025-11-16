from pathlib import Path


class Layout:
    def __init__(self, out_dir: str):
        self.base = Path(out_dir)
        self.adoc_dir = self.base / "adoc"
        self.events_dir = self.base / "events"
        self.index_dir = self.base / "index"
        self.logs_dir = self.base / "logs"
        self.cache_dir = self.base / "cache"

    def ensure(self) -> None:
        self.base.mkdir(parents=True, exist_ok=True)
        self.adoc_dir.mkdir(parents=True, exist_ok=True)
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)


