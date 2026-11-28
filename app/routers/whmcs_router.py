"""Mock WHMCS external API router (POST /includes/api.php)."""

import hmac
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.config import Settings, get_settings
from app.services.whmcs_service import WhmcsService, whmcs_service

router = APIRouter(tags=["WHMCS mock"])

SUPPORTED_ACTIONS = {
    "GetClientsDetails",
    "GetInvoices",
    "GetInvoice",
    "GetClientsProducts",
    "GetProducts",
    "GetTickets",
    "GetTicket",
}


def get_whmcs_service() -> WhmcsService:
    return whmcs_service


def _authenticate_whmcs(username: str, password: str, settings: Settings) -> bool:
    expected_id = settings.mock_whmcs_identifier
    expected_secret = settings.mock_whmcs_secret
    if not expected_id or not expected_secret:
        return False
    return hmac.compare_digest(username, expected_id) and hmac.compare_digest(password, expected_secret)


@router.post("/includes/api.php")
async def whmcs_api(
    request: Request,
    settings: Settings = Depends(get_settings),
    service: WhmcsService = Depends(get_whmcs_service),
) -> dict[str, Any]:
    """Form-encoded WHMCS external API mock.

    Authenticates via form fields ``username`` and ``password`` against
    ``MOCK_WHMCS_IDENTIFIER`` and ``MOCK_WHMCS_SECRET``. Accepts ``responsetype=json``
    and ignores ``accesskey``. Does not enforce ownership on GetInvoice or GetTicket.
    """
    form = await request.form()
    params = {key: str(value) for key, value in form.items()}

    username = params.get("username", "")
    password = params.get("password", "")
    if not _authenticate_whmcs(username, password, settings):
        return {"result": "error", "message": "Authentication Failed"}

    action = params.get("action", "").strip()
    if action not in SUPPORTED_ACTIONS:
        return {"result": "error", "message": "Invalid or missing action"}

    dispatch = {
        "GetClientsDetails": service.get_clients_details,
        "GetInvoices": service.get_invoices,
        "GetInvoice": service.get_invoice,
        "GetClientsProducts": service.get_clients_products,
        "GetProducts": service.get_products,
        "GetTickets": service.get_tickets,
        "GetTicket": service.get_ticket,
    }
    return dispatch[action](params)
