from datetime import date
from typing import Annotated

from fastapi.templating import Jinja2Templates
from app.child.models.category import Category
from app.child.models.draft import DraftAssignment
from app.child.models.team import Team
from app.child.models.users import User
from app.child.schemas.athlete import AthleteBase, AthleteCreate, AthleteGet, AthleteRead, AthleteUpdate
from app.child.models.athlete import Athlete
from app.child.services.excel import parse_athletes_excel
from app.child.services.logic import find_category_id
from app.core.dependencies import create_session_token, get_current_user_optional
from app.core.secury import verify_password
from app.database import create_tournament_db, get_db, get_t_db, get_tournament_session
from app.tournament_main.model import Tournament
from app.tournament_main.schema import TournamentCreate, TournamentRead
from fastapi import APIRouter, Form, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Request, Depends, UploadFile, File
from sqlalchemy import select, delete
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm import selectinload
import re
from fastapi.responses import RedirectResponse
from fastapi.responses import HTMLResponse

DBSession = Annotated[AsyncSession, Depends(get_t_db)]
UpFile = Annotated[UploadFile, File(...)]

router = APIRouter(prefix="/{tournament_id}/auth", tags=["Auth"])
templates = Jinja2Templates(directory="templates")
    

# 1. Страница логина (GET)
@router.get("/", response_class=HTMLResponse)
async def login_page(
    tournament_id: int, 
    request: Request,
    user = Depends(get_current_user_optional)
):
    # Если пользователь уже вошел, кидаем его на страницу турнира
    if user:
        return RedirectResponse(url=f"/view/{tournament_id}", status_code=303)
        
    return templates.TemplateResponse("login.html", {
        "request": request
    })

# 2. Обработка формы (POST)
@router.post("/")
async def login_submit(
    tournament_id: int, # <--- ДОБАВИЛИ СЮДА
    request: Request,
    login: str = Form(...),
    password: str = Form(...),
    t_db: AsyncSession = Depends(get_t_db) # Теперь get_t_db получит ID и откроет БД турнира!
):
    # Ищем пользователя
    result = await t_db.execute(select(User).where(User.login == login))
    user = result.scalar_one_or_none()
    
    # Проверяем
    if not user or not verify_password(password, user.hashed_password) or not user.is_active:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Неверный логин или пароль"
        }, status_code=400)

    # Успешный вход
    token = create_session_token(user.id)
    # Редиректим на страницу ЭТОГО турнира
    response = RedirectResponse(url=f"/view/{tournament_id}", status_code=303) 
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax"
    )
    return response