"""Account-type behavior shared by the accounts API and financial summaries."""
from datetime import date

from httpx import AsyncClient
from decimal import Decimal

from app.services import account_service, fx_service, net_worth_service

from tests.helpers import money, txn_payload


async def test_debit_card_is_a_liquid_account_type(client: AsyncClient, categories, monkeypatch):
    async def fixed_rate(currency: str, on_date: date) -> fx_service.FxQuote:
        return fx_service.FxQuote(Decimal("0.012") if currency == "RUB" else Decimal("1"), on_date)

    monkeypatch.setattr(fx_service, "rate_to_usd", fixed_rate)
    monkeypatch.setattr(account_service, "rate_to_usd", fixed_rate)
    monkeypatch.setattr(net_worth_service, "rate_to_usd", fixed_rate)
    response = await client.post(
        "/accounts",
        json={"name": "Debit card", "type": "debit_card", "currency": "RUB"},
    )

    assert response.status_code == 201
    debit_card = response.json()
    assert debit_card["type"] == "debit_card"

    transaction = await client.post(
        "/transactions",
        json=txn_payload(
            debit_card["id"],
            type="income",
            amount="1000.00",
            category_id=categories["Salary"]["id"],
            date=date.today().isoformat(),
        ),
    )
    assert transaction.status_code == 201

    summary = await client.get("/net-worth/summary", params={"range": "all"})

    assert summary.status_code == 200
    assert money(summary.json()["current"]) == money("12.00")


async def test_savings_account_is_separate_from_available_cash(client: AsyncClient, account_id, categories):
    savings = (await client.post(
        "/accounts", json={"name": "Three-month deposit", "type": "savings", "currency": "USD"}
    )).json()
    today = date.today().isoformat()
    income = await client.post("/transactions", json=txn_payload(
        account_id, type="income", amount="1000.00",
        category_id=categories["Salary"]["id"], date=today,
    ))
    assert income.status_code == 201
    transfer = await client.post("/transactions", json=txn_payload(
        account_id, type="transfer", amount="700.00",
        transfer_account_id=savings["id"], category_id=None, date=today,
    ))
    assert transfer.status_code == 201

    summary = (await client.get("/net-worth/summary", params={"range": "all"})).json()
    breakdown = {item["key"]: money(item["amount"]) for item in summary["breakdown"]}
    assert breakdown["cash"] == money("300")
    assert breakdown["deposits"] == money("700")
    assert money(summary["current"]) == money("1000")
    low_risk = next(tier for tier in summary["risk_levels"] if tier["risk_level"] == "low")
    assert {item["key"] for item in low_risk["items"]} == {"cash", "deposits"}
    assert money(low_risk["total_value"]) == money("1000")

    withdrawal = await client.post("/transactions", json=txn_payload(
        savings["id"], type="transfer", amount="700.00",
        transfer_account_id=account_id, category_id=None, date=today,
    ))
    assert withdrawal.status_code == 201
    after = (await client.get("/net-worth/summary", params={"range": "all"})).json()
    after_breakdown = {item["key"]: money(item["amount"]) for item in after["breakdown"]}
    assert after_breakdown["cash"] == money("1000")
    assert after_breakdown["deposits"] == money("0")
    assert money(after["current"]) == money("1000")
