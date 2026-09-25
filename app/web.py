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
from app.tournament_main.model import CategoryTemplate, Tournament
from app.tournament_main.schema import TournamentCreate
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import create_tournament_db, get_db, get_t_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, select, asc, desc, func, extract
from sqlalchemy.orm import selectinload
from fastapi.responses import RedirectResponse

router = APIRouter(include_in_schema=False) # Скрываем из Swagger (docs)
templates = Jinja2Templates(directory="templates")

@router.get("/", response_class=HTMLResponse)
async def index_page(request: Request, db: AsyncSession = Depends(get_db)):
    # Загружаем турниры
    t_res = await db.execute(select(Tournament))
    tournaments = t_res.scalars().all()
    
    # Загружаем шаблоны для формы создания
    c_res = await db.execute(select(CategoryTemplate))
    templates_list = c_res.scalars().all()
    
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "tournaments": tournaments,
        "templates": templates_list
    })

@router.get("/view/{tournament_id}", response_class=HTMLResponse)
async def index_page(
    request: Request, 
    tournament_id: int, 
    t_db: AsyncSession = Depends(get_t_db),
    main_db: AsyncSession = Depends(get_db)):

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


# Вспомогательная функция для сборки схемы из формы
async def tournament_form_data(
    title: str = Form(...),
    type: str = Form(...),
    event_date: date = Form(...),
    description: str = Form(""),
    judge: str = Form(""),
    secretary: str = Form(""),
    template_ids: list[int] = Form([])
):
    return TournamentCreate(
        title=title,
        type=type,
        event_date=event_date,
        description=description,
        judge=judge,
        secretary=secretary,
        template_ids=template_ids
    )

# Обработка формы создания турнира
@router.post("/tournaments/create-web")
async def create_tournament_web(
    data: TournamentCreate = Depends(tournament_form_data),
    db: AsyncSession = Depends(get_db)
):
    # Генерация слага для названия БД
    slug = re.sub(r'\W+', '_', data.title).lower()
    
    # Создаем БД и копируем категории (используем данные из схемы)
    new_db_url = await create_tournament_db(slug, db, data.template_ids)
    
    # Создаем запись в основной БД
    new_tournament = Tournament(
        title=data.title, 
        type=data.type,
        description=data.description,
        event_date=data.event_date, 
        db_path=new_db_url,
        judge=data.judge,        # Теперь сохраняем и судей
        secretary=data.secretary
    )
    
    db.add(new_tournament)
    await db.commit()
    
    return RedirectResponse(url="/", status_code=303)

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
    ath_result = await t_db.execute(select(Athlete))
    all_athletes = list(ath_result.scalars().all())

    # Получаем ВСЕ команды с их участниками
    team_result = await t_db.execute(
        select(Team).options(selectinload(Team.members))
    )
    teams = list(team_result.scalars().all())

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

    # Сортировка команд (по названию)
    teams.sort(key=lambda x: (x.name or "").lower())

    # 5. Список клубов берем из ПОЛНОГО списка атлетов (чтобы фильтр не "съедал" варианты)
    unique_clubs = sorted(list(set(a.club for a in all_athletes if a.club)))
    
    return templates.TemplateResponse("athletes.html", {
        "request": request, 
        "athletes": filtered_athletes,
        "teams": teams, # ОБЯЗАТЕЛЬНО передаем в шаблон
        "t_id": tournament_id,
        "clubs": unique_clubs,
        "age_categories": ["6-7", "8-9", "10-11", "12-13", "14-15", "16-17", "18+"]
    })

@router.get("/view/{tournament_id}/categories", response_class=HTMLResponse)
async def view_categories(
    request: Request, 
    tournament_id: int, 
    t_db: AsyncSession = Depends(get_t_db),
    main_db: AsyncSession = Depends(get_db),
):
    # # 1. Проверка и авто-распределение
    # check_draft = await t_db.execute(select(DraftAssignment).limit(1))
    # if not check_draft.scalar_one_or_none():
    #     await run_draft_assignment_logic(tournament_id, main_db, t_db)
    #     await t_db.commit() 

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
    print(categories_with_discipline)
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
        .where(Category.discipline == "kata") 
    )
    categories = result.scalars().all()

    return templates.TemplateResponse("kata.html", {
        "request": request,
        "categories": categories,
        "t_id": tournament_id
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

    print(data)
    return templates.TemplateResponse("kumite_nav.html",{
        "request": request,
        "categories": data,
        "tournament_id": tournament_id
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