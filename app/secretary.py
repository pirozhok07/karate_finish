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
from app.core.dependencies import get_current_user_optional, require_admin, require_secretary_or_admin
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

router = APIRouter(include_in_schema=False, dependencies=[Depends(require_secretary_or_admin)]) # Скрываем из Swagger (docs)
templates = Jinja2Templates(directory="templates")

@router.get("/view/{tournament_id}", response_class=HTMLResponse)
async def index_page(
    request: Request, 
    tournament_id: int, 
    user = Depends(get_current_user_optional),
    t_db: AsyncSession = Depends(get_t_db),
    main_db: AsyncSession = Depends(get_db)):

    if not user:
        return RedirectResponse(url=f"/{tournament_id}/auth", status_code=303)
    # Загружаем турнир
    tournament = await main_db.get(Tournament, tournament_id)
    
    result = await t_db.execute(select(Category))
    categories = result.scalars().all()

    # Считаем количество записей в таблице Athlete для конкретного турнира
    result = await t_db.execute(
        select(func.count(Athlete.id)).where(Athlete.is_present == True)
    )
    present_count = result.scalar() or 0

    # Считаем количество записей в таблице Athlete для конкретного турнира
    result = await t_db.execute(
        select(func.count(Athlete.id))
    )
    total_athletes = result.scalar() or 0

    # Считаем количество записей в таблице Category для конкретного турнира
    result = await t_db.execute(
        select(func.count(Category.id)))
    total_clubs = result.scalar() or 0

    return templates.TemplateResponse("tournament.html", {
        "request": request, 
        "tournament": tournament,
        "athletes_count": total_athletes,  # Общее кол-во участников
        "present_count": present_count, 
        "clubs_count": total_clubs,        # Кол-во уникальных клубов
        "completion_rate": 50,
        "categories": categories
    })



@router.get("/view/{tournament_id}/categories", response_class=HTMLResponse)
async def view_categories(
    request: Request, 
    tournament_id: int, 
    t_db: AsyncSession = Depends(get_t_db),
    main_db: AsyncSession = Depends(get_db),
):
    # 2. Загружаем категории с полной подгрузкой атлетов и команд
    result = await t_db.execute(
        select(Category).options(
            selectinload(Category.draft_assignments).options(
                selectinload(DraftAssignment.athlete),
                selectinload(DraftAssignment.team).selectinload(Team.members)
            )
        )
    )
    # .unique() важен при использовании нескольких selectinload
    categories = result.scalars().all()
    categories_with_discipline = defaultdict(list)

    # 3. СОРТИРОВКА В PYTHON (решает проблему с None в шаблоне)
    for cat in categories:
        cat.draft_assignments.sort(
            key=lambda d: (
                # Сначала проверяем атлета, если его нет — проверяем команду
                (d.athlete.is_present if d.athlete else (d.team.is_present if d.team else False))
            ),
            reverse=True
        )
        # подсчет человек явившихся
        count_present = 0
        for it in cat.draft_assignments:
            person = it.athlete if it.athlete else it.team
            if person.is_present:
                count_present +=1
        data = {
            "category": cat, 
            "count_present":count_present
        }
        if cat.gender == "unisex":
            discipline = "group"
        else:
            discipline = cat.discipline
        categories_with_discipline[discipline].append(data)

    # 4. Нераспределенные
    unassigned_res = await t_db.execute(
        select(DraftAssignment)
        .where(DraftAssignment.category_id == None)
        .options(selectinload(DraftAssignment.athlete))
    )
    unassigned = unassigned_res.scalars().all()
    
    return templates.TemplateResponse("categories.html", {
        "request": request,
        "categories": categories_with_discipline,
        "unassigned": unassigned,
        "t_id": tournament_id
    })

@router.get("/view/{tournament_id}/registration", response_class=HTMLResponse)
async def registration_page(
    request: Request, 
    tournament_id: int, 
    t_db: AsyncSession = Depends(get_t_db)
):
    # Сортируем по фамилии для удобства поиска в списке
    result = await t_db.execute(
        select(Athlete)
        .options(
            selectinload(Athlete.draft_assignments).selectinload(DraftAssignment.category),
            selectinload(Athlete.team).selectinload(Team.draft_assignments).selectinload(DraftAssignment.category)
        )
    )
    athletes = result.scalars().all()
    result = await t_db.execute(select(Team).options(selectinload(Team.members)))
    teams = result.scalars().all()
    
    unique_clubs = sorted(list(set(a.club for a in athletes if a.club)))
    return templates.TemplateResponse("registration.html", {
        "request": request,
        "athletes": athletes,
        "teams": teams,
        "clubs": unique_clubs,
        "t_id": tournament_id
    })

