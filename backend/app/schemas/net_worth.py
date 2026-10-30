from datetime import date as date_
from decimal import Decimal

from pydantic import BaseModel


class NetWorthPoint(BaseModel):
    date: date_
    value: Decimal


class NetWorthBreakdownItem(BaseModel):
    key: str
    name: str
    color: str
    icon: str
    amount: Decimal
    percent: float


class CapitalRoleSummary(BaseModel):
    """Assets grouped by how they behave month to month (see CapitalRole) —
    a cross-cut of the asset-class breakdown, not a replacement for it."""

    role: str
    label: str
    color: str
    total_value: Decimal
    monthly_cash_flow: Decimal
    count: int


class RiskLevelItem(BaseModel):
    """One holding within a risk tier — Cash, Deposits, or a single asset
    (key=f"asset:{id}"). This list IS the diversification view: a tier with
    one item at 100% is concentrated, several items with even shares aren't,
    no separate score needed."""

    key: str
    name: str
    amount: Decimal
    percent: float  # share of this tier, not of total capital


class RiskLevelSummary(BaseModel):
    """Account balances + assets grouped by user-tagged risk of loss
    (see RiskLevel) — another cross-cut, like capital_roles. Available cash
    and deposits participate as the low-risk anchor of the allocation."""

    risk_level: str
    label: str
    color: str
    total_value: Decimal
    percent: float  # share of total capital (cash + assets)
    items: list[RiskLevelItem]


class NetWorthSummary(BaseModel):
    range: str
    current: Decimal
    change_amount: Decimal
    change_percent: float | None
    series: list[NetWorthPoint]
    breakdown: list[NetWorthBreakdownItem]
    capital_roles: list[CapitalRoleSummary]
    risk_levels: list[RiskLevelSummary]
