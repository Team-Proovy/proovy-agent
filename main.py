"""Development server runner."""

import os

import uvicorn


def main() -> None:
    """Run the FastAPI development server."""
    host = os.getenv("UVICORN_HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("UVICORN_RELOAD", "true").lower() == "true"

    uvicorn.run("proovy_agent.app.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
