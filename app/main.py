"""
ASGI entry point.

Run the server (from the project folder, D:\\Ask Your Data):
    uvicorn app.main:app --reload            # recommended for development (auto-reload on save)
    python app/main.py                       # same thing, as a plain script
    VS Code: Run and Debug (Ctrl+Shift+D) -> "API server" -> F5

Then open http://localhost:8000.

This module only creates the app object. All wiring lives in `app/api/factory.py` so tests can
build apps with their own settings and fake LLMs via `create_app(settings, llm)`.
"""

import sys
from pathlib import Path

# When run as a script (python app/main.py, or python main.py from inside app/), Python only
# looks in this file's folder. Add the project root so `import app...` works either way.
_ROOT = Path(__file__).resolve().parent.parent
if __package__ in (None, "") and str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.api.factory import create_app  # noqa: E402  (must come after the path fix above)

# The object uvicorn serves. Settings come from environment variables / .env (app/core/config.py).
app = create_app()

__all__ = ["app", "create_app"]


if __name__ == "__main__":
    import uvicorn

    print("Starting Ask Your Data on http://localhost:8000  (Ctrl+C to stop)")
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True, app_dir=str(_ROOT))
