from fastapi import FastAPI, Request, status
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from skardex.config import settings
from skardex.routers import auth, dashboard, materials, movements, users
from skardex.security import NotAuthenticatedError


def create_app() -> FastAPI:
    app = FastAPI(title="Simple Kardex")
    app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
    app.include_router(auth.router)
    app.include_router(dashboard.router)
    app.include_router(materials.router)
    app.include_router(movements.router)
    app.include_router(users.router)

    @app.exception_handler(NotAuthenticatedError)
    async def not_authenticated_handler(
        request: Request, exc: NotAuthenticatedError
    ) -> RedirectResponse:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    return app


app = create_app()
