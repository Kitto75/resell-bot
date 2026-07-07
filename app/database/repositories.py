import builtins
from decimal import Decimal
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import BalanceTransaction, BotSetting, CreatedUser, RechargeRequest, Reseller, ResellerInbound, ResellerStatus, ResellerTelegramAccount, TransactionType


class ResellerRepository:
    def __init__(self, session: AsyncSession) -> None: self.session = session
    async def get_by_telegram_id(self, telegram_id: int) -> Reseller | None:
        account = await self.session.scalar(select(ResellerTelegramAccount).where(ResellerTelegramAccount.telegram_id == telegram_id))
        if account is not None:
            return await self.session.get(Reseller, account.reseller_id)
        return await self.session.scalar(select(Reseller).where(Reseller.telegram_id == telegram_id))
    async def get(self, reseller_id: int) -> Reseller | None: return await self.session.get(Reseller, reseller_id)
    async def list(self, include_archived: bool = False) -> builtins.list[Reseller]:
        stmt = select(Reseller).order_by(Reseller.display_name)
        if not include_archived: stmt = stmt.where(Reseller.status != ResellerStatus.archived)
        return list((await self.session.scalars(stmt)).all())
    async def add(self, telegram_id: int, display_name: str, balance: Decimal, price_per_gb: Decimal) -> Reseller:
        reseller = Reseller(telegram_id=telegram_id, display_name=display_name, balance=balance, price_per_gb=price_per_gb)
        self.session.add(reseller); await self.session.flush(); self.session.add(ResellerTelegramAccount(reseller_id=reseller.id, telegram_id=telegram_id, is_primary=True)); await self.session.flush(); return reseller
    async def telegram_accounts(self, reseller_id: int) -> builtins.list[ResellerTelegramAccount]:
        return list((await self.session.scalars(select(ResellerTelegramAccount).where(ResellerTelegramAccount.reseller_id == reseller_id).order_by(ResellerTelegramAccount.is_primary.desc(), ResellerTelegramAccount.telegram_id))).all())
    async def primary_telegram_id(self, reseller: Reseller) -> int:
        account = await self.session.scalar(select(ResellerTelegramAccount).where(ResellerTelegramAccount.reseller_id == reseller.id, ResellerTelegramAccount.is_primary == True))
        return account.telegram_id if account else reseller.telegram_id
    async def add_telegram_account(self, reseller_id: int, telegram_id: int, is_primary: bool = False) -> ResellerTelegramAccount:
        if is_primary:
            await self.session.execute(update(ResellerTelegramAccount).where(ResellerTelegramAccount.reseller_id == reseller_id).values(is_primary=False))
        account = ResellerTelegramAccount(reseller_id=reseller_id, telegram_id=telegram_id, is_primary=is_primary)
        self.session.add(account); await self.session.flush(); return account
    async def remove_telegram_account(self, account_id: int) -> bool:
        account = await self.session.get(ResellerTelegramAccount, account_id)
        if account is None: return False
        count = int(await self.session.scalar(select(func.count(ResellerTelegramAccount.id)).where(ResellerTelegramAccount.reseller_id == account.reseller_id)) or 0)
        if count <= 1: return False
        was_primary, reseller_id = account.is_primary, account.reseller_id
        await self.session.delete(account); await self.session.flush()
        if was_primary:
            replacement = await self.session.scalar(select(ResellerTelegramAccount).where(ResellerTelegramAccount.reseller_id == reseller_id).order_by(ResellerTelegramAccount.id))
            if replacement: replacement.is_primary = True
        return True
    async def set_primary_telegram_account(self, account_id: int) -> ResellerTelegramAccount | None:
        account = await self.session.get(ResellerTelegramAccount, account_id)
        if account is None: return None
        await self.session.execute(update(ResellerTelegramAccount).where(ResellerTelegramAccount.reseller_id == account.reseller_id).values(is_primary=False))
        account.is_primary = True
        reseller = await self.session.get(Reseller, account.reseller_id)
        if reseller: reseller.telegram_id = account.telegram_id
        await self.session.flush(); return account
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
    async def recent(self, reseller_id: int, tx_type: TransactionType | None = None, limit: int = 5, offset: int = 0) -> builtins.list[BalanceTransaction]:
        stmt = select(BalanceTransaction).where(BalanceTransaction.reseller_id == reseller_id)
        if tx_type is not None:
            stmt = stmt.where(BalanceTransaction.type == tx_type)
        stmt = stmt.order_by(BalanceTransaction.created_at.desc(), BalanceTransaction.id.desc()).limit(limit).offset(offset)
        return list((await self.session.scalars(stmt)).all())
