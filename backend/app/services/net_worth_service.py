"""Net worth aggregation: a single trend line plus a percent breakdown by
asset class.

Design note: "Cash" and "Deposits" are not stored anywhere — both are derived
live from Account/Transaction data. Savings accounts are deposits; checking,
debit-card, cash and investment-account balances are available cash. The
Transactions feature stays the single source of truth for money in accounts.
Investment accounts count here too: their balance is uninvested/unallocated
money sitting on the account, not the market value of what's actually
invested — that value is still tracked manually via Asset/AssetValuation,
same as every other class (investments, crypto, real estate, vehicles,
precious metals, other). Without this, money deposited into an investment
account but not yet turned into a valued Asset silently disappeared from
net worth. Account balances and asset valuations are collapsed into one
daily, forward-filled series so the chart reads as one continuous line even
though the two halves are updated at very different cadences.
"""
from collections import defaultdict
from datetime import date as date_
from datetime import timedelta
from decimal import Decimal
from itertools import groupby

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.asset import Asset, AssetValuation
from app.models.enums import AccountType, AssetClass, CapitalRole, RiskLevel, TransactionType
from app.models.transaction import Transaction
from app.services.fx_service import money, rate_to_usd
from app.services.account_service import _account_balances
from app.schemas.net_worth import (
    CapitalRoleSummary,
    NetWorthBreakdownItem,
    NetWorthPoint,
    NetWorthSummary,
    RiskLevelItem,
    RiskLevelSummary,
)

CASH_ACCOUNT_TYPES = {
    AccountType.CHECKING,
    AccountType.DEBIT_CARD,
    AccountType.CASH,
    AccountType.INVESTMENT,
}
DEPOSIT_ACCOUNT_TYPES = {AccountType.SAVINGS}

RANGE_DAYS = {"30d": 30, "90d": 90, "1y": 365, "5y": 365 * 5}

_CLASS_META: dict[str, tuple[str, str, str]] = {
    # key -> (display name, color, lucide icon). Colors use the dataviz
    # skill's validated 8-slot palette (blue, orange, aqua, yellow, magenta,
    # green, violet, red). Deposits occupy slot 8 beside Cash in the UI;
    # their red is a category color, not a risk or loss status.
    "cash": ("Свободные деньги", "#2a78d6", "wallet"),  # slot 1 blue
    "deposits": ("Вклады", "#b84b54", "piggy-bank"),  # slot 8 red
    AssetClass.INVESTMENTS.value: ("Инвестиции", "#eb6834", "trending-up"),  # slot 2 orange
    AssetClass.CRYPTO.value: ("Криптовалюта", "#1baf7a", "bitcoin"),  # slot 3 aqua
    AssetClass.REAL_ESTATE.value: ("Недвижимость", "#eda100", "building-2"),  # slot 4 yellow
    AssetClass.VEHICLES.value: ("Транспорт", "#e87ba4", "car"),  # slot 5 magenta
    AssetClass.PRECIOUS_METALS.value: ("Драгметаллы", "#008300", "gem"),  # slot 6 green
    AssetClass.OTHER.value: ("Прочее", "#4a3aa7", "package"),  # slot 7 violet
}

_ROLE_META: dict[CapitalRole, tuple[str, str]] = {
    # role -> (label, color). Status colors, not categorical ones — "good"
    # and "critical" from the dataviz skill's fixed status palette, reused
    # verbatim from how StatCard/NetWorthChart already color income vs.
    # expense elsewhere in the app.
    CapitalRole.INCOME: ("Доходный", "var(--success)"),
    CapitalRole.NEUTRAL: ("Нейтральный", "var(--text-muted)"),
    CapitalRole.DRAIN: ("Убыточный", "var(--danger)"),
}

_RISK_META: dict[RiskLevel, tuple[str, str]] = {
    # Same status-color reuse as _ROLE_META — low risk reads as "good",
    # high risk as "critical", not a categorical hue.
    RiskLevel.LOW: ("Низкий", "var(--success)"),
    RiskLevel.MEDIUM: ("Средний", "var(--text-muted)"),
    RiskLevel.HIGH: ("Высокий", "var(--danger)"),
}


def _daily_series(events: list[tuple[date_, Decimal]], start: date_, end: date_) -> list[NetWorthPoint]:
    """Forward-fills a sparse, date-sorted list of cumulative totals into one
    point per calendar day. `events` before `start` still count — they just
    collapse into `start`'s opening value."""
    events = sorted(events, key=lambda e: e[0])
    points: list[NetWorthPoint] = []
    idx, n = 0, len(events)
    current = Decimal("0")
    day = start
    while day <= end:
        while idx < n and events[idx][0] <= day:
            current = events[idx][1]
            idx += 1
        points.append(NetWorthPoint(date=day, value=current))
        day += timedelta(days=1)
    return points


async def _account_cumulative_events(session: AsyncSession) -> dict[str, list[tuple[date_, Decimal]]]:
    accounts_result = await session.execute(select(Account.id, Account.type, Account.currency))
    account_groups = {
        acc_id: ("cash" if acc_type in CASH_ACCOUNT_TYPES else "deposits", currency)
        for acc_id, acc_type, currency in accounts_result.all()
        if acc_type in CASH_ACCOUNT_TYPES or acc_type in DEPOSIT_ACCOUNT_TYPES
    }

    txns_result = await session.execute(
        select(Transaction.date, Transaction.type, Transaction.amount_usd, Transaction.account_id, Transaction.transfer_account_id)
    )

    deltas: dict[str, dict[date_, Decimal]] = {
        "cash": defaultdict(Decimal), "deposits": defaultdict(Decimal),
    }
    for tx_date, tx_type, amount, account_id, transfer_account_id in txns_result.all():
        source = account_groups.get(account_id)
        destination = account_groups.get(transfer_account_id)
        if tx_type == TransactionType.INCOME and source:
            deltas[source[0]][tx_date] += amount
        elif tx_type == TransactionType.EXPENSE and source:
            deltas[source[0]][tx_date] -= amount
        elif tx_type == TransactionType.TRANSFER:
            if source:
                deltas[source[0]][tx_date] -= amount
            if destination:
                deltas[destination[0]][tx_date] += amount

    balances = await _account_balances(session)
    current: dict[str, Decimal] = defaultdict(Decimal)
    for account_id, (group, currency) in account_groups.items():
        balance = balances.get(account_id, Decimal("0"))
        if balance:
            current[group] += money(balance * (await rate_to_usd(currency, date_.today())).rate)

    result: dict[str, list[tuple[date_, Decimal]]] = {}
    for group, daily in deltas.items():
        events: list[tuple[date_, Decimal]] = []
        running = Decimal("0")
        for day in sorted(daily):
            running += daily[day]
            events.append((day, running))
        if events or current[group]:
            events.append((date_.today(), current[group]))
        result[group] = events
    return result


async def _asset_events_and_class_totals(
    session: AsyncSession,
) -> tuple[list[tuple[date_, Decimal]], dict[AssetClass, Decimal], dict[int, Decimal]]:
    asset_class_result = await session.execute(select(Asset.id, Asset.asset_class, Asset.currency))
    asset_meta = {asset_id: (asset_class, currency) for asset_id, asset_class, currency in asset_class_result.all()}

    valuations_result = await session.execute(
        select(AssetValuation.asset_id, AssetValuation.as_of_date, AssetValuation.value).order_by(
            AssetValuation.as_of_date
        )
    )
    rows = valuations_result.all()

    current_by_asset: dict[int, Decimal] = {}
    native_by_asset: dict[int, Decimal] = {}
    events: list[tuple[date_, Decimal]] = []
    for day, group in groupby(rows, key=lambda row: row[1]):
        for asset_id, _, value in group:
            native_by_asset[asset_id] = value
            currency = asset_meta[asset_id][1]
            rate = (await rate_to_usd(currency, day)).rate
            current_by_asset[asset_id] = money(value * rate)
        events.append((day, sum(current_by_asset.values(), Decimal("0"))))

    # The latest asset valuation remains the recorded asset value, while its
    # USD equivalent changes with today's exchange rate.
    if native_by_asset:
        for asset_id, value in native_by_asset.items():
            rate = (await rate_to_usd(asset_meta[asset_id][1], date_.today())).rate
            current_by_asset[asset_id] = money(value * rate)
        events.append((date_.today(), sum(current_by_asset.values(), Decimal("0"))))

    class_totals: dict[AssetClass, Decimal] = defaultdict(Decimal)
    for asset_id, value in current_by_asset.items():
        asset_class = asset_meta.get(asset_id, (None, None))[0]
        if asset_class is not None:
            class_totals[asset_class] += value

    return events, class_totals, current_by_asset


async def _capital_role_summary(session: AsyncSession, current_by_asset: dict[int, Decimal]) -> list[CapitalRoleSummary]:
    """Cross-cuts the same assets by how the user tagged them (income /
    neutral / drain) instead of by asset class — always all three roles,
    even at zero, so the block reads as a fixed scale rather than a list
    that shuffles as assets are added."""
    roles_result = await session.execute(select(Asset.id, Asset.capital_role, Asset.monthly_cash_flow, Asset.currency))

    totals_value: dict[CapitalRole, Decimal] = defaultdict(Decimal)
    totals_flow: dict[CapitalRole, Decimal] = defaultdict(Decimal)
    counts: dict[CapitalRole, int] = defaultdict(int)
    for asset_id, role, cash_flow, currency in roles_result.all():
        totals_value[role] += current_by_asset.get(asset_id, Decimal("0"))
        if cash_flow:
            rate = (await rate_to_usd(currency, date_.today())).rate
            totals_flow[role] += money(cash_flow * rate)
        counts[role] += 1

    return [
        CapitalRoleSummary(
            role=role.value,
            label=_ROLE_META[role][0],
            color=_ROLE_META[role][1],
            total_value=totals_value.get(role, Decimal("0")),
            monthly_cash_flow=totals_flow.get(role, Decimal("0")),
            count=counts.get(role, 0),
        )
        for role in CapitalRole
    ]


async def _risk_level_summary(
    session: AsyncSession, current_by_asset: dict[int, Decimal], cash_today: Decimal,
    deposits_today: Decimal,
) -> list[RiskLevelSummary]:
    """Cross-cuts Cash + assets by user-tagged risk of loss — unlike
    capital_roles, Cash participates here: it's the zero-risk anchor an
    80/20-style allocation rule ("80% of capital at zero risk, at most 20%
    exposed") is measured against. Always all three tiers, even at zero,
    same reasoning as capital_roles. Each tier's item list *is* its
    diversification view — a tier that's one holding at 100% is
    concentrated, several even-sized holdings aren't, no separate index."""
    assets_result = await session.execute(select(Asset.id, Asset.name, Asset.risk_level))
    asset_rows = assets_result.all()

    totals: dict[RiskLevel, Decimal] = defaultdict(Decimal)
    items_by_level: dict[RiskLevel, list[tuple[str, str, Decimal]]] = defaultdict(list)

    if cash_today:
        totals[RiskLevel.LOW] += cash_today
        items_by_level[RiskLevel.LOW].append(("cash", _CLASS_META["cash"][0], cash_today))
    if deposits_today:
        totals[RiskLevel.LOW] += deposits_today
        items_by_level[RiskLevel.LOW].append(("deposits", _CLASS_META["deposits"][0], deposits_today))

    for asset_id, name, risk_level in asset_rows:
        value = current_by_asset.get(asset_id, Decimal("0"))
        if value == 0:
            continue
        totals[risk_level] += value
        items_by_level[risk_level].append((f"asset:{asset_id}", name, value))

    grand_total = sum(totals.values(), Decimal("0"))

    def _share(amount: Decimal, denominator: Decimal) -> float:
        return float(amount / denominator * 100) if denominator else 0.0

    summaries = []
    for level in RiskLevel:
        tier_total = totals.get(level, Decimal("0"))
        items = [
            RiskLevelItem(key=key, name=name, amount=amount, percent=_share(amount, tier_total))
            for key, name, amount in sorted(items_by_level.get(level, []), key=lambda item: item[2], reverse=True)
        ]
        summaries.append(
            RiskLevelSummary(
                risk_level=level.value,
                label=_RISK_META[level][0],
                color=_RISK_META[level][1],
                total_value=tier_total,
                percent=_share(tier_total, grand_total),
                items=items,
            )
        )
    return summaries


