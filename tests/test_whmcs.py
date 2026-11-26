"""Tests for the WHMCS mock API (POST /includes/api.php) and fixture integrity."""

import json
from pathlib import Path

import pytest


CUSTOMERS_PATH = Path(__file__).resolve().parents[1] / "data" / "customers.json"
WHMCS_PATH = Path(__file__).resolve().parents[1] / "data" / "whmcs.json"


def whmcs_post(client, action: str | None = None, **extra):
    payload = {
        "username": "test-whmcs-identifier",
        "password": "test-whmcs-secret",
        "responsetype": "json",
    }
    if action is not None:
        payload["action"] = action
    payload.update(extra)
    return client.post("/includes/api.php", data=payload)


class TestWhmcsAuthAndDispatch:
    def test_get_method_returns_405(self, client):
        assert client.get("/includes/api.php").status_code == 405

    @pytest.mark.parametrize(
        "creds",
        [
            {},
            {"username": "wrong", "password": "test-whmcs-secret"},
            {"username": "test-whmcs-identifier", "password": "wrong"},
        ],
    )
    def test_bad_credentials_return_authentication_failed(self, client, creds):
        resp = client.post("/includes/api.php", data={"action": "GetClientsDetails", **creds})
        assert resp.status_code == 200
        assert resp.json() == {"result": "error", "message": "Authentication Failed"}

    @pytest.mark.parametrize("action", [None, "", "AddInvoice", "OpenTicket", "UnknownAction"])
    def test_unknown_or_missing_action_rejected(self, client, action):
        resp = whmcs_post(client, action=action)
        assert resp.status_code == 200
        assert resp.json() == {"result": "error", "message": "Invalid or missing action"}

    def test_accesskey_is_ignored(self, client):
        resp = whmcs_post(client, action="GetClientsDetails", email="rahul@example.com", accesskey="anything")
        assert resp.status_code == 200
        assert resp.json()["result"] == "success"


