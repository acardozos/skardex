from pathlib import Path

from fastapi.templating import Jinja2Templates

from skardex.constants import MOVEMENT_REASON_LABELS, UNIT_LABELS
from skardex.money import format_cop
from skardex.pagination import PER_PAGE_OPTIONS, build_url
from skardex.quantities import format_quantity
from skardex.services.billing_service import can_fix_billing
from skardex.static_files import static_url

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["unit_labels"] = UNIT_LABELS
templates.env.globals["reason_labels"] = MOVEMENT_REASON_LABELS
templates.env.globals["can_fix_billing"] = can_fix_billing
templates.env.globals["per_page_options"] = PER_PAGE_OPTIONS
templates.env.globals["page_url"] = build_url
templates.env.globals["static_url"] = static_url
templates.env.filters["cop"] = format_cop
templates.env.filters["qty"] = format_quantity
