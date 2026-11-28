"""Read-only customer endpoints authenticated via verified Bearer JWT."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.customer_repository import CustomerRepository, repository
from app.security import get_current_client_id

router = APIRouter(prefix="/api/v1/connector/customer", tags=["Customer connector"])


def get_repository() -> CustomerRepository:
    return repository


ClientId = Annotated[int | None, Query(alias="clientId", gt=0, description="Verified MilesWeb customer ID")]


def _resolve_authenticated_customer(
    requested_client_id: ClientId,
    token_client_id: int | str,
    customer_repository: CustomerRepository,
) -> dict[str, Any]:
    caller_id = int(token_client_id)
    if requested_client_id is not None and requested_client_id != caller_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    customer = customer_repository.get_customer(caller_id)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return customer


@router.get("")
def get_customer(
    client_id: ClientId = None,
    token_client_id: int | str = Depends(get_current_client_id),
    customer_repository: CustomerRepository = Depends(get_repository),
) -> dict[str, Any]:
    """Return profile information for the authenticated customer."""
    customer = _resolve_authenticated_customer(client_id, token_client_id, customer_repository)
    return {
        "success": True,
        "data": {key: customer[key] for key in ("clientId", "name", "email", "status")},
    }


@router.get("/hosting-services")
def get_hosting_services(
    client_id: ClientId = None,
    token_client_id: int | str = Depends(get_current_client_id),
    customer_repository: CustomerRepository = Depends(get_repository),
) -> dict[str, Any]:
    """Return hosting services, including an empty list for customers without any."""
    customer = _resolve_authenticated_customer(client_id, token_client_id, customer_repository)
    return {"success": True, "data": customer["hostingServices"]}


@router.get("/domains")
def get_domains(
    client_id: ClientId = None,
    token_client_id: int | str = Depends(get_current_client_id),
    customer_repository: CustomerRepository = Depends(get_repository),
) -> dict[str, Any]:
    """Return registered domains, including an empty list for customers without any."""
    customer = _resolve_authenticated_customer(client_id, token_client_id, customer_repository)
    return {"success": True, "data": customer["domains"]}
