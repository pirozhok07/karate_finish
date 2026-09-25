from http.client import HTTPException
from typing import AsyncGenerator
from app.tournament_main.model import CategoryKataTemplate, CategoryTemplate, Tournament
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, selectinload
from app.child.models.athlete import Athlete
from app.child.models.category import Category, Kata, CategoryKata
from app.child.models.score import Score
from app.child.models.draft import DraftAssignment
from app.child.models.round import Round
from app.child.models.team import Team

from fastapi import Depends
from sqlalchemy import select

DATABASE_URL = "sqlite+aiosqlite:///./main.db"

engine = create_async_engine(
    DATABASE_URL, 
    connect_args={"check_same_thread": False}
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine, 
    class_=AsyncSession, 
    expire_on_commit=False,
    autoflush=False
)

class Base(DeclarativeBase):
    """
    Базовый класс для всех моделей SQLAlchemy.
    Использует новый стиль DeclarativeBase (SQLAlchemy 2.0+).
    """
    pass

async def get_db()-> AsyncGenerator[AsyncSession, None]:
    """
    Асинхронная зависимость (Dependency Injection) для получения сессии БД.

    Гарантирует закрытие сессии после завершения обработки запроса.

    Yields:
        AsyncSession: Объект асинхронной сессии базы данных.
    """
    async with AsyncSessionLocal() as session:
        yield session



# Функция для инициализации новой БД турнира
async def create_tournament_db(slug: str, main_db: AsyncSession, template_ids: list[int]):
    db_path = f"tournament_{slug}.db"
    new_db_url = f"sqlite+aiosqlite:///{db_path}"
    
    t_engine = create_async_engine(new_db_url)
    
    # 1. Создаем таблицы в новом файле
    import app.child.models as child_models
    async with t_engine.begin() as conn:
        await conn.run_sync(child_models.TournamentBase.metadata.create_all)
    
    # 2. Получаем ТОЛЬКО ВЫБРАННЫЕ шаблоны из основной БД
    result = await main_db.execute(
        select(CategoryTemplate)
                .options(selectinload(CategoryTemplate.kata_associations) # Подгружаем промежуточную таблицу
            .selectinload(CategoryKataTemplate.kata)         # Подгружаем сами объекты Ката
        )
        .where(CategoryTemplate.id.in_(template_ids))
    )
    selected_templates = result.scalars().all()
    
    # 3. Переносим их в новую БД
    if selected_templates:
        t_session_factory = async_sessionmaker(t_engine, expire_on_commit=False)
        async with t_session_factory() as t_session:
            created_katas_cache = {}
            for tmpl in selected_templates:
                new_cat = Category(
                    name=tmpl.name,
                    discipline=tmpl.discipline,
                    # tatami_number=1,
                    min_age=tmpl.min_age,
                    max_age=tmpl.max_age,
                    gender=tmpl.gender,
                    min_weight=tmpl.min_weight,
                    max_weight=tmpl.max_weight
                )
                t_session.add(new_cat)
                await t_session.flush() # Получаем ID новой категории
                # Переносим привязанные КАТА через ассоциации
                for assoc in tmpl.kata_associations:
                    k_tmpl = assoc.kata # Оригинальный объект Ката
                    
                    # 1. Проверяем/создаем само Ката в кэше новой БД
                    if k_tmpl.name not in created_katas_cache:
                        new_kata = Kata(
                            name=k_tmpl.name,
                            min_duration=k_tmpl.min_duration,
                            max_duration=k_tmpl.max_duration,
                            is_advanced=k_tmpl.is_advanced
                        )
                        t_session.add(new_kata)
                        await t_session.flush() # Получаем ID нового ката
                        created_katas_cache[k_tmpl.name] = new_kata
                    
                    # 2. Создаем НОВУЮ связь с сохранением round_limit
                    new_assoc = CategoryKata(
                        category_id=new_cat.id,
                        kata_id=created_katas_cache[k_tmpl.name].id,
                        round_limit=assoc.round_limit # КОПИРУЕМ ЛИМИТ КРУГА
                    )
                    t_session.add(new_assoc)

            await t_session.commit()
    
    await t_engine.dispose()
    return new_db_url


async def get_tournament_session(db_url: str):
    engine = create_async_engine(db_url)
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session() as session:
        try:
            yield session
        finally:
            await engine.dispose() 

# Универсальная зависимость для получения сессии турнира
async def get_t_db(tournament_id: int, main_db: AsyncSession = Depends(get_db)):
    result = await main_db.execute(
        select(Tournament).where(Tournament.id == tournament_id)
    )
    tournament = result.scalar_one_or_none()
    
    if not tournament:
        raise HTTPException(status_code=404, detail=f"Турнир {tournament_id} не найден")
    
    # Открываем сессию к базе этого турнира
    async for t_session in get_tournament_session(tournament.db_path):
        yield t_session