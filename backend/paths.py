"""All writable locations. A portable workspace is always an explicit absolute path."""
import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    data: Path
    state: Path
    config: Path
    portable: bool = False

    @classmethod
    def resolve(cls, workspace=None, *, platform=None, env=None, home=None):
        env = os.environ if env is None else env
        platform = sys.platform if platform is None else platform
        home = Path.home() if home is None else Path(home)
        if workspace:
            root = Path(workspace)
            if not root.is_absolute():
                raise ValueError("Portable workspace must be an absolute path")
            return cls(root, root / "state", root / "config", True)
        if platform == "win32":
            root = Path(env.get("LOCALAPPDATA", str(home / "AppData" / "Local"))) / "JOCKY"
            return cls(root, root / "state", root / "config")
        def xdg(key, default):
            value = Path(env.get(key, str(default)))
            if not value.is_absolute():
                raise ValueError(f"{key} must be absolute")
            return value / "jocky"
        return cls(xdg("XDG_DATA_HOME", home / ".local/share"),
                   xdg("XDG_STATE_HOME", home / ".local/state"),
                   xdg("XDG_CONFIG_HOME", home / ".config"))

    @property
    def database(self):
        return self.data / "workstation.sqlite3"

    @property
    def artifacts(self):
        return self.data / "artifacts"

    @property
    def backups(self):
        return self.data / "backups"

    def initialize(self):
        for path in (self.data, self.state, self.config, self.artifacts, self.backups, self.state / "logs"):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Real write probe; permission bits alone are insufficient on removable media.
        import tempfile
        with tempfile.TemporaryFile(dir=self.data) as handle:
            handle.write(b"JOCKY storage probe")
            handle.flush()
            os.fsync(handle.fileno())
