from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import close_pool, init_pool
from app.routers import area
from app.services.ais_stream import start_stream, stop_stream


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    start_stream()
    yield
    stop_stream()
    await close_pool()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(area.router)
