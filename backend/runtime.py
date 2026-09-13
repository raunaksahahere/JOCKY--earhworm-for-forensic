"""Packaged entry: private NDJSON stdout bootstrap, authenticated loopback HTTP."""
import argparse
import json
import logging
import logging.handlers
import os
import secrets
import signal
import sys
import threading
import time

from waitress import create_server

from backend.api import create_app
from backend.paths import Paths
from backend.service import Workstation
from backend.storage import Store
from backend.versions import versions


class WorkspaceLock:
    def __init__(self, path):
        self.handle = open(path, "a+b")
        self.handle.seek(0)
        self.handle.write(b"0")
        self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            raise RuntimeError("Workspace is already in use or does not support file locking")

    def close(self):
        self.handle.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", help="Explicit absolute portable workspace; otherwise system user data")
    parser.add_argument("--legacy-ledger", help="Explicit path to migrate after creating a verified backup")
    args = parser.parse_args()
    os.umask(0o077)
    lock = service = server = None
    stop = threading.Event()
    instance = secrets.token_hex(16)
    def emit(event, **data):
        print(json.dumps({"protocol": 1, "event": event, "instance_id": instance, **data}), flush=True)
    emit("started", versions=versions())
    try:
        paths = Paths.resolve(args.workspace)
        paths.initialize()
        lock = WorkspaceLock(paths.data / "workspace.lock")
        handler = logging.handlers.RotatingFileHandler(paths.state / "logs" / "backend.log", maxBytes=1024*1024, backupCount=3, encoding="utf-8")
        logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s")
        store = Store(paths)
        from pathlib import Path
        legacy = Path(args.legacy_ledger) if args.legacy_ledger else Path(__file__).resolve().parent.parent / "data" / "hash_ledger.json"
        if args.legacy_ledger or legacy.exists():
            store.migrate_ledger(legacy)
        service = Workstation(store)
        credential = secrets.token_urlsafe(32)
        app = create_app(service, credential, instance, stop)
        server = create_server(app, host="127.0.0.1", port=0, threads=4, connection_limit=32,
                               max_request_body_size=1024*1024, channel_timeout=30, ident="JOCKY")
        thread = threading.Thread(target=server.run, name="jocky-http", daemon=True)
        thread.start()
        def control():
            # EOF means the owning UI exited, including a crash. No orphan backend.
            for line in sys.stdin:
                try:
                    data = json.loads(line)
                    if data.get("event") == "shutdown" and data.get("instance_id") == instance:
                        break
                except (ValueError, AttributeError):
                    continue
            stop.set()
        threading.Thread(target=control, name="jocky-control", daemon=True).start()
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: stop.set())
        emit("ready", host="127.0.0.1", port=server.effective_port, token=credential, versions=versions(), storage_mode="portable" if paths.portable else "system")
        while not stop.wait(.2):
            if not thread.is_alive():
                raise RuntimeError("HTTP server stopped unexpectedly")
        emit("stopping")
        service.close()
        server.close()
        server.task_dispatcher.shutdown()
        emit("stopped")
        return 0
    except Exception as error:
        # Exception messages may contain sensitive paths; bootstrap only reports type.
        emit("startup_error", error={"code": "startup_failed", "type": type(error).__name__, "message": "Initialization failed. Check workspace permissions, available space, database integrity and existing sessions."})
        return 1
    finally:
        if service:
            service.close()
        if server:
            server.close()
        if lock:
            lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
