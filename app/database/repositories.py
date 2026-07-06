from decimal import Decimal
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import BalanceTransaction, BotSetting, CreatedUser, RechargeRequest, Reseller, ResellerInbound, ResellerStatus, TransactionType


class ResellerRepository:
    def __init__(self, session: AsyncSession) -> None: self.session = session
    async def get_by_telegram_id(self, telegram_id: int) -> Reseller | None:
        return await self.session.scalar(select(Reseller).where(Reseller.telegram_id == telegram_id))
    async def get(self, reseller_id: int) -> Reseller | None: return await self.session.get(Reseller, reseller_id)
    async def list(self, include_archived: bool = False) -> list[Reseller]:
        stmt = select(Reseller).order_by(Reseller.display_name)
        if not include_archived: stmt = stmt.where(Reseller.status != ResellerStatus.archived)
        return list((await self.session.scalars(stmt)).all())
    async def add(self, telegram_id: int, display_name: str, balance: Decimal, price_per_gb: Decimal) -> Reseller:
        reseller = Reseller(telegram_id=telegram_id, display_name=display_name, balance=balance, price_per_gb=price_per_gb)
        self.session.add(reseller); await self.session.flush(); return reseller
    async def count_users(self, reseller_id: int) -> int:
        return int(await self.session.scalar(select(func.count(CreatedUser.id)).where(CreatedUser.reseller_id == reseller_id)) or 0)


class SettingsRepository:
    def __init__(self, session: AsyncSession) -> None: self.session = session
    async def get(self, key: str, default: str | None = None) -> str | None:
        setting = await self.session.get(BotSetting, key)
        return default if setting is None else setting.value
    async def set(self, key: str, value: str) -> None:
        setting = await self.session.get(BotSetting, key)
        if setting is None: self.session.add(BotSetting(key=key, value=value))
        else: setting.value = value
    async def get_bool(self, key: str, default: bool = False) -> bool:
        setting = await self.session.get(BotSetting, key)
        return default if setting is None else setting.value == "1"
    async def set_bool(self, key: str, value: bool) -> None:
        await self.set(key, "1" if value else "0")


class InboundRepository:
    def __init__(self, session: AsyncSession) -> None: self.session = session
    async def allowed_tags(self, reseller_id: int) -> list[str]:
        return list((await self.session.scalars(select(ResellerInbound.inbound_tag).where(ResellerInbound.reseller_id == reseller_id))).all())
    async def set_allowed_tags(self, reseller_id: int, tags: list[str]) -> None:
        for item in (await self.session.scalars(select(ResellerInbound).where(ResellerInbound.reseller_id == reseller_id))).all():
            await self.session.delete(item)
        self.session.add_all([ResellerInbound(reseller_id=reseller_id, inbound_tag=tag) for tag in tags])


class RechargeRepository:
    def __init__(self, session: AsyncSession) -> None: self.session = session
    async def create(self, reseller_id: int, amount: Decimal, file_id: str | None, text: str | None) -> RechargeRequest:
        req = RechargeRequest(reseller_id=reseller_id, amount=amount, receipt_file_id=file_id, receipt_text=text)
        self.session.add(req); await self.session.flush(); return req
    async def get(self, request_id: int) -> RechargeRequest | None: return await self.session.get(RechargeRequest, request_id)


class TransactionRepository:
    def __init__(self, session: AsyncSession) -> None: self.session = session
    async def recent(self, reseller_id: int, tx_type: TransactionType | None = None, limit: int = 5, offset: int = 0) -> list[BalanceTransaction]:
        stmt = select(BalanceTransaction).where(BalanceTransaction.reseller_id == reseller_id)
        if tx_type is not None:
            stmt = stmt.where(BalanceTransaction.type == tx_type)
        stmt = stmt.order_by(BalanceTransaction.created_at.desc(), BalanceTransaction.id.desc()).limit(limit).offset(offset)
        return list((await self.session.scalars(stmt)).all())
