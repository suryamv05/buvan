from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import APIError
from app.core.security import get_current_user, require_roles
from app.modules.auth.models import User
from app.modules.auth.schemas import (
    LoginRequest,
    PasswordChangeRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserResponse,
)
from app.modules.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, request: Request, session: AsyncSession = Depends(get_session)) -> UserResponse:
    service = AuthService(session)
    await service.rate_limit(request, "register")
    await service.register(body.email, body.password.get_secret_value())
    return UserResponse(message="If registration can be completed, you will receive further instructions.")


@router.post("/login", response_model=TokenPair)
async def login(body: LoginRequest, request: Request, response: Response, session: AsyncSession = Depends(get_session)) -> TokenPair:
    pair = await AuthService(session).login(body.email, body.password.get_secret_value(), request)
    response.headers["Cache-Control"] = "no-store"
    return pair


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshRequest, response: Response, session: AsyncSession = Depends(get_session)) -> TokenPair:
    pair = await AuthService(session).refresh(body.refresh_token)
    response.headers["Cache-Control"] = "no-store"
    return pair


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> Response:
    await AuthService(session).logout(user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(body: PasswordChangeRequest, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> Response:
    await AuthService(session).change_password(user, body.current_password.get_secret_value(), body.new_password.get_secret_value())
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/realtime-token")
async def realtime_token(user: User = Depends(require_roles("user", "coach", "admin"))) -> dict[str, str]:
    from app.core.security import create_realtime_token

    return {"token": create_realtime_token(user.id, user.token_version)}


@router.get("/discord/start")
async def discord_start(
    request: Request,
    redirect_uri: str = Query(max_length=2048),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    service = AuthService(session)
    await service.rate_limit(request, "discord-start")
    location = await service.discord_authorize_url(redirect_uri)
    response = RedirectResponse(location, status_code=302)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/discord/callback", response_model=TokenPair)
async def discord_callback(
    request: Request,
    response: Response,
    code: str = Query(min_length=1, max_length=4096),
    state: str = Query(min_length=32, max_length=256),
    redirect_uri: str = Query(max_length=2048),
    session: AsyncSession = Depends(get_session),
) -> TokenPair:
    service = AuthService(session)
    await service.rate_limit(request, "discord-callback")
    pair = await service.discord_callback(code, state, redirect_uri)
    response.headers["Cache-Control"] = "no-store"
    return pair