@router.get("/view/{tournament_id}/kata", response_class=HTMLResponse)
async def kata_page(
    request: Request, 
    tournament_id: int, 
    t_db: AsyncSession = Depends(get_t_db)
):
    result = await t_db.execute(
        select(Category).options(selectinload(Category.rounds).selectinload(Round.scores))
        .where(Category.discipline == "kata") 
    )
    categories = result.scalars().all()

    data = defaultdict(list)
    for category in categories:
        if category.rounds and category.rounds[0].scores:
            data[category.tatami_number].append(category.to_dict())

    return templates.TemplateResponse("kata_nav.html",{
        "request": request,
        "categories": data,
        "tournament_id": tournament_id,
    })



@router.get("/view/{tournament_id}/kata/all/{tatami_number}", response_class=HTMLResponse)
async def get_kata_page(
    tatami_number: int, 
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
            # 3. Подгружаем справочник КАТА для выпадающих списков
            selectinload(Category.kata_associations).selectinload(CategoryKata.kata)
        )
        .where(Category.discipline == "kata", Category.tatami_number == tatami_number) 
        .order_by(Category.id)
    )
    categories = result.scalars().all()

    used_katas = {}

    for category in categories:
        for round in category.rounds:
            for score in round.scores:
                if score.athlete_id:
                    athlete_id = score.athlete_id 
                    if athlete_id:
                        if athlete_id not in used_katas:
                            used_katas[athlete_id] = set()
                        if score.performance_kata:
                            used_katas[athlete_id].add(score.performance_kata)
    

    return templates.TemplateResponse("kata.html", {
        "request": request,
        "categories": categories,
        "t_id": tournament_id,
        "used_katas": used_katas
    })

@router.get("/view/{tournament_id}/kata/{category_id}", response_class=HTMLResponse)
async def get_kata_category_page(
    category_id: int, 
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
            # 3. Подгружаем справочник КАТА для выпадающих списков
            selectinload(Category.kata_associations).selectinload(CategoryKata.kata)
        )
        .where(Category.discipline == "kata", Category.id == category_id) 
        .order_by(Category.id)
    )
    category = result.scalars().one_or_none()

    used_katas = {}

    for round in category.rounds:
        for score in round.scores:
            if score.athlete_id:
                athlete_id = score.athlete_id 
                if athlete_id:
                    if athlete_id not in used_katas:
                        used_katas[athlete_id] = set()
                    if score.performance_kata:
                        used_katas[athlete_id].add(score.performance_kata)

    return templates.TemplateResponse("kata_category.html", {
        "request": request,
        "category": category,
        "t_id": tournament_id,
        "used_katas": used_katas
    })



@router.get("/view/{tournament_id}/kumite", response_class=HTMLResponse)
async def kumite_page(
    request: Request, 
    tournament_id: int, 
    t_db: AsyncSession = Depends(get_t_db)
):
    result = await t_db.execute(
        select(Category)
        .where(Category.discipline == "kumite") 
    )
    categories = result.scalars().all()

    data = defaultdict(list)
    for category in categories:
        data[category.tatami_number].append(category.to_dict())

    return templates.TemplateResponse("kumite_nav.html",{
        "request": request,
        "categories": data,
        "tournament_id": tournament_id
    })

@router.get("/view/{tournament_id}/kumite/all", response_class=HTMLResponse)
async def get_stream_page(
    request: Request, 
    tournament_id: int
):
    """
    Открывает единую панель управления всеми матчами кумите.
    Использует category_id=0 как сигнал для JS загружать весь поток.
    """
    return templates.TemplateResponse(
        "kumite_all.html", 
        {
            "request": request, 
            "tournament_id": tournament_id,
            "category_id": 0  # Передаем 0 вместо "all"
        }
    )

@router.get("/view/{tournament_id}/kumite/all/{tatami_number}", response_class=HTMLResponse)
async def get_kumite_page(
    request: Request, 
    tournament_id: int,
    tatami_number: int, 
    t_db: AsyncSession = Depends(get_t_db)
):
    
    category_name = "ОБЩИЙ ПОТОК ТУРНИРА (Все категории)"
    

    # 2. Рендерим шаблон (убедитесь, что файл называется kumite_full.html или kumite.html)
    return templates.TemplateResponse(
        "kumite_all.html", 
        {
            "request": request, 
            "tournament_id": tournament_id,
            "tatami_number": tatami_number,
            "category_name": category_name
        }
    )

