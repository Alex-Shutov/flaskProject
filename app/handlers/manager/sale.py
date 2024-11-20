from itertools import product

from redis.cluster import command
from telebot import types
from bot import get_bot_instance, get_user_state
from states import DirectStates as SaleStates, AvitoStates
from config import CHANNEL_CHAT_ID
from telebot.states.sync.context import StateContext
from database import check_user_access, get_products, get_product_params, create_order, get_user_info, get_product_info,get_product_type,create_order_items
from app_types import UserRole
from redis_client import save_user_state, load_user_state, delete_user_state
from utils import format_order_message

from handlers.handlers import get_user_by_username

from states import AppStates

from database import get_orders

from database import get_type_product_by_id

from app_types import OrderType
from database import update_order_status

from database import get_product_info_with_params

from database import decrement_stock

from handlers.manager.delivery import handle_sale_delivery

from utils import is_valid_command

from handlers.handlers import review_order_data

from handlers.handlers import process_product_stock

from database import update_order_message_id

from states import DirectStates

from database import get_setting_value

from database import check_packing_before_order

# Инициализация хранилища состояний
bot = get_bot_instance()


@bot.message_handler(func=lambda message: message.text == '#Продажа')
def handle_sale(message, state: StateContext):
    chat_id = message.chat.id
    state.delete()

    # Начинаем с выбора типа продажи
    state.set(SaleStates.sale_type)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Прямая", callback_data="sale_direct"))
    markup.add(types.InlineKeyboardButton("Доставка", callback_data="sale_delivery"))
    markup.add(types.InlineKeyboardButton("Авито", callback_data="sale_avito"))
    bot.send_message(chat_id, "Выберите тип продажи:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('sale_'), state=SaleStates.sale_type)
def handle_sale_type(call: types.CallbackQuery, state: StateContext):
    sale_type = call.data.split('_')[1]
    state.add_data(sale_type=sale_type)

    # Переходим к выбору типа продукта
    state.set(SaleStates.type_product)

    product_types = get_product_type()
    markup = types.InlineKeyboardMarkup()
    for product_type in product_types:
        markup.add(types.InlineKeyboardButton(product_type[1], callback_data=f"type_product_{product_type[0]}"))
    bot.edit_message_text("Выберите тип продукта:",
                          chat_id=call.message.chat.id,
                          message_id=call.message.message_id,
                          reply_markup=markup)


@bot.callback_query_handler(state=SaleStates.type_product)
def handle_product_type(call: types.CallbackQuery, state: StateContext):
    with state.data() as data:
        type = data.get('type_product')
    print(123)
    type_id = call.data.split('_')[2] if not type else str(type['id'])
    state.add_data(type_product=get_type_product_by_id(type_id))
    state.set(SaleStates.product_id)

    products = get_products(type_id)
    markup = types.InlineKeyboardMarkup()
    for product in products:
        markup.add(types.InlineKeyboardButton(product[1], callback_data=f"product_{product[0]}"))
    bot.edit_message_text("Выберите продукт:",
                          chat_id=call.message.chat.id,
                          message_id=call.message.message_id,
                          reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('product_'), state=SaleStates.product_id)
def handle_product_selection(call: types.CallbackQuery, state: StateContext):
    product_id = call.data.split('_')[1]
    with state.data() as data:
        product_dict = data.get('product_dict', {})
        if not product_dict.get(product_id):
            product_dict[product_id] = []

    state.add_data(product_dict=product_dict)
    state.add_data(product_id=product_id)
    state.set(SaleStates.param_id)

    params = get_product_params(product_id)
    markup = types.InlineKeyboardMarkup()
    for param in params:
        markup.add(types.InlineKeyboardButton(f"{param[1]} (Осталось {param[2]})",
                                              callback_data=f"param_{param[0]}"))
    bot.edit_message_text("Выберите параметр продукта:",
                          chat_id=call.message.chat.id,
                          message_id=call.message.message_id,
                          reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('param_'), state=SaleStates.param_id)
def handle_param_selection(call: types.CallbackQuery, state: StateContext):
    param_id = call.data.split('_')[1]
    with state.data() as data:
        product_id = data.get('product_id')
        product_dict = data.get('product_dict', {})
        if product_id:
            product_dict[product_id].append(param_id)

    state.add_data(product_dict=product_dict)

    # Спрашиваем про дополнительный товар
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Да", callback_data="yes_add_more"))
    markup.add(types.InlineKeyboardButton("Нет", callback_data="no_more_items"))
    bot.edit_message_text("Хотите добавить дополнительный товар?",
                          chat_id=call.message.chat.id,
                          message_id=call.message.message_id,
                          reply_markup=markup)


def finalize_sale_process(call: types.CallbackQuery, state: StateContext):
    with state.data() as data:
        sale_type = data.get('sale_type')

    if sale_type == "avito":
        # Проверяем необходимость упаковки
        with state.data() as data:
            product_dict = data.get("product_dict", {})
            if not product_dict:
                bot.send_message(call.message.chat.id, "Нет продуктов для оформления заказа.")
                return

            total_products = sum(len(params) for params in product_dict.values())
            state.set(SaleStates.total_price)
            bot.send_message(call.message.chat.id, "Введите сумму для оплаты:")

            if total_products >= 2 or needs_packing(product_dict):
                state.add_data(is_need_packing=True)
                markup = types.InlineKeyboardMarkup(row_width=2)
                markup.add(
                    types.InlineKeyboardButton("Да", callback_data="pack_yes"),
                    types.InlineKeyboardButton("Нет", callback_data="pack_no")
                )
                bot.send_message(call.message.chat.id, "Упакуете продукт самостоятельно?",
                                 reply_markup=markup)
                state.set(SaleStates.pack_id)

    elif sale_type == "delivery":
        handle_sale_delivery(call, state)
    else:  # direct sale
        state.set(SaleStates.total_price)
        bot.send_message(call.message.chat.id, "Введите сумму для оплаты:")


@bot.callback_query_handler(func=lambda call: call.data in ['yes_add_more', 'no_more_items'])
def handle_additional_product(call: types.CallbackQuery, state: StateContext):
    if call.data == 'yes_add_more':
        with state.data() as data:
            type_product = data.get('type_product')
            type_id = type_product['id']

        products = get_products(str(type_id))
        markup = types.InlineKeyboardMarkup()
        for product in products:
            markup.add(types.InlineKeyboardButton(product[1], callback_data=f"product_{product[0]}"))
        bot.send_message(call.message.chat.id, "Выберите продукт", reply_markup=markup)
        state.set(SaleStates.product_id)
    else:
        with state.data() as data:
            sale_type = data.get('sale_type')
            if sale_type == 'avito':
                state.set(AvitoStates.avito_photo)
                state.set(AvitoStates.avito_photo)
                bot.send_message(call.message.chat.id, "Пожалуйста, загрузите фотографию для Авито.")
            elif sale_type == 'delivery':
                handle_sale_delivery(call,state)
            elif sale_type == 'direct':
                state.set(SaleStates.gift)
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("Пропустить", callback_data="skip"))
                bot.send_message(call.message.chat.id, "Введите текст подарка или нажмите 'Пропустить':",
                                 reply_markup=markup)

