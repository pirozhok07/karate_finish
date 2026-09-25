from datetime import date
from typing import Annotated
from app.child.models.category import Category
from app.child.models.draft import DraftAssignment
from app.child.models.team import Team
from app.child.schemas.athlete import AthleteBase, AthleteCreate, AthleteRead, AthleteUpdate
from app.child.models.athlete import Athlete
from app.child.services.excel import parse_athletes_excel
from app.child.services.logic import find_category_id, sync_team_presence
from app.database import create_tournament_db, get_db, get_t_db, get_tournament_session
from app.tournament_main.model import Tournament
from app.tournament_main.schema import TournamentCreate, TournamentRead
from fastapi import APIRouter, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends, UploadFile, File
from sqlalchemy import select
from sqlalchemy.orm.attributes import set_committed_value
import re
from fastapi.responses import RedirectResponse

DBSession = Annotated[AsyncSession, Depends(get_t_db)]
UpFile = Annotated[UploadFile, File(...)]

router = APIRouter(prefix="/{tournament_id}/athletes", tags=["Athlete"])
    
@router.post(
    "/",
    response_model=AthleteRead,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить спортсмена"
)
async def add_athlete(
    athlete_data: AthleteCreate, 
    t_db: DBSession
) -> Athlete:
    # .model_dump() превращает схему со всеми полями (фамилия, дата рождения и т.д.) в словарь.
    # Распаковка ** позволяет передать их в конструктор модели одной строкой.
    new_athlete = Athlete(**athlete_data.model_dump())
    
    try:
        t_db.add(new_athlete)
        await t_db.commit()
        await t_db.refresh(new_athlete)
        return new_athlete
    except Exception as e:
        await t_db.rollback()
        raise HTTPException(status_code=400, detail=f"Ошибка сохранения: {str(e)}")

@router.get(
    "/", 
    response_model=list[AthleteRead],
    summary="Получить список спортсменов"
)
async def list_athletes(t_db: DBSession) -> list[Athlete]:
    result = await t_db.execute(select(Athlete))
    return result.scalars().all()

@router.put(
    "/{athlete_id}", 
    response_model=AthleteRead,
    summary="Обновить данные спортсменов"
)
async def update_athlete(
    athlete_id: int,
    athlete_data: AthleteUpdate,
    t_db: DBSession
) -> Athlete:
    # 1. Находим атлета
    athlete = await t_db.get(Athlete, athlete_id)
    if not athlete:
        raise HTTPException(status_code=404, detail="Athlete not found")
    print(athlete_data)
    update_date = athlete_data.model_dump(exclude_unset=True, exclude_none=True)
    for key, value in update_date.items():
        if hasattr(athlete, key):
            setattr(athlete, key, value)
    # 2. Обновляем статус
    
    # 3. Синхронизация команд (ваша логика)
    updated_teams = await sync_team_presence(t_db, athlete_id) 
    team_statuses = {t.id: t.is_present for t in updated_teams}

    await t_db.commit()
    await t_db.refresh(athlete)

    # 4. Собираем ПОЛНЫЙ ответ
    # Превращаем объект SQLAlchemy в словарь и добавляем недостающие поля
    response_data = {
        **athlete.__dict__,  # Тут будут id, last_name, first_name и т.д.
        "status": "success",
        "team_statuses": team_statuses
    }
    
    return response_data

@router.delete(
    "/{athlete_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить спортсмена по ID"
)
async def delete_athlete(
    athlete_id: int,
    t_db: DBSession
) -> None:
    # 1. Ищем атлета, чтобы убедиться, что он существует
    result = await t_db.execute(select(Athlete).where(Athlete.id == athlete_id))
    athlete = result.scalar_one_or_none()
    
    if not athlete:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=f"Спортсмен с ID {athlete_id} не найден в этом турнире"
        )

    # 2. Удаляем
    try:
        await t_db.delete(athlete)
        await t_db.commit()
        # При 204 No Content тело ответа не возвращается
        return None
    except Exception as e:
        await t_db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Ошибка при удалении: {str(e)}"
        )
    

@router.post("/upload-excel")
async def upload_athletes_from_excel(
    tournament_id: int,
    file: UpFile,
    t_db: DBSession
):
    try:
        content = await file.read()
        all_athletes, teams_dict = parse_athletes_excel(content)
        # 1. Сохраняем атлетов
        for a in all_athletes:
            t_db.add(a)
        await t_db.flush() 

        # 3. Создание и привязка КОМАНД
        for t_info in teams_dict.values():
            members_objs = t_info["members"]
            
            if len(members_objs) >= 2:
                first_member = members_objs[0]
                
                new_team = Team(
                    name=t_info["name"],
                    club=first_member.club
                )
                
                # ХАК ДЛЯ ASYNC: Говорим SQLAlchemy, что коллекция members пустая и её не надо грузить из БД
                set_committed_value(new_team, 'members', [])
                
                t_db.add(new_team)
                await t_db.flush() 

                # Теперь append сработает без обращения к базе
                for m in members_objs:
                    new_team.members.append(m)
                
                await t_db.flush()
        
        await t_db.commit()
        return RedirectResponse(url=f"/view/{tournament_id}/athlete", status_code=303)
    
    except Exception as e:
        await t_db.rollback()
        print(f"ОШИБКА: {e}")
        raise HTTPException(status_code=500, detail=str(e))