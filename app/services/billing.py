from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import BalanceTransaction, CreatedUser, OperationLog, OperationType, Reseller, TransactionType

BYTES_PER_GB = 1024 ** 3

class InsufficientBalanceError(ValueError): pass

class BillingService:
    def __init__(self, session: AsyncSession) -> None: self.session = session
    def calculate_cost(self, gb: int, price_per_gb: Decimal) -> Decimal: return Decimal(gb) * price_per_gb
    async def change_balance(self, reseller: Reseller, amount: Decimal, tx_type: TransactionType, description: str | None = None, created_by: int | None = None) -> BalanceTransaction:
        before = reseller.balance; after = before + amount
        if after < 0: raise InsufficientBalanceError("موجودی کافی نیست")
        reseller.balance = after
        tx = BalanceTransaction(reseller_id=reseller.id, type=tx_type, amount=amount, balance_before=before, balance_after=after, description=description, created_by=created_by)
        self.session.add(tx); await self.session.flush(); return tx
    async def charge_for_operation(self, reseller: Reseller, username: str, operation: OperationType, gb: int, days: int) -> OperationLog:
        cost = self.calculate_cost(gb, reseller.price_per_gb)
        tx_type = TransactionType.create_user if operation == OperationType.create else TransactionType.renew_user
        tx = await self.change_balance(reseller, -cost, tx_type, f"{'ساخت' if operation == OperationType.create else 'تمدید'} {username}", reseller.telegram_id)
        log = OperationLog(reseller_id=reseller.id, username=username, operation_type=operation, added_gb=gb, added_days=days, charged_amount=cost, balance_before=tx.balance_before, balance_after=tx.balance_after)
        self.session.add(log)
        if operation == OperationType.create:
            self.session.add(CreatedUser(reseller_id=reseller.id, username=username, total_gb=gb, total_days=days))
        await self.session.flush(); return log

    async def charge_for_create_once(self, reseller: Reseller, username: str, gb: int, days: int) -> OperationLog | None:
        existing = await self.session.scalar(select(CreatedUser).where(CreatedUser.username == username).with_for_update())
        if existing is not None:
            return None
        return await self.charge_for_operation(reseller, username, OperationType.create, gb, days)