@bot.callback_query_handler(state=SaleStates.gift, func=lambda call: call.data == 'skip')
def skip_gift(call: types.CallbackQuery, state: StateContext):
    # Пропускаем ввод подарка
    # TODO добавить базовые параметры из типа продукта
    try:
        default_present = get_setting_value('default_present')
        if not default_present:
            default_present = "Гирлянда 3м"
    except Exception:
        default_present = "Гирлянда 3м"

    state.add_data(gift=default_present)
    # Переходим к состоянию примечания
    state.set(SaleStates.note)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Пропустить", callback_data='skip'))
    bot.edit_message_text("Введите примечание или нажмите 'Пропустить'", chat_id=call.message.chat.id,
                          message_id=call.message.message_id, reply_markup=markup)

@bot.message_handler(state=SaleStates.gift, func=lambda message: True)
def process_gift(message: types.Message, state: StateContext):
    # Сохраняем текст подарка
    gift = message.text.strip()
    state.add_data(gift=gift)
    # Переходим к состоянию примечания
    state.set(SaleStates.note)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Пропустить", callback_data='skip'))
    bot.send_message(message.chat.id, "Введите примечание или нажмите 'Пропустить'", reply_markup=markup)





@bot.callback_query_handler( func=lambda call: call.data == 'skip')
def skip_note(call: types.CallbackQuery, state: StateContext):
    state.add_data(note=None)
    with state.data() as data:
        sale_type = data.get('sale_type')
    if sale_type == 'avito':
        check_packing_requirements(call.message.chat.id, state)
    else:
        bot.send_message(call.message.chat.id, "Введите общую сумму для заказа")
        state.set(SaleStates.total_price)

@bot.message_handler(state=SaleStates.note, func=lambda message: True)
def process_note(message: types.Message, state: StateContext):
    note = message.text.strip()
    state.add_data(note=note)
    with state.data() as data:
        sale_type = data.get('sale_type')
    if sale_type == 'avito':
        check_packing_requirements(message.chat.id, state)
    else:
        bot.send_message(message.chat.id, "Введите общую сумму")
        state.set(SaleStates.total_price)


def check_packing_requirements(chat_id, state: StateContext):
    """
    Проверяет требования к упаковке для заказа используя правила из БД
    """
    with state.data() as data:
        product_dict = data.get('avito_products', {})
        sale_type = data.get('sale_type')

        # Проверяем необходимость упаковки
        needs_packing, reason = check_packing_before_order(product_dict, sale_type)

        # Сохраняем результат
        data['is_need_packing'] = needs_packing
        data['packing_reason'] = reason

        # Отправляем сообщение о результате
        message = "Товар требует упаковки" if needs_packing else "Товар не требует упаковки"
        message += f"\nПричина: {reason}"

        state.set(AvitoStates.total_price)
        # mess=bot.send_message(chat_id, message)
        review_order_data(chat_id, state)

@bot.callback_query_handler(func=lambda call: call.data in ['pack_yes', 'pack_no'], state=SaleStates.pack_id)
def handle_pack_choice(call: types.CallbackQuery, state: StateContext):
    """Обработчик выбора упаковщика"""
    if call.data == 'pack_yes':
        user = get_user_by_username(call.message.json['chat']['username'],state)
        # Если менеджер будет упаковывать сам
        state.add_data(pack_id=user['id'])
        bot.edit_message_text(
            "Вы будете упаковывать заказ самостоятельно.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id
        )
        review_order_data(call.message.chat.id,state)
    else:
        # Если нужен другой упаковщик
        state.add_data(pack_id=None)
        bot.edit_message_text(
            "Упаковщик будет назначен позже.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id
        )
        review_order_data(call.message.chat.id,state)


@bot.message_handler(state=SaleStates.total_price)
def handle_total_price(message: types.Message, state: StateContext):
    if not is_valid_command(message.text, state): return
    try:
        total_amount = float(message.text)
        state.add_data(total_price=total_amount)
        # Завершаем процесс оформления заказа
        review_order_data(message.chat.id, state)
        # finalize_avito_order(message.chat.id, message.message_id,message.from_user.username, state)
    except ValueError:
        bot.send_message(message.chat.id, "Некорректный формат суммы. Пожалуйста, введите число.")
