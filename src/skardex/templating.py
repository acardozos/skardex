from pathlib import Path

from fastapi.templating import Jinja2Templates

from skardex.constants import UNIT_LABELS

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["unit_labels"] = UNIT_LABELS
