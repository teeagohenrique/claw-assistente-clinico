from fastapi import FastAPI

from routers.admin import router as admin_router
from routers.webhook import router as webhook_router

app = FastAPI(
    title="Assistente Clínico Cláudio (Claw) - API",
    description="Backend FastAPI - Continuidade Terapêutica (Dr. Responsável)",
    version="6.2.0",
)

app.include_router(webhook_router)
app.include_router(admin_router)


@app.get("/")
async def status_servidor():
    return {
        "status": "online",
        "servico": "Assistente Clínico Cláudio (Claw)",
        "versao": "6.2.0",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