def finalize_order(chat_id, username, message_id, state: StateContext):
    # Загружаем состояние пользователя через контекстный менеджер

    # Работаем с данными через контекстный менеджер
    with state.data() as order_data:
        if order_data:
            product_dict = order_data.get("product_dict")
            param_id = order_data.get("param_id")
            product_id = order_data.get("product_id")
            gift = order_data.get("gift")
            note = order_data.get("note")
            sale_type = order_data.get("sale_type")
            total_price = order_data.get("total_price")

            if not all([product_dict, sale_type]):
                bot.send_message(chat_id, "Не хватает данных для оформления заказа. Пожалуйста, начните процесс заново.")
                return

            try:
                manager_info = get_user_info(username)
                if not manager_info:
                    bot.send_message(chat_id, "Не удалось получить информацию о менеджере.")
                    return
                print(manager_info)
                print('manager_info')
                manager_id = manager_info['id']
                manager_name = manager_info['name']
                manager_username = manager_info['username']

                process_product_stock(product_dict)

                # Создаем основной заказ
                order = create_order(product_dict, gift, note, sale_type, manager_id, message_id,
                                        total_price=total_price)
                # Добавляем все товары в order_items
                # for i, product_id in enumerate(product_ids):
                #     product_info = get_product_info(product_id)
                #     product_name = product_info['name']
                #     product_values = product_info['product_values']
                #     is_main_product = product_info['is_main_product']
                #     param_id = param_ids[i]
                #
                #     # Добавляем товар в order_items
                #     create_order_items(order_id, product_id, product_name, product_values, is_main_product)
                update_order_status(order['id'],OrderType.CLOSED.value)
                order_message = format_order_message(
                    order['id'], order['values']['general'], gift, note, sale_type, manager_name, manager_username, total_price=total_price
                )
                bot.send_message(chat_id, order_message)
                reply_message_id = bot.send_message(CHANNEL_CHAT_ID, order_message)
                update_order_message_id(order['id'],reply_message_id.message_id)


                # Удаляем состояние после завершения заказа
                state.delete()
            except Exception as e:
                # state.delete()
                bot.send_message(chat_id, f"Произошла ошибка при оформлении заказа: {str(e)}")
        else:
            bot.send_message(chat_id, "Произошла ошибка при оформлении заказа. Пожалуйста, попробуйте снова.")

@bot.callback_query_handler(func=lambda call: call.data == 'orders_sold', state=AppStates.picked_action)
def show_sold_orders(call: types.CallbackQuery, state: StateContext):
    with state.data() as data:
        start_date = data['start_date']
        end_date = data['end_date']

    user_info = get_user_by_username(call.from_user.username, state)

    # Получаем заказы, где manager_id совпадает с текущим пользователем и статус "closed" или "refund"
    orders = get_orders(username=call.from_user.username, status=['closed', 'refund'], start_date=start_date, end_date=end_date)

    if not orders:
        bot.send_message(call.message.chat.id, "Нет проданных товаров за выбранный период.")
        return

    # Отправляем каждое сообщение через format_order_message
    for order in orders:
        order_message = format_order_message(
            order['id'], order['product_id'], order['product_param_id'], order['gift'],
            order['note'], order['order_type'], user_info['name'], user_info['username']
        )
        bot.send_message(call.message.chat.id, order_message)

# @bot.message_handler(func=lambda message: message.text == '#Заказы' and UserRole.MANAGER.value in get_user_info(message.from_user.username)['roles'])
# def handle_orders(message: types.Message, state: StateContext):
#     markup = types.InlineKeyboardMarkup()
#     markup.add(
#         types.InlineKeyboardButton("Активные заказы", callback_data='orders_show_active'),
#         types.InlineKeyboardButton("Мои заказы (в доставке)", callback_data='orders_show_in_delivery')
#     )
#     bot.send_message(message.chat.id, "Выберите тип заказов:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "cancel_order")
def handle_cancel_order(call: types.CallbackQuery, state: StateContext):
    """
    Обработчик отмены заказа.
    Полностью сбрасывает состояние и начинает процесс оформления заново.
    """
    # Удаляем текущее состояние
    state.delete()

    # Начинаем процесс заново
    message_id = call.message.message_id
    chat_id = call.message.chat.id

    # Удаляем сообщение с подтверждением заказа
    bot.delete_message(chat_id, message_id)

    # Начинаем с выбора типа продажи
    state.set(SaleStates.sale_type)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Прямая", callback_data="sale_direct"))
    markup.add(types.InlineKeyboardButton("Доставка", callback_data="sale_delivery"))
    markup.add(types.InlineKeyboardButton("Авито", callback_data="sale_avito"))

    bot.send_message(chat_id, "Выберите тип продажи:\n\n", reply_markup=markup)


