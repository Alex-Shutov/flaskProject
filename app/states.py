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
    product_dict=State()
    is_need_packing=State()
    total_price = State()


class AvitoStates(StatesGroup):
    avito_photo = State()
    avito_photos_tracks=State()
    avito_message=State()
    invoice_photo = State()
    order_id=State()
    track_number_manual=State()
    track_number=State()
    total_price=State()
    in_avito_photo = State()
    avito_products=State()
    next_step=State()
    track_price=State()


class CourierStates(StatesGroup):
    current_message_to_edit=State()
    accepted = State()
    orders=State()
    reply_message_id=State()
    picked_order=State()
    message_to_edit=State()
    waiting_for_route_location = State()
    selecting_delivered_items = State()  # выбор доставленных товаров
    entering_delivery_sum = State()      # ввод суммы доставки
    entering_delivery_note = State()     # ввод заметки
    viewing_order = State()              # просмотр заказа
    viewing_trip = State()               # просмотр поездки
    waiting_for_invoice = State()  # ожидание фото накладной
    processing_avito = State()  # обработка авито заказа


class AppStates(StatesGroup):
    user_info=State()
    picked_action = State()
    enter_date_range=State()
    start_date=State()
    enter_repacking_reason=State()
    end_date=State()
    enter_skip_reason = State()
    pending_skip_order_id = State()
    pending_skip_tracking = State()
    pending_skip_reply_message = State()
    enter_repack_reason=State()

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
    is_main_product=State()
    enter_product_param_values=State()
    enter_product_stock=State()
    enter_product_param_title=State()
    selected_type_product_info=State()
    manage_stock_type = State()
    manage_stock_product = State()
    manage_stock_param = State()
    manage_stock_action = State()
    manage_stock_quantity = State()
    manage_prices = State()
    enter_sale_price = State()
    enter_avito_price = State()
    editing_setting=State()
    edit_setting=State()
    select_supplier = State()
    manage_packing_rules=State()

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
    manual_date_input = State()

