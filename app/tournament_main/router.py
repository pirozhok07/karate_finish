from datetime import date
from typing import Annotated
from app.database import create_tournament_db, get_db
from app.tournament_main.model import CategoryTemplate, Tournament
from app.tournament_main.schema import CategoryTemplateRead, TournamentCreate, TournamentRead
from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import Depends
import re

DBSession = Annotated[AsyncSession, Depends(get_db)]

router = APIRouter(prefix="/tournaments", tags=["Tournament"])

# @router.post("/")
# async def create_tournament(name: str, db: AsyncSession = Depends(get_db)):
#     # 1. Создаем отдельную БД и таблицу атлетов в ней
#     new_db_path = await create_tournament_db(name.replace(" ", "_").lower())
    
#     # 2. Сохраняем метаданные в основную БД
#     new_tournament = Tournament(name=name, date ="2026-10-10", db_path=new_db_path)
#     db.add(new_tournament)
#     await db.commit()
#     await db.refresh(new_tournament)
    
#     return {"status": "success", "tournament_id": new_tournament.id, "db": new_db_path}

@router.post("/", response_model=TournamentRead)
async def create_tournament(
    item: TournamentCreate, 
    db: DBSession
):
    # 1. Генерируем путь к БД из заголовка
    slug = re.sub(r'\W+', '_', item.title).lower()
    new_db_url = await create_tournament_db(slug, db, item.template_ids)
    
    # 2. Создаем запись в реестре
    new_tournament = Tournament(
        title=item.title,
        type=item.type,
        description=item.description,
        event_date=item.event_date,
        judge=item.judge,
        secretary=item.secretary,
        db_path=new_db_url
    )
    
    db.add(new_tournament)
    await db.commit()
    await db.refresh(new_tournament)
    
    return new_tournament

async def add_templates(db: DBSession) -> None:
    result = await db.execute(select(CategoryTemplate))
    if not result.scalars().first():
        from app.tournament_main.template import CATEGORIES
        for cat in CATEGORIES:
            db.add(CategoryTemplate(**cat))
        await db.commit()

@router.get(
    "/templates", 
    response_model=list[CategoryTemplateRead],
    summary = "Список шаблонов категории"
)
async def get_category_templates(db: DBSession):
    """
    Возвращает список всех доступных шаблонов категорий из основной БД.
    Используется пользователем перед созданием турнира.
    """
    result = await db.execute(select(CategoryTemplate).order_by(CategoryTemplate.id))
    templates = result.scalars().all()
    return templates

