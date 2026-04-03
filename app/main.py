from contextlib import asynccontextmanager
from typing import AsyncGenerator

from app import web
from app import print
from app.child.models.athlete import Athlete
from app.tournament_main import router
from fastapi.templating import Jinja2Templates
from app.child.router import athlete,  category, kata, kumite
from app.tournament_main.init_db import setup_initial_templates
from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse
from app.core.logger import logger
from app.database import AsyncSessionLocal, engine, get_db, get_t_db

from app.tournament_main.model import Base, Tournament

@asynccontextmanager
async def lifespan(
    app: FastAPI
) -> AsyncGenerator[None, None]:
    """
    Управляет жизненным циклом приложения.
    
    Выполняет инициализацию ресурсов при запуске (создание таблиц) 
    и очистку при завершении работы.
    """
    logger.info("Инициализация базы данных...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        await setup_initial_templates(session)

    logger.info("Приложение API успешно запущено")
    yield

    logger.info("Приложение API завершает работу")
    await engine.dispose()


app = FastAPI(
    title="Karate API",
    description="API для управления соревнованиями",
    version="1.0.0",
    lifespan=lifespan
)


app.include_router(router.router)
app.include_router(athlete.router)
app.include_router(category.router)
app.include_router(kata.router)
app.include_router(kumite.router)
app.include_router(web.router)
app.include_router(print.router)