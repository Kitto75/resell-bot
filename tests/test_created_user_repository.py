import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.models import Base, CreatedUser, Reseller
from app.database.repositories import CreatedUserRepository


def test_created_users_list_by_reseller_is_paginated_owned_and_newest_first():
    async def run() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with sessionmaker() as session, session.begin():
            reseller = Reseller(telegram_id=1001, display_name="r1", balance=Decimal("0"), price_per_gb=Decimal("1"))
            other = Reseller(telegram_id=1002, display_name="r2", balance=Decimal("0"), price_per_gb=Decimal("1"))
            session.add_all([reseller, other])
            await session.flush()
            base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
            for idx in range(12):
                session.add(CreatedUser(reseller_id=reseller.id, username=f"own_{idx}", created_at=base_time + timedelta(minutes=idx)))
            session.add(CreatedUser(reseller_id=other.id, username="other_user", created_at=base_time + timedelta(days=1)))

        async with sessionmaker() as session:
            repo = CreatedUserRepository(session)
            first_page = await repo.list_by_reseller(reseller.id, limit=10, offset=0)
            second_page = await repo.list_by_reseller(reseller.id, limit=10, offset=10)
            first_usernames = await repo.list_usernames_by_reseller(reseller.id, limit=10, offset=0)
            second_usernames = await repo.list_usernames_by_reseller(reseller.id, limit=10, offset=10)
            total = await repo.count_by_reseller(reseller.id)

        assert total == 12
        assert [user.username for user in first_page] == [f"own_{idx}" for idx in range(11, 1, -1)]
        assert [user.username for user in second_page] == ["own_1", "own_0"]
        assert first_usernames == [f"own_{idx}" for idx in range(11, 1, -1)]
        assert second_usernames == ["own_1", "own_0"]
        assert all(user.username != "other_user" for user in first_page + second_page)
        assert "other_user" not in first_usernames + second_usernames
        await engine.dispose()

    asyncio.run(run())
