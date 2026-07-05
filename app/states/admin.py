from aiogram.fsm.state import State, StatesGroup
class AdminReseller(StatesGroup):
    telegram_id = State(); name = State(); balance = State(); price = State()
class RejectRecharge(StatesGroup):
    reason = State()
