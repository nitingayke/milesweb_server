"""Read-only mock WHMCS billing and support data provider."""

import json
from pathlib import Path
from typing import Any


class WhmcsService:
    """Provides read-only WHMCS API responses backed by data/whmcs.json.

    Intentionally does NOT enforce ownership on GetInvoice or GetTicket so
    the MCP server's own ownership verification can be tested against real
    cross-account WHMCS behavior.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(__file__).resolve().parents[2] / "data" / "whmcs.json"

    def _load(self) -> dict[str, Any]:
        with self.path.open(encoding="utf-8") as source:
            return json.load(source)

    @staticmethod
    def _parse_int(value: Any, default: int | None = None) -> int | None:
        if value is None or str(value).strip() == "":
            return default
        try:
            return int(str(value).strip())
        except ValueError:
            return None

    @staticmethod
    def _paginate(items: list[dict[str, Any]], limitstart: int, limitnum: int) -> list[dict[str, Any]]:
        start = max(0, limitstart)
        limit = max(1, min(limitnum, 50))
        return items[start : start + limit]

    @staticmethod
    def _quirky_collection(key: str, page: list[dict[str, Any]]) -> dict[str, Any] | str:
        """Mimic real WHMCS JSON quirks: '' when empty, single dict when 1 item, list otherwise."""
        if not page:
            return ""
        if len(page) == 1:
            return {key: page[0]}
        return {key: page}

    def get_clients_details(self, params: dict[str, str]) -> dict[str, Any]:
        data = self._load()
        clients = data.get("clients", [])
        raw_client_id = params.get("clientid")
        raw_email = params.get("email")

        match: dict[str, Any] | None = None
        if raw_client_id is not None and str(raw_client_id).strip() != "":
            cid = self._parse_int(raw_client_id)
            if cid is not None:
                match = next((c for c in clients if c.get("id") == cid), None)
        elif raw_email is not None and str(raw_email).strip() != "":
            target = raw_email.strip().lower()
            match = next((c for c in clients if c.get("email", "").strip().lower() == target), None)

        if match is None:
            return {"result": "error", "message": "Client Not Found"}

        return {
            "result": "success",
            "userid": match["id"],
            "id": match["id"],
            "email": match["email"],
            "fullname": match["fullname"],
            "status": match["status"],
            "client": dict(match),
        }

    def get_invoices(self, params: dict[str, str]) -> dict[str, Any]:
        data = self._load()
        invoices = list(data.get("invoices", []))

        userid = self._parse_int(params.get("userid"))
        if userid is not None:
            invoices = [inv for inv in invoices if inv.get("userid") == userid]
        elif params.get("userid") is not None and str(params.get("userid")).strip() != "":
            invoices = []

        status_filter = (params.get("status") or "").strip()
        if status_filter:
            invoices = [inv for inv in invoices if inv.get("status", "").lower() == status_filter.lower()]

        orderby = (params.get("orderby") or "id").strip().lower()
        order = (params.get("order") or "asc").strip().lower()
        key_map = {
            "id": lambda inv: inv.get("id", 0),
            "invoicenumber": lambda inv: str(inv.get("invoicenum", "")),
            "date": lambda inv: str(inv.get("date", "")),
            "duedate": lambda inv: str(inv.get("duedate", "")),
            "total": lambda inv: float(inv.get("total", 0) or 0),
            "status": lambda inv: str(inv.get("status", "")),
        }
        if orderby in key_map:
            invoices.sort(key=key_map[orderby], reverse=(order == "desc"))

        limitstart = self._parse_int(params.get("limitstart"), 0) or 0
        limitnum = self._parse_int(params.get("limitnum"), 25) or 25
        page = self._paginate(invoices, limitstart, limitnum)

        # Project list-level invoice fields (still includes extra fields like paymentmethod/notes for MCP to strip)
        list_rows = [
            {
                "id": inv["id"],
                "userid": inv["userid"],
                "invoicenum": inv["invoicenum"],
                "status": inv["status"],
                "date": inv["date"],
                "duedate": inv["duedate"],
                "datepaid": inv["datepaid"],
                "subtotal": inv["subtotal"],
                "credit": inv.get("credit", "0.00"),
                "tax": inv["tax"],
                "total": inv["total"],
                "currencycode": inv["currencycode"],
                "balance": inv["balance"],
                "paymentmethod": inv.get("paymentmethod"),
                "notes": inv.get("notes"),
            }
            for inv in page
        ]

        return {
            "result": "success",
            "totalresults": len(invoices),
            "startnumber": max(0, limitstart),
            "numreturned": len(list_rows),
            "invoices": self._quirky_collection("invoice", list_rows),
        }

    def get_invoice(self, params: dict[str, str]) -> dict[str, Any]:
        invoice_id = self._parse_int(params.get("invoiceid"))
        if invoice_id is None:
            return {"result": "error", "message": "Invoice Not Found"}

        data = self._load()
        inv = next((item for item in data.get("invoices", []) if item.get("id") == invoice_id), None)
        if inv is None:
            return {"result": "error", "message": "Invoice Not Found"}

        return {
            "result": "success",
            "invoiceid": inv["id"],
            "invoicenum": inv["invoicenum"],
            "userid": inv["userid"],
            "date": inv["date"],
            "duedate": inv["duedate"],
            "datepaid": inv["datepaid"],
            "subtotal": inv["subtotal"],
            "credit": inv["credit"],
            "tax": inv["tax"],
            "tax2": inv["tax2"],
            "total": inv["total"],
            "balance": inv["balance"],
            "status": inv["status"],
            "currencycode": inv["currencycode"],
            "paymentmethod": inv.get("paymentmethod"),
            "notes": inv.get("notes"),
            "items": inv.get("items", {"item": []}),
            "transactions": inv.get("transactions", ""),
        }

    def get_clients_products(self, params: dict[str, str]) -> dict[str, Any]:
        data = self._load()
        products = list(data.get("products", []))

        client_id = self._parse_int(params.get("clientid"))
        if client_id is not None:
            products = [p for p in products if p.get("clientid") == client_id]
        elif params.get("clientid") is not None and str(params.get("clientid")).strip() != "":
            products = []

        service_id = self._parse_int(params.get("serviceid"))
        if service_id is not None:
            products = [p for p in products if p.get("id") == service_id]

        limitstart = self._parse_int(params.get("limitstart"), 0) or 0
        limitnum = self._parse_int(params.get("limitnum"), 25) or 25
        page = self._paginate(products, limitstart, limitnum)

        return {
            "result": "success",
            "clientid": client_id,
            "totalresults": len(products),
            "startnumber": max(0, limitstart),
            "numreturned": len(page),
            "products": self._quirky_collection("product", page),
        }

    def get_products(self, params: dict[str, str]) -> dict[str, Any]:
        """Return WHMCS product catalog pricing (separate from GetClientsProducts)."""
        data = self._load()
        catalog_products = list(data.get("catalog_products", []))

        pid = self._parse_int(params.get("pid"))
        if pid is not None:
            catalog_products = [p for p in catalog_products if p.get("pid") == pid]
        elif params.get("pid") is not None and str(params.get("pid")).strip() != "":
            catalog_products = []

        gid = self._parse_int(params.get("gid"))
        if gid is not None:
            catalog_products = [p for p in catalog_products if p.get("gid") == gid]

        module = (params.get("module") or "").strip().lower()
        if module:
            catalog_products = [p for p in catalog_products if str(p.get("module", "")).lower() == module]

        return {
            "result": "success",
            "totalresults": len(catalog_products),
            "products": self._quirky_collection("product", catalog_products),
        }

    def get_tickets(self, params: dict[str, str]) -> dict[str, Any]:
        data = self._load()
        tickets = list(data.get("tickets", []))

        client_id = self._parse_int(params.get("clientid"))
        if client_id is not None:
            tickets = [t for t in tickets if t.get("userid") == client_id]
        elif params.get("clientid") is not None and str(params.get("clientid")).strip() != "":
            tickets = []

        status_filter = (params.get("status") or "").strip()
        if status_filter:
            tickets = [t for t in tickets if t.get("status", "").lower() == status_filter.lower()]

        limitstart = self._parse_int(params.get("limitstart"), 0) or 0
        limitnum = self._parse_int(params.get("limitnum"), 25) or 25
        page = self._paginate(tickets, limitstart, limitnum)

        rows = [
            {
                "id": t["id"],
                "tid": t["tid"],
                "userid": t["userid"],
                "deptid": t["deptid"],
                "deptname": t["deptname"],
                "subject": t["subject"],
                "status": t["status"],
                "priority": t["priority"],
                "date": t["date"],
                "lastreply": t["lastreply"],
                "flag": t.get("flag", 0),
                "notes": t.get("notes"),
            }
            for t in page
        ]

        return {
            "result": "success",
            "totalresults": len(tickets),
            "startnumber": max(0, limitstart),
            "numreturned": len(rows),
            "tickets": self._quirky_collection("ticket", rows),
        }

    def get_ticket(self, params: dict[str, str]) -> dict[str, Any]:
        ticket_id = self._parse_int(params.get("ticketid"))
        if ticket_id is None:
            return {"result": "error", "message": "Ticket Not Found"}

        data = self._load()
        ticket = next((item for item in data.get("tickets", []) if item.get("id") == ticket_id), None)
        if ticket is None:
            return {"result": "error", "message": "Ticket Not Found"}

        replies = list(ticket.get("replies", {}).get("reply", []))
        replies_sort = (params.get("repliessort") or "ASC").strip().upper()
        if replies_sort == "DESC":
            replies.sort(key=lambda r: str(r.get("date", "")), reverse=True)
        else:
            replies.sort(key=lambda r: str(r.get("date", "")))

        return {
            "result": "success",
            "ticketid": ticket["id"],
            "tid": ticket["tid"],
            "userid": ticket["userid"],
            "deptid": ticket["deptid"],
            "deptname": ticket["deptname"],
            "c": ticket["c"],
            "subject": ticket["subject"],
            "status": ticket["status"],
            "priority": ticket["priority"],
            "date": ticket["date"],
            "lastreply": ticket["lastreply"],
            "flag": ticket.get("flag", 0),
            "notes": ticket.get("notes"),
            "attachments": ticket.get("attachments", []),
            "replies": {"reply": replies},
        }


whmcs_service = WhmcsService()
