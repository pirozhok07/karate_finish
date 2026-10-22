from collections import defaultdict
from datetime import date, datetime
from http.client import HTTPException
import re
from app.child.models.athlete import Athlete
from app.child.models.category import Category, CategoryKata
from app.child.models.draft import DraftAssignment
from app.child.models.round import Round
from app.child.models.score import Score
from app.child.models.match import Match
from app.child.models.team import Team
from app.child.models.winner import Winner
from app.child.services.logic import find_category_id
from app.child.services.redirect import promote_to_next_round
from app.child.services.service import get_category_winners
from app.core.dependencies import get_current_user_optional, require_admin
from app.tournament_main.model import CategoryTemplate, Tournament
from app.tournament_main.schema import TournamentCreate
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import create_tournament_db, get_db, get_t_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, select, asc, desc, func, extract, update
from sqlalchemy.orm import selectinload
from fastapi.responses import RedirectResponse

router = APIRouter(include_in_schema=False, dependencies=[Depends(require_admin)]) # Скрываем из Swagger (docs)
templates = Jinja2Templates(directory="templates")

# Вспомогательная функция для сборки схемы из формы


@router.get("/view/{tournament_id}/athlete")
async def view_tournament(
    request: Request, 
    tournament_id: int, 
    t_db: AsyncSession = Depends(get_t_db)
):
    # 1. Получаем параметры фильтрации
    params = request.query_params
    search = params.get("search", "").strip().lower()
    club_filter = params.get("club", "")
    age_filter = params.get("age", "")
    sort_by = params.get("sort", "last_name")

    # 2. Загружаем данные из БД
    # Получаем ВСЕХ атлетов (для фильтрации и списка клубов)
    ath_result = await t_db.execute(
        select(Athlete)
        .options(selectinload(Athlete.draft_assignments).selectinload(DraftAssignment.category))
    )
    all_athletes = list(ath_result.scalars().all())

    # Получаем ВСЕ команды с их участниками
    team_result = await t_db.execute(
        select(Team).options(selectinload(Team.members))
    )
    teams = list(team_result.scalars().all())
    # Загружаем категории 
   
    # 3. Фильтрация атлетов (Личников)
    filtered_athletes = all_athletes
    if search:
        filtered_athletes = [a for a in filtered_athletes if search in a.last_name.lower()]
    
    if club_filter:
        filtered_athletes = [a for a in filtered_athletes if a.club == club_filter]
        # Команды тоже фильтруем по клубу
        teams = [t for t in teams if t.club == club_filter]

    if age_filter:
        current_year = date.today().year
        def get_age(birth_date):
            return current_year - birth_date.year

        if "-" in age_filter:
            min_a, max_a = map(int, age_filter.split("-"))
            filtered_athletes = [a for a in filtered_athletes if min_a <= get_age(a.birth_date) <= max_a]
        elif age_filter == "18+":
            filtered_athletes = [a for a in filtered_athletes if get_age(a.birth_date) >= 18]

    # 4. Сортировка атлетов
    if sort_by == "birth_date":
        filtered_athletes.sort(key=lambda x: x.birth_date)
    elif sort_by == "club":
        filtered_athletes.sort(key=lambda x: (x.club or "", x.last_name.lower()))
    else:
        filtered_athletes.sort(key=lambda x: x.last_name.lower())

    for a in filtered_athletes:
        a.categories_data = [
            {"id": d.category.id, "name":d.category.name}
            for d in a.draft_assignments if d.category
        ] or []

    # Сортировка команд (по названию)
    teams.sort(key=lambda x: (x.name or "").lower())

    # 5. Список клубов берем из ПОЛНОГО списка атлетов (чтобы фильтр не "съедал" варианты)
    unique_clubs = sorted(list(set(a.club for a in all_athletes if a.club)))
    

    categories = (await t_db.execute(select(Category))).scalars().all()
    all_categories = defaultdict(list)
    for cat in categories:
        if cat.discipline == "kumite":
            all_categories["kumite"].append(cat.to_dict())
        elif cat.gender == "unisex":
            pass
            # all_categories["group"].append(cat.to_dict())
        else:
            all_categories["kata"].append(cat.to_dict())


    return templates.TemplateResponse("athletes.html", {
        "request": request, 
        "athletes": filtered_athletes,
        "teams": teams, # ОБЯЗАТЕЛЬНО передаем в шаблон
        "t_id": tournament_id,
        "clubs": unique_clubs,
        "all_categories": all_categories,
        "age_categories": ["8-9", "10-11", "12-13", "14-15", "16-17", "18+"]
    })


@router.get("/view/{tournament_id}/kata-change", response_class=HTMLResponse)
async def kata_change(
    request: Request, 
    tournament_id: int, 
    t_db: AsyncSession = Depends(get_t_db)
):
    # Загружаем структуру: Категории -> Круги -> Оценки -> Данные атлета
    result = await t_db.execute(
        select(Category)
        .options(
            # 1. Загружаем цепочку: Категория -> Раунды -> Оценки
            selectinload(Category.rounds)
            .selectinload(Round.scores)
            .options(
                # 2. Внутри оценок подгружаем и атлетов, и команды с их составом
                selectinload(Score.athlete),
                selectinload(Score.team).selectinload(Team.members)
            ),
        )
        .where(Category.discipline == "kata") 
        .order_by(Category.id)
    )
    categories = result.scalars().all()

    categories_data=[]
    for cat in categories:
        first_round = next((r for r in cat.rounds if r.scores), None)
        athletes = []
        if first_round:
            for s in sorted(first_round.scores, key=lambda x: getattr(x, 'position', 0) or 0):
                if s.athlete:
                    athletes.append({
                        "score_id": s.id,
                        "athlete_id": s.athlete_id,
                        "name": (
                            f"{(s.athlete.last_name or '').strip()} " 
                            f"{(s.athlete.first_name or '').strip()} "
                            f"{(s.athlete.middle_name or '').strip()} "
                            ),
                        "club": s.athlete.club or '',
                        "position": getattr(s, 'position', 0) or 0,
                        "is_present": s.athlete.is_present
                    })
        categories_data.append({
            "id": cat.id,
            "name": cat.name,
            "athletes": athletes
        })
    

    return templates.TemplateResponse("kata_change.html", {
        "request": request,
        "categories": categories_data,
        "t_id": tournament_id
    })




