import structlog
from fastapi import APIRouter, Depends, Request, Response, status

from app.api.deps import get_app_settings, get_auth_service, get_current_user
from app.core.config import Settings
from app.core.rate_limit import rate_limit
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
)
from app.schemas.user import UserRead
from app.services.auth_service import AuthService, TokenPair

router = APIRouter(prefix="/auth", tags=["Auth"])
logger = structlog.get_logger(__name__)


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _token_response(tokens: TokenPair) -> TokenResponse:
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("register", "rate_limit_auth_per_minute"))],
)
async def register(
    payload: RegisterRequest, auth_service: AuthService = Depends(get_auth_service)
) -> User:
    return await auth_service.register(
        email=payload.email, password=payload.password, full_name=payload.full_name
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit("login", "rate_limit_auth_per_minute"))],
)
async def login(
    payload: LoginRequest,
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    _, tokens = await auth_service.authenticate(
        email=payload.email, password=payload.password, ip=_client_ip(request)
    )
    return _token_response(tokens)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit("refresh", "rate_limit_refresh_per_minute"))],
)
async def refresh(
    payload: RefreshRequest,
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    tokens = await auth_service.refresh(
        raw_refresh_token=payload.refresh_token, ip=_client_ip(request)
    )
    return _token_response(tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: LogoutRequest,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> None:
    await auth_service.logout(raw_refresh_token=payload.refresh_token, user=current_user)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> None:
    await auth_service.change_password(
        user=current_user,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )


@router.post(
    "/forgot-password",
    dependencies=[Depends(rate_limit("forgot_password", "rate_limit_auth_per_minute"))],
)
async def forgot_password(
    payload: ForgotPasswordRequest,
    auth_service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_app_settings),
) -> Response:
    raw_token = await auth_service.request_password_reset(email=payload.email)
    if raw_token is not None and not settings.is_production:
        # No email provider exists yet (NotificationService lands in Stage 10) - logging the
        # link is the documented dev-environment stand-in, per
        # docs/01-product-requirements.md §8 assumptions. Guarded so this can never fire in
        # production, even before a real email channel replaces it.
        logger.info("password_reset_token_issued", email=payload.email, reset_token=raw_token)
    # Identical response whether or not the account exists - no email enumeration.
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post(
    "/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit("reset_password", "rate_limit_auth_per_minute"))],
)
async def reset_password(
    payload: ResetPasswordRequest, auth_service: AuthService = Depends(get_auth_service)
) -> None:
    await auth_service.reset_password(
        raw_reset_token=payload.reset_token, new_password=payload.new_password
    )
