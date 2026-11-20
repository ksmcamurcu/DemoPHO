import os

import uvicorn
from fastapi import FastAPI

from app.providers import DemoChatProvider
from app.routers import (
    appointments,
    capabilities,
    chat,
    experiments,
    learning,
    memories,
    products,
)
from app.store import MemoryStore


def create_app() -> FastAPI:
    application = FastAPI(
        title="DemoPHO API",
        description="DemoPHO için kimlik doğrulamasız, bellek içi API demosu.",
        version="0.1.0",
    )
    application.state.store = MemoryStore()
    application.state.chat_provider = DemoChatProvider()
    for router in (
        chat.router,
        memories.router,
        learning.router,
        capabilities.router,
        products.router,
        appointments.router,
        experiments.router,
    ):
        application.include_router(router, prefix="/api/v1")

    @application.get("/health", tags=["Sistem"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()


def main() -> None:
    host = os.getenv("DEMO_PHO_HOST", "127.0.0.1")
    port = int(os.getenv("DEMO_PHO_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