def _resolve_start_date(range_key: str, account_events: dict[str, list[tuple[date_, Decimal]]], asset_events: list[tuple[date_, Decimal]], today: date_) -> date_:
    if range_key in RANGE_DAYS:
        return today - timedelta(days=RANGE_DAYS[range_key] - 1)

    all_dates = [day for events in account_events.values() for day, _ in events] + [e[0] for e in asset_events]
    return min(all_dates) if all_dates else today


async def get_net_worth_summary(session: AsyncSession, range_key: str) -> NetWorthSummary:
    today = date_.today()
    account_events = await _account_cumulative_events(session)
    asset_events, class_totals, current_by_asset = await _asset_events_and_class_totals(session)
    capital_roles = await _capital_role_summary(session, current_by_asset)

    start = _resolve_start_date(range_key, account_events, asset_events, today)

    cash_series = _daily_series(account_events["cash"], start, today)
    deposit_series = _daily_series(account_events["deposits"], start, today)
    asset_series = _daily_series(asset_events, start, today)
    series = [
        NetWorthPoint(date=c.date, value=c.value + d.value + a.value)
        for c, d, a in zip(cash_series, deposit_series, asset_series, strict=True)
    ]

    current = series[-1].value if series else Decimal("0")
    start_value = series[0].value if series else Decimal("0")
    change_amount = current - start_value
    change_percent = float(change_amount / start_value * 100) if start_value else None

    # Account event entries are already cumulative — the last one in each
    # group is today's total, including the current exchange-rate valuation.
    cash_events = account_events["cash"]
    deposit_events = account_events["deposits"]
    cash_today = cash_events[-1][1] if cash_events else Decimal("0")
    deposits_today = deposit_events[-1][1] if deposit_events else Decimal("0")
    risk_levels = await _risk_level_summary(session, current_by_asset, cash_today, deposits_today)

    total = cash_today + deposits_today + sum(class_totals.values(), Decimal("0"))

    def _percent(amount: Decimal) -> float:
        return float(amount / total * 100) if total else 0.0

    breakdown = []
    name, color, icon = _CLASS_META["cash"]
    breakdown.append(NetWorthBreakdownItem(key="cash", name=name, color=color, icon=icon, amount=cash_today, percent=_percent(cash_today)))
    name, color, icon = _CLASS_META["deposits"]
    breakdown.append(NetWorthBreakdownItem(key="deposits", name=name, color=color, icon=icon, amount=deposits_today, percent=_percent(deposits_today)))
    for asset_class in AssetClass:
        name, color, icon = _CLASS_META[asset_class.value]
        amount = class_totals.get(asset_class, Decimal("0"))
        breakdown.append(
            NetWorthBreakdownItem(key=asset_class.value, name=name, color=color, icon=icon, amount=amount, percent=_percent(amount))
        )

    return NetWorthSummary(
        range=range_key,
        current=current,
        change_amount=change_amount,
        change_percent=change_percent,
        series=series,
        breakdown=breakdown,
        capital_roles=capital_roles,
        risk_levels=risk_levels,
    )
