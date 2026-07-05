from aiogram.fsm.state import State, StatesGroup
class CreateUser(StatesGroup):
    username = State(); gb = State(); days = State(); confirm = State()
class RenewUser(StatesGroup):
    username = State(); confirm_user = State(); gb = State(); days = State(); confirm = State()
class Recharge(StatesGroup):
    amount = State(); receipt = State()
