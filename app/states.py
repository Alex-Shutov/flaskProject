from telebot.states import State, StatesGroup
class DirectStates(StatesGroup):
    type_product=State()       # выбор типа продукта
    product_id = State()       # выбор продукта
    param_id = State()         # выбор параметра продукта
    gift = State()             # ввод подарка
    note = State()             # примечание
    sale_type = State()        # выбор типа продажи
    pack_id = State()
    command =State()
    total_price = State()


class AvitoStates(StatesGroup):
    avito_photo = State()
    avito_message=State()
    invoice_photo = State()
    order_id=State()
    total_price=State()

class CourierStates(StatesGroup):
    accepted = State()
    orders=State()
    reply_message_id=State()
    picked_order=State()
    message_to_edit=State()

class AppStates(StatesGroup):
    user_info=State()
    picked_action = State()
    enter_date_range=State()
    start_date=State()
    end_date=State()

class AdminStates(StatesGroup):
    choose_type_product = State()  # выбор типа продукта
    manage_type_product = State()  # управление типом продукта
    enter_type_product_name = State()  # добавление названия типа продукта
    enter_type_product_params = State()  # ввод параметров типа продукта
    enter_product_name = State()  # добавление названия продукта
    enter_inherited_param_values = State()  # ввод значений унаследованных параметров
    enter_product_additional_params = State()  # ввод дополнительных параметров продукта
    manage_product = State()  # управление продуктом
    view_product = State()  # просмотр продуктов
    add_product = State()  # добавление продукта
    add_product_param = State()  # добавление параметров продукта
    admin_command=State()
    choose_product = State()
    enter_product_params=State()
    enter_product_specific_params=State()
    enter_product_param_values=State()
    enter_product_stock=State()
    enter_product_param_title=State()
    selected_type_product_info=State()

class ReportStates(StatesGroup):
    report_type_id = State()
    report_type=State()
    report_period=State()
class DeliveryStates(StatesGroup):
    delivery_date=State()   # объект для avito
    delivery_delivery_timedate=State()   # объект для avito
    delivery_address=State()   # объект для avito
    delivery_note=State()   # объект для avito
    contact_phone=State()   # объект для avito
    contact_name=State()   # объект для avito
    total_amount=State()   # объект для avito
    delivery_time=State()   # объект для avito
