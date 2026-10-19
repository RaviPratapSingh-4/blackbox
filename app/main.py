from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Black Box", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}