from fastapi import Request, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from typing import Optional

from app.child.models.users import User
from app.database import get_t_db

SECRET_KEY = "super-secret-key"
serializer = URLSafeTimedSerializer(SECRET_KEY)

def create_session_token(user_id: int) -> str:
    return serializer.dumps({"user_id": user_id})

def get_user_id_from_token(token: str) -> Optional[int]:
    try:
        data = serializer.loads(token, max_age=604800)
        return data.get("user_id")
    except (BadSignature, SignatureExpired):
        return None

async def get_current_user_optional(
        request: Request,
        db: AsyncSession = Depends(get_t_db)
) -> Optional[User]:
    session_token = request.cookies.get("session_token")
    if not session_token:
        return None
    user_id = get_user_id_from_token(session_token)
    if not user_id:
        return None
    user = await db.get(User, user_id)
    if user and user.is_active:
        return user
    return None

async def require_auth(user: Optional[User] = Depends(get_current_user_optional)):
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"location": "/"}
        )
    return user

async def require_admin(user: User | None = Depends(get_current_user_optional)):
    if not user or user.role !="admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Требуются права администратора"
        )
    return user

async def require_secretary_or_admin(user: User | None = Depends(get_current_user_optional)):
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуются авторизация"
        )
    if user.role not in ["secretary", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ для судей"
        )
    return user