from fastapi import APIRouter, Request, Response

from skardex.security import CurrentUser
from skardex.templating import templates

router = APIRouter()


@router.get("/about")
def about(request: Request, user: CurrentUser) -> Response:
    """What version this is and who it is for (spec 010). Signed in only,
    like every other screen."""
    return templates.TemplateResponse(request, "about.html")
