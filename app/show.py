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
from app.core.dependencies import get_current_user_optional
from app.tournament_main.model import CategoryTemplate, Tournament
from app.tournament_main.schema import TournamentCreate
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import create_tournament_db, get_db, get_t_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, select, asc, desc, func, extract, update, and_, or_
from sqlalchemy.orm import selectinload
from fastapi.responses import RedirectResponse

router = APIRouter(include_in_schema=False) # Скрываем из Swagger (docs)
templates = Jinja2Templates(directory="templates")

async def tournament_form_data(
    title: str = Form(...),
    type: str = Form(...),
    event_date: date = Form(...),
    description: str = Form(""),
    judge: str = Form(""),
    secretary: str = Form(""),
    template_ids: list[int] = Form([]),
    admin_password: str = Form(...),
    secretary_password: str = Form(...),
):
    return TournamentCreate(
        title=title,
        type=type,
        event_date=event_date,
        description=description,
        judge=judge,
        secretary=secretary,
        template_ids=template_ids,
        admin_password=admin_password,
        secretary_password=secretary_password,
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
    new_db_url = await create_tournament_db(slug, db, data.template_ids, data.admin_password, data.secretary_password)
    
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

@router.get("/view/{tournament_id}/kata-show", response_class=HTMLResponse)
async def kata_page_show(
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
    if categories:
        for category in categories:
            if category.rounds and category.rounds[0].scores:
                data[category.tatami_number].append(category.to_dict())

    return templates.TemplateResponse("kata_nav_show.html",{
        "request": request,
        "categories": data,
        "tournament_id": tournament_id,
    })

@router.get("/view/{tournament_id}/kata/all/{tatami_number}/show", response_class=HTMLResponse)
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
            .selectinload(Round.scores.and_(or_(Score.team.has(Team.is_active == True), Score.athlete.has(Athlete.is_active == True))))
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

    return templates.TemplateResponse("kata_show.html", {
        "request": request,
        "categories": categories,
        "t_id": tournament_id,
    })

@router.get("/view/{tournament_id}/kata/{category_id}/show", response_class=HTMLResponse)
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
            .selectinload(Round.scores.and_(or_(Score.team.has(Team.is_active == True), Score.athlete.has(Athlete.is_active == True))))
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

    return templates.TemplateResponse("kata_category_show.html", {
        "request": request,
        "category": category,
        "t_id": tournament_id
    })