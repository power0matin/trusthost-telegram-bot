from aiogram.fsm.state import State, StatesGroup


class OrderStates(StatesGroup):
    quantity = State()
    custom = State()
    hostname = State()
    domain = State()
    rootpw = State()
    promo = State()


class TicketStates(StatesGroup):
    subject = State()
    message = State()
    reply = State()


class WalletStates(StatesGroup):
    amount = State()


class PromoStates(StatesGroup):
    renew = State()
    topup = State()
