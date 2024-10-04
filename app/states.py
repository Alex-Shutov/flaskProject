from telebot.states import State, StatesGroup
class DirectStates(StatesGroup):
    type_product=State()       # выбор типа продукта
    product_id = State()       # выбор продукта
    param_id = State()         # выбор параметра продукта
    gift = State()             # ввод подарка
    note = State()             # примечание
    sale_type = State()        # выбор типа продажи

class AvitoStates(StatesGroup):
    avito_photo = State()
    avito_message=State()
    invoice_photo = State()
    order_id=State()

class CourierStates(StatesGroup):
    accepted = State()
    orders=State()
    reply_message_id=State()
    picked_order=State()
    message_to_edit=State()

class AppStates(StatesGroup):
    user_info=State()
# class SaleStates:
#     direct = DirectStates()    # объект для direct
#     avito = AvitoStates()      # объект для avito