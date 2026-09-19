from pathlib import Path

from fastapi.templating import Jinja2Templates

from skardex.constants import MOVEMENT_REASONS, UNIT_LABELS
from skardex.money import format_cop

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["unit_labels"] = UNIT_LABELS
templates.env.globals["reason_labels"] = MOVEMENT_REASONS
templates.env.filters["cop"] = format_cop
