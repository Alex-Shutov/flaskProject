from telebot.states import State, StatesGroup
class DirectStates(StatesGroup):
    product_id = State()       # выбор продукта
    param_id = State()         # выбор параметра продукта
    gift = State()             # ввод подарка
    note = State()             # примечание
    sale_type = State()        # выбор типа продажи

class AvitoStates(StatesGroup):
    avito_photo = State()
    avito_message=State()
    invoice_photo = State()

class CourierStates(StatesGroup):
    accepted = State()
    orders=State()
# class SaleStates:
#     direct = DirectStates()    # объект для direct
#     avito = AvitoStates()      # объект для avito