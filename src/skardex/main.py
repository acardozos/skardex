import logging

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from skardex.config import settings
from skardex.routers import auth, dashboard, materials, movements, users
from skardex.security import NotAuthenticatedError
from skardex.templating import templates

logger = logging.getLogger("skardex")

_ERROR_TEMPLATES = {
    status.HTTP_403_FORBIDDEN: "errors/403.html",
    status.HTTP_404_NOT_FOUND: "errors/404.html",
}


def create_app() -> FastAPI:
    app = FastAPI(title="Simple Kardex")
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        same_site="lax",
        https_only=settings.session_https_only,
    )
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

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> Response:
        template_name = _ERROR_TEMPLATES.get(exc.status_code)
        if template_name is None:
            return JSONResponse(
                {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
            )
        return templates.TemplateResponse(
            request, template_name, status_code=exc.status_code
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> Response:
        logger.exception("Unhandled exception on %s %s", request.method, request.url)
        return templates.TemplateResponse(
            request,
            "errors/500.html",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return app


app = create_app()
