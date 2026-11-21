from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import BalanceTransaction, CreatedUser, OperationLog, OperationType, Reseller, TransactionType

BYTES_PER_GB = 1024 ** 3
DUPLICATE_CREATE_WINDOW = timedelta(minutes=10)  # a second confirm for the same account within this time is a double click


def gb_to_bytes(gb) -> int:
    """Volume in GB (int, str or Decimal, e.g. 1.5) -> whole bytes."""
    return int((Decimal(str(gb)) * BYTES_PER_GB).to_integral_value(rounding=ROUND_HALF_UP))


class InsufficientBalanceError(ValueError): pass

class BillingService:
    def __init__(self, session: AsyncSession) -> None: self.session = session
    @staticmethod
    def calculate_cost(gb, price_per_gb: Decimal) -> Decimal:
        """Whole toman: a fractional volume such as 1.25 GB is priced and rounded half-up."""
        return (Decimal(str(gb)) * Decimal(price_per_gb)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    async def change_balance(self, reseller: Reseller, amount: Decimal, tx_type: TransactionType, description: str | None = None, created_by: int | None = None) -> BalanceTransaction:
        before = reseller.balance; after = before + amount
        if after < 0: raise InsufficientBalanceError("موجودی کافی نیست")
        reseller.balance = after
        tx = BalanceTransaction(reseller_id=reseller.id, type=tx_type, amount=amount, balance_before=before, balance_after=after, description=description, created_by=created_by)
        self.session.add(tx); await self.session.flush(); return tx
    async def charge_for_operation(self, reseller: Reseller, username: str, operation: OperationType, gb, days: int, actor_telegram_id: int | None = None, track_user: bool = True) -> OperationLog:
        gb = Decimal(str(gb))
        cost = self.calculate_cost(gb, reseller.price_per_gb)
        tx_type = TransactionType.create_user if operation == OperationType.create else TransactionType.renew_user
        tx = await self.change_balance(reseller, -cost, tx_type, f"{'ساخت' if operation == OperationType.create else 'تمدید'} {username}", actor_telegram_id or reseller.telegram_id)
        log = OperationLog(reseller_id=reseller.id, username=username, operation_type=operation, added_gb=gb, added_days=days, charged_amount=cost, balance_before=tx.balance_before, balance_after=tx.balance_after, created_by=actor_telegram_id or reseller.telegram_id)
        self.session.add(log)
        if operation == OperationType.create and track_user:
            self.session.add(CreatedUser(reseller_id=reseller.id, username=username, total_gb=gb, total_days=days))
        await self.session.flush(); return log

    async def charge_for_create_once(self, reseller: Reseller, username: str, gb, days: int, actor_telegram_id: int | None = None) -> OperationLog | None:
        """Charge for a freshly created panel account.

        Only a genuine double click is skipped (the same reseller already paid for this username a moment ago).
        A leftover local record - the account was deleted from the panel earlier and the name is being reused - must NOT
        make the new account free: the record is taken over and the account is charged and reported as usual."""
        existing = await self.session.scalar(select(CreatedUser).where(CreatedUser.username == username).with_for_update())
        if existing is None:
            return await self.charge_for_operation(reseller, username, OperationType.create, gb, days, actor_telegram_id)
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - DUPLICATE_CREATE_WINDOW
        paid_just_now = await self.session.scalar(select(OperationLog.id).where(
            OperationLog.reseller_id == reseller.id, OperationLog.username == username,
            OperationLog.operation_type == OperationType.create, OperationLog.created_at >= cutoff).limit(1))
        if paid_just_now is not None:
            return None
        log = await self.charge_for_operation(reseller, username, OperationType.create, gb, days, actor_telegram_id, track_user=False)
        existing.reseller_id = reseller.id
        existing.total_gb = Decimal(str(gb)); existing.total_days = days; existing.marzban_status = "on_hold"
        existing.created_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self.session.flush()
        return log
