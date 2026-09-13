"""Entry point for the bundled JOCKY Flask backend."""
import os

from communication.server import app


if __name__ == "__main__":
    host = os.environ.get("JOCKY_HOST", "127.0.0.1")
    port = int(os.environ.get("JOCKY_PORT", "5000"))
    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)