@router.get("/view/{tournament_id}/kumite/{category_id}", response_class=HTMLResponse)
async def get_kumite_page(
    request: Request, 
    tournament_id: int,
    category_id: int, 
    t_db: AsyncSession = Depends(get_t_db)
):
    # 1. Определяем название страницы
        # Ищем конкретную категорию
    result = await t_db.execute(select(Category).where(Category.id == category_id, Category.discipline == 'kumite'))
    category = result.scalar_one_or_none()
    
    if not category:
        return HTMLResponse(content="Категория не найдена", status_code=404)
    category_name = category.name

    # 2. Рендерим шаблон (убедитесь, что файл называется kumite_full.html или kumite.html)
    return templates.TemplateResponse(
        "kumite_all.html", 
        {
            "request": request, 
            "tournament_id": tournament_id,
            "category_id": category_id,
            "category_name": category_name
        }
    )

@router.get("/view/{tournament_id}/kumite/{category_id}/bracket", response_class=HTMLResponse)
async def view_category_bracket(
    request: Request, 
    category_id: int, 
    tournament_id: int,
    t_db: AsyncSession = Depends(get_t_db)
):
    # 1. Получаем категорию и матчи
    cat = await t_db.get(Category, category_id)
    res = await t_db.execute(select(Match).where(Match.category_id == category_id).order_by(Match.number))
    matches = res.scalars().all()

    # 2. Собираем всех атлетов этой категории для имен
    ath_res = await t_db.execute(select(Athlete).join(DraftAssignment).where(DraftAssignment.category_id == category_id))
    athletes_map = {a.id: a.first_name for a in ath_res.scalars().all()}

    # 3. Группируем по раундам
    bracket_data = {}
    for m in matches:
        if m.round_number not in bracket_data: bracket_data[m.round_number] = []
        bracket_data[m.round_number].append(m.to_dict())
    
    max_r = max(bracket_data.keys()) if bracket_data else 1

    return templates.TemplateResponse("kumite_view.html", {
        "request": request,
        "category": cat,
        "bracket": bracket_data,
        "athletes": athletes_map,
        "max_round": max_r,
        "tournament_id": tournament_id
    })


@router.get("/view/{tournament_id}/results", response_class=HTMLResponse)
async def get_tournament_results_page(request: Request, tournament_id: int, t_db: AsyncSession = Depends(get_t_db),
    main_db: AsyncSession = Depends(get_db)):
    # 1. Получаем данные турнира
    tournament_res = await main_db.execute(select(Tournament).where(Tournament.id == tournament_id))
    tournament = tournament_res.scalar_one_or_none()
    
    if not tournament:
        raise HTTPException(status_code=404, detail="Турнир не найден")

    # 2. Получаем категории вместе с победителями и данными атлетов (через связи)
    # Используем selectinload для загрузки списка победителей и joinedload для данных атлета
    result = await t_db.execute(
        select(Category)
        .options(
            selectinload(Category.winners)
            .joinedload(Winner.athlete)
        )
    )
    categories_list = result.scalars().all()
    
    formatted_categories = []
    
    for cat in categories_list:
        # Пропускаем категории, где еще нет зафиксированных победителей
        if not cat.winners:
            continue
            
        # Подготавливаем структуру для Jinja2
        winners_data = {
            "gold": None,
            "silver": None,
            "bronze": None  # В шаблоне ожидается объект, если нужно 2 бронзы — см. примечание ниже
        }
        
        for w in cat.winners:
            athlete_info = {
                "first_name": w.athlete.first_name,
                "last_name": w.athlete.last_name,
                "club": w.athlete.club
            }
            
            if w.place == 1:
                winners_data["gold"] = athlete_info
            elif w.place == 2:
                winners_data["silver"] = athlete_info
            elif w.place == 3:
                # Если в кумите два 3-х места, берем первого попавшегося 
                # (или можно изменить шаблон под список)
                winners_data["bronze"] = athlete_info

        formatted_categories.append({
            "name": cat.name,
            "athletes_count": 5, # Убедитесь, что это поле есть в модели
            "winners": winners_data
        })

    # 3. Рендерим страницу
    return templates.TemplateResponse("result.html", {
        "request": request,
        "tournament": tournament,
        "categories": formatted_categories
    })