@router.post("/view/{tournament_id}/range-athletes")
async def range_athletes(tournament_id: int, t_db: AsyncSession = Depends(get_t_db)):
# 1. Очистка старого черновика
    await t_db.execute(delete(DraftAssignment))

    categories = (await t_db.execute(select(Category))).scalars().all()
    
    # Загружаем всех атлетов и все команды с участниками
    athletes = (await t_db.execute(select(Athlete))).scalars().all()
    teams_res = await t_db.execute(select(Team).options(selectinload(Team.members)))
    teams = teams_res.scalars().all()

    # 1. Распределяем ЛИЧНИКОВ (только в гендерные категории)
    for a in athletes:
        # ВАЖНО: Проверяем, заявлялся ли он в личку (флаг из импорта)
        # Если флага нет в модели, можно убрать это условие или добавить поле в БД
        if a.is_kata:
            # Твоя функция поиска
            cat_id = find_category_id(a, categories)

            t_db.add(DraftAssignment(
                athlete_id=a.id, 
                category_id=cat_id,
                reason="Авто-распределение (личка)"
            ))
        if a.is_kumite:
            # Твоя функция поиска
            cat_id = find_category_id(a, categories, True)
            
            t_db.add(DraftAssignment(
                athlete_id=a.id, 
                category_id=cat_id,
                reason="Авто-распределение (кумите)"
            ))

    # 2. Распределяем КОМАНДЫ
    for team in teams:
        # Команды ищем только в категориях unisex (или командных ката)
        team_cats = [c for c in categories if c.gender == "unisex"]
        
        for cat in team_cats:
            if not team.members:
                continue
                
            # Проверка возраста для ВСЕХ участников группы по году рождения
            # (Все должны попадать в диапазон категории)
            ages = [m.age for m in team.members]
            
            if all(cat.min_age <= age <= cat.max_age for age in ages):
                t_db.add(DraftAssignment(
                    team_id=team.id,
                    category_id=cat.id,
                    reason=f"Авто-распределение (группа)"
                ))

    await t_db.commit()
    return RedirectResponse(url=f"/view/{tournament_id}/categories", status_code=303)

@router.post("/view/{tournament_id}/round/{round_id}/finish-web")
async def finish_round_web(tournament_id: int, round_id: int, t_db: AsyncSession = Depends(get_t_db)):
    await promote_to_next_round(t_db, round_id)
    return RedirectResponse(url=f"/view/{tournament_id}/kata", status_code=303)

@router.post("/view/{tournament_id}/finish_round/{round_id}")
async def finish_round_route(tournament_id: int, round_id: int, t_db: AsyncSession = Depends(get_t_db)):
    result = await promote_to_next_round(t_db, round_id)
    
    if result == "TIE_BREAK_CREATED":
        return {"status": "success", "message": "Обнаружено равенство баллов! Создана переигровка."}
    
    return {"status": "success", "message": "Круг успешно завершен."}


@router.get(
    "/view/{tournament_id}/kumite/{category_id}/change",
    response_class=HTMLResponse,
)
async def view_category_change(
    request: Request,
    category_id: int,
    tournament_id: int,
    t_db: AsyncSession = Depends(get_t_db),
):
    # 1. Категория
    cat = await t_db.get(Category, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Категория не найдена")

    # 2. Матчи этой категории
    res = await t_db.execute(
        select(Match)
        .where(Match.category_id == category_id)
        .order_by(Match.round_number, Match.number)
    )
    matches = res.scalars().all()

    # 3. Все атлеты категории → map {id: "Фамилия Имя"}
    ath_res = await t_db.execute(
        select(Athlete)
        .join(DraftAssignment)
        .where(DraftAssignment.category_id == category_id)
    )
    athletes_map = {
        a.id: f"{(a.last_name or '').strip()} {(a.first_name or '').strip()}".strip()
        for a in ath_res.scalars().all()
    }

    # 4. Группируем по раундам
    bracket_data: dict[int, list] = {}
    for m in matches:
        bracket_data.setdefault(m.round_number, []).append(m.to_dict())

    max_r = max(bracket_data.keys()) if bracket_data else 1

    return templates.TemplateResponse("kumite_change.html", {
        "request": request,
        "category": cat,
        "bracket": bracket_data,
        "athletes": athletes_map,
        "max_round": max_r,
        "t_id": tournament_id,
    })



@router.post("/view/{tournament_id}/all_registr")
async def set_all_present(tournament_id: int, t_db: AsyncSession = Depends(get_t_db)):
    await t_db.execute(
        update(Athlete).values(is_present=True)
    )
    await t_db.commit()
    return {"statue": "success"}