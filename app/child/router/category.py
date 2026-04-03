from http.client import HTTPException
import random
from typing import Annotated

from app.child.models.athlete import Athlete
from app.child.models.category import Category
from app.child.models.draft import DraftAssignment
from app.child.models.round import Round
from app.child.models.score import Score
from app.child.schemas.category import CategoryRead
from app.child.services.logic import find_category_id
from app.child.services.redirect import run_draft_assignment_logic
from app.child.services.service import generate_all_kumite_horizontal
from app.database import get_db, get_t_db
from app.tournament_main.model import Tournament
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import  selectinload
from fastapi import Depends, APIRouter
from sqlalchemy import select, delete
from fastapi.responses import RedirectResponse

DBSession = Annotated[AsyncSession, Depends(get_t_db)]
DBSession_main = Annotated[AsyncSession, Depends(get_db)]

router = APIRouter(prefix="/{tournament_id}/category", tags=["Category"])

@router.get(
    "/", 
    response_model=list[CategoryRead],
    summary="Получить список категорий"
)
async def list_athletes(t_db: DBSession) -> list[Category]:
    result = await t_db.execute(select(Category))
    return result.scalars().all()

@router.post("/test-assign")
async def test_draft_assignment(
    tournament_id: int,
    main_db: DBSession_main,
    t_db: DBSession
):
    total = await run_draft_assignment_logic(tournament_id, main_db, t_db)
    return {"status": "draft_created", "total_processed": total}

@router.post("/final-assign", response_class=RedirectResponse)
async def final_draft_assignment(
    tournament_id: int,
    t_db: DBSession
):
    # await generate_all_kumite_horizontal(tournament_id, t_db)
    # 1. Чистим боевые таблицы
    await t_db.execute(delete(Score))
    await t_db.execute(delete(Round))

    # 2. Загружаем черновики с подгрузкой атлетов и команд
    result = await t_db.execute(
        select(DraftAssignment)
        .options(selectinload(DraftAssignment.athlete), selectinload(DraftAssignment.team))
        .join(Category)
        .where(Category.discipline == "kata")
        .where(DraftAssignment.category_id != None)
    )
    drafts = result.scalars().all()

    # Фильтруем только ПРИСУТСТВУЮЩИХ (атлет или вся команда)
    active_drafts = []
    for d in drafts:
        if d.athlete and d.athlete.is_present:
            active_drafts.append(d)
        elif d.team and d.team.is_present:
            active_drafts.append(d)

    # Группируем по категориям
    by_category = {}
    for d in active_drafts:
        by_category.setdefault(d.category_id, []).append(d)

    for cat_id, assignments in by_category.items():
        random.shuffle(assignments) # Жеребьевка
        
        new_round = Round(category_id=cat_id, round_number=1)
        t_db.add(new_round)
        await t_db.flush()

        for d in assignments:
            # Создаем Score с привязкой либо к атлету, либо к команде
            new_score = Score(
                round_id=new_round.id,
                athlete_id=d.athlete_id, # Будет None, если это команда
                team_id=d.team_id        # Будет None, если это личник
            )
            t_db.add(new_score)

    await t_db.commit()
    return RedirectResponse(url=f"/view/{tournament_id}/kata", status_code=303)

@router.patch("/draft/{draft_id}")
async def update_draft_category(
    draft_id: int,
    category_id: int | None,
    t_db: DBSession
):
    result = await t_db.execute(select(DraftAssignment).where(DraftAssignment.id == draft_id))
    draft = result.scalar_one_or_none()
    
    if not draft:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    
    draft.category_id = category_id
    draft.reason = "Изменено вручную"
    await t_db.commit()
    return {"status": "updated"}
