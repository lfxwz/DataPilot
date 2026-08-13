"""Application entry point."""

import uvicorn

from datapilot.api import create_app
from datapilot.config import get_settings

app = create_app()


def run() -> None:
    """Run the development server from the installed console script."""

    settings = get_settings()
    uvicorn.run(
        "datapilot.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.environment == "development",
    )


if __name__ == "__main__":
    run()