class TestWhmcsActions:
    def test_get_clients_details_by_email_and_clientid(self, client):
        by_email = whmcs_post(client, action="GetClientsDetails", email="PRIYA@example.com")
        assert by_email.status_code == 200
        data = by_email.json()
        assert data["result"] == "success"
        assert data["client"]["id"] == 12347
        assert data["email"] == "priya@example.com"

        by_id = whmcs_post(client, action="GetClientsDetails", clientid="12345")
        assert by_id.status_code == 200
        assert by_id.json()["client"]["id"] == 12345
        assert by_id.json()["email"] == "rahul@example.com"

        missing = whmcs_post(client, action="GetClientsDetails", email="nobody@example.com")
        assert missing.status_code == 200
        assert missing.json()["result"] == "error"

    def test_get_invoices_rahul_statuses_and_sorting(self, client):
        resp = whmcs_post(client, action="GetInvoices", userid="12345", orderby="id", order="asc")
        assert resp.status_code == 200
        body = resp.json()
        assert body["result"] == "success"
        assert body["totalresults"] == 4
        assert body["numreturned"] == 4
        invoices = body["invoices"]["invoice"]
        assert isinstance(invoices, list)
        assert {inv["status"] for inv in invoices} == {"Paid", "Unpaid", "Overdue", "Cancelled"}
        assert all(inv["userid"] == 12345 for inv in invoices)
        assert all("credit" in inv for inv in invoices)
        inv_81002 = next(inv for inv in invoices if inv["id"] == 81002)
        assert inv_81002["credit"] == "100.00"

    def test_get_invoices_priya_works_without_enhance_hosting(self, client):
        resp = whmcs_post(client, action="GetInvoices", userid="12347")
        assert resp.status_code == 200
        body = resp.json()
        assert body["result"] == "success"
        assert body["totalresults"] == 2
        assert len(body["invoices"]["invoice"]) == 2

    def test_get_invoices_empty_quirk_for_karan(self, client):
        resp = whmcs_post(client, action="GetInvoices", userid="12349")
        assert resp.status_code == 200
        body = resp.json()
        assert body["result"] == "success"
        assert body["totalresults"] == 0
        assert body["numreturned"] == 0
        assert body["invoices"] == ""

    def test_single_object_quirk_on_lists(self, client):
        # Amit has 1 product and 1 ticket -> single object instead of list
        products = whmcs_post(client, action="GetClientsProducts", clientid="12346").json()
        assert isinstance(products["products"]["product"], dict)
        assert products["products"]["product"]["id"] == 1002

        tickets = whmcs_post(client, action="GetTickets", clientid="12346").json()
        assert isinstance(tickets["tickets"]["ticket"], dict)
        assert tickets["tickets"]["ticket"]["id"] == 92001

        # Filtered single invoice also triggers single-object quirk
        paid = whmcs_post(client, action="GetInvoices", userid="12345", status="Paid").json()
        assert paid["totalresults"] == 1
        assert isinstance(paid["invoices"]["invoice"], dict)
        assert paid["invoices"]["invoice"]["id"] == 81001

    def test_get_invoice_details_and_not_found(self, client):
        resp = whmcs_post(client, action="GetInvoice", invoiceid="81001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"] == "success"
        assert data["userid"] == 12345
        assert len(data["items"]["item"]) == 1
        assert len(data["transactions"]["transaction"]) == 1
        assert "notes" in data

        missing = whmcs_post(client, action="GetInvoice", invoiceid="999999")
        assert missing.status_code == 200
        assert missing.json() == {"result": "error", "message": "Invoice Not Found"}

    def test_get_clients_products_includes_sensitive_fields_and_serviceid_filter(self, client):
        resp = whmcs_post(client, action="GetClientsProducts", clientid="12345")
        assert resp.status_code == 200
        products = resp.json()["products"]["product"]
        assert len(products) == 2
        assert "username" in products[0]
        assert "password" in products[0]
        assert "dedicatedip" in products[0]
        assert "customfields" in products[0]
        for key in ("firstpaymentamount", "nextinvoicedate", "paymentmethodname", "currency"):
            assert key in products[0]

        filtered = whmcs_post(client, action="GetClientsProducts", clientid="12345", serviceid="1005")
        assert filtered.status_code == 200
        assert filtered.json()["totalresults"] == 1
        assert filtered.json()["products"]["product"]["id"] == 1005

        karan_empty = whmcs_post(client, action="GetClientsProducts", clientid="12349")
        assert karan_empty.json()["products"] == ""

    def test_get_tickets_and_get_ticket_details(self, client):
        tickets = whmcs_post(client, action="GetTickets", clientid="12345").json()
        assert tickets["totalresults"] == 3
        rows = tickets["tickets"]["ticket"]
        assert all(row["userid"] == 12345 for row in rows)
        assert any(row["status"] == "Closed" for row in rows)

        neha_empty = whmcs_post(client, action="GetTickets", clientid="12348").json()
        assert neha_empty["totalresults"] == 0
        assert neha_empty["tickets"] == ""

        detail = whmcs_post(client, action="GetTicket", ticketid="91001", repliessort="DESC").json()
        assert detail["result"] == "success"
        assert detail["userid"] == 12345
        assert "c" in detail
        assert len(detail["attachments"]) == 1
        replies = detail["replies"]["reply"]
        assert len(replies) == 4
        assert replies[0]["date"] >= replies[-1]["date"]
        assert any(r["admin"] is True and r["note"] is True for r in replies)

        missing = whmcs_post(client, action="GetTicket", ticketid="999999").json()
        assert missing == {"result": "error", "message": "Ticket Not Found"}

    def test_cross_client_get_invoice_and_get_ticket_return_real_userid(self, client):
        """Mock intentionally does NOT block cross-client GetInvoice/GetTicket lookups."""
        inv = whmcs_post(client, action="GetInvoice", invoiceid="82001").json()
        assert inv["result"] == "success"
        assert inv["userid"] == 12346

        tkt = whmcs_post(client, action="GetTicket", ticketid="93001").json()
        assert tkt["result"] == "success"
        assert tkt["userid"] == 12347


class TestFixtureIntegrity:
    def test_all_ids_unique_and_references_valid(self):
        customers = json.loads(CUSTOMERS_PATH.read_text(encoding="utf-8"))["customers"]
        whmcs = json.loads(WHMCS_PATH.read_text(encoding="utf-8"))

        customer_by_id = {c["clientId"]: c for c in customers}
        assert len(customer_by_id) == len(customers)

        whmcs_clients = {c["id"]: c for c in whmcs["clients"]}
        assert len(whmcs_clients) == len(whmcs["clients"])
        for cid, wclient in whmcs_clients.items():
            assert cid in customer_by_id
            assert wclient["email"].lower() == customer_by_id[cid]["email"].lower()

        invoice_ids = [inv["id"] for inv in whmcs["invoices"]]
        assert len(invoice_ids) == len(set(invoice_ids))
        for inv in whmcs["invoices"]:
            assert inv["userid"] in whmcs_clients

        product_ids = [p["id"] for p in whmcs["products"]]
        assert len(product_ids) == len(set(product_ids))
        for prod in whmcs["products"]:
            assert prod["clientid"] in whmcs_clients

        ticket_ids = [t["id"] for t in whmcs["tickets"]]
        assert len(ticket_ids) == len(set(ticket_ids))
        for tkt in whmcs["tickets"]:
            assert tkt["userid"] in whmcs_clients
