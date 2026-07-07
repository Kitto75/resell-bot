from aiogram.fsm.state import State, StatesGroup

class AddReseller(StatesGroup):
    telegram_id = State()
    balance = State()
    price = State()
    display_name = State()
    confirm = State()

class EditReseller(StatesGroup):
    select = State()
    field = State()
    value = State()
    confirm = State()

class BalanceEdit(StatesGroup):
    select = State()
    action = State()
    amount = State()
    confirm = State()

class MaintenanceMode(StatesGroup):
    menu = State()
    confirm = State()

class InboundPermissions(StatesGroup):
    select_reseller = State()
    edit = State()
    confirm = State()

class TransactionBrowsing(StatesGroup):
    select_reseller = State()
    browse = State()

class RechargeModeration(StatesGroup):
    confirm = State()
    reject_reason = State()

# Backward-compatible names for old imports/deployments.
class AdminReseller(AddReseller):
    pass
class RejectRecharge(StatesGroup):
    reason = State()

class BackupSettings(StatesGroup):
    interval = State()


class TelegramAccountManagement(StatesGroup):
    select_reseller = State()
    add = State()


class AdminCreateMarzbanUser(StatesGroup):
    username = State()
    gb = State()
    days = State()
    confirm = State()


class AdminRenewMarzbanUser(StatesGroup):
    username = State()
    confirm_user = State()
    gb = State()
    days = State()
    confirm = State()


class AdminDisableMarzbanUser(StatesGroup):
    username = State()
    confirm = State()


class AdminEnableMarzbanUser(StatesGroup):
    username = State()
    confirm = State()


class AdminDeleteMarzbanUser(StatesGroup):
    username = State()
    confirm = State()
