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

# Инициализация хранилища состояний
bot = get_bot_instance()



@bot.message_handler(func=lambda message: message.text == '#Продажа')
def handle_sale(message,state:StateContext):
    chat_id = message.chat.id
    state.delete()
    with state.data() as data:
        user_info = data.get('user_info')
    print(user_info)

    # user_state = load_user_state(chat_id)
    # if chat_id in user_state:
    #     state.delete()

    # state = bot.get_state(message.chat.id)
    state.set(SaleStates.type_product)

    product_types = get_product_type()
    markup = types.InlineKeyboardMarkup()
    for product_type in product_types:
        markup.add(types.InlineKeyboardButton(product_type[1], callback_data=f"type_product_{product_type[0]}"))
    bot.send_message(chat_id, "Выберите тип:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('type_product_'), state=SaleStates.type_product)
def handle_product_sale(call: types.CallbackQuery,state:StateContext):
    # user_state = load_user_state(chat_id)
    # if chat_id in user_state:
    #     state.delete()
    type_id = call.data.split('_')[2]
    # state = bot.get_state(message.chat.id)
    state.add_data(type_product=get_type_product_by_id(type_id))
    state.set(SaleStates.product_id)

    products = get_products(type_id)
    markup = types.InlineKeyboardMarkup()
    for product in products:
        markup.add(types.InlineKeyboardButton(product[1], callback_data=f"product_{product[0]}"))
    bot.send_message(call.message.chat.id, "Выберите продукт:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('product_'))
def handle_product_selection(call: types.CallbackQuery,state:StateContext):
    product_id = call.data.split('_')[1]
    # Сохраняем выбранный продукт в состоянии
    with state.data() as data:
        product_dict = data.get('product_dict', {})  # Используем словарь вместо отдельных списков
        if not product_dict.get(product_id):
            product_dict[product_id] = []  # Создаем запись для продукта с пустым списком параметров

    state.add_data(product_dict=product_dict)
    state.add_data(product_id=product_id)

    # Переходим в состояние выбора параметра продукта
    state.set(SaleStates.param_id)
    # save_param_to_redis(chat_id,'product_id', product_id)

    # Отправляем параметры продукта
    params = get_product_params(product_id)
    markup = types.InlineKeyboardMarkup()

    for param in params:
        markup.add(types.InlineKeyboardButton(f"{param[1]} (Осталось {param[2]})", callback_data=f"param_{param[0]}"))
    bot.edit_message_text("Выберите параметр продукта:", chat_id=call.message.chat.id,
                          message_id=call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ['yes_add_more', 'no_more_items'])
def handle_additional_product(call: types.CallbackQuery, state: StateContext):
    if call.data == 'yes_add_more':
        # Начинаем выбор нового продукта
        with state.data() as data:
            type_product = data.get('type_product')
            type_id = type_product['id']
        print('type_id')
        products = get_products(str(type_id))
        markup = types.InlineKeyboardMarkup()
        print(products)
        for product in products:
            markup.add(types.InlineKeyboardButton(product[1], callback_data=f"product_{product[0]}"))
        bot.send_message(call.message.chat.id, "Выберите дополнительный товар", reply_markup=markup)
        state.set(SaleStates.product_id)
    elif call.data == 'no_more_items':
        # Переход к добавлению подарка и завершению заказа
        state.set(SaleStates.gift)
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Пропустить", callback_data="skip"))
        bot.send_message(call.message.chat.id, "Введите текст подарка или нажмите 'Пропустить':", reply_markup=markup)


@bot.callback_query_handler(state=SaleStates.param_id, func=lambda call: call.data.startswith('param_'))
def handle_param_selection(call: types.CallbackQuery,state:StateContext):
    param_id = call.data.split('_')[1]
    # Сохраняем параметр
    # state = bot.get_state(call.message.chat.id)
    with state.data() as data:
        product_id = data.get('product_id')
        product_dict = data.get('product_dict', {})

        if product_id:
            product_dict[product_id].append(param_id)  # Добавляем параметр к продукту

    state.add_data(product_dict=product_dict)
    print("Обновленные данные:", product_dict)


    # state.add_data(param_id=param_id)
    # save_param_to_redis(chat_id, 'param_id', param_id)


    # Переход в состояние ввода подарка
    state.set(SaleStates.gift)


    # Спрашиваем текст подарка
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Да", callback_data="yes_add_more"))
    markup.add(types.InlineKeyboardButton("Нет", callback_data="no_more_items"))
    bot.edit_message_text("Хотите оформить дополнительный товар?", chat_id=call.message.chat.id,
                          message_id=call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(state=SaleStates.gift, func=lambda call: call.data == 'skip')
def skip_gift(call: types.CallbackQuery, state: StateContext):
    # Пропускаем ввод подарка
    # TODO добавить базовые параметры из типа продукта
    state.add_data(gift="Гирлянда 2м")
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





@bot.callback_query_handler(state=SaleStates.note, func=lambda call: call.data == 'skip')
def skip_note(call: types.CallbackQuery, state: StateContext):
    # Пропускаем ввод примечания
    state.add_data(note=None)
    # Переходим к выбору типа продажи
    state.set(SaleStates.sale_type)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Прямая", callback_data="sale_direct"))
    markup.add(types.InlineKeyboardButton("Доставка", callback_data="sale_delivery"))
    markup.add(types.InlineKeyboardButton("Авито", callback_data="sale_avito"))
    bot.send_message(call.message.chat.id, "Выберите тип продажи:", reply_markup=markup)

@bot.message_handler(state=SaleStates.note, func=lambda message: True)
def process_note(message: types.Message, state: StateContext):
    # Сохраняем текст примечания
    note = message.text.strip()
    state.add_data(note=note)
    # Переходим к выбору типа продажи
    state.set(SaleStates.sale_type)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Прямая", callback_data="sale_direct"))
    markup.add(types.InlineKeyboardButton("Доставка", callback_data="sale_delivery"))
    markup.add(types.InlineKeyboardButton("Авито", callback_data="sale_avito"))
    bot.send_message(message.chat.id, "Выберите тип продажи:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('sale_'), state=SaleStates.sale_type)
def handle_sale_type(call: types.CallbackQuery, state: StateContext):
    sale_type = call.data.split('_')[1]
    # Сохраняем тип продажи
    state.add_data(sale_type=sale_type)

    if sale_type == "avito":
        with state.data() as data:
            product_dict = data.get("product_dict", {})
        if not product_dict:
            bot.send_message(call.message.chat.id, "Нет продуктов для оформления заказа.")
            return

        total_products = sum(len(params) for params in product_dict.values())

        if total_products == 1:
            # Проверяем требует ли продукт упаковки
            product_id, param_ids = next(iter(product_dict.items()))
            product_info = get_product_info_with_params(product_id, param_ids[0])
            param_type = product_info.get("product_values", {}).get("Тип", None)

            if not param_type or param_type.lower() == "китай":
                # Пропускаем упаковку и переходим к загрузке фото
                bot.send_message(call.message.chat.id, "Данный продукт не требует упаковки")
                state.set(AvitoStates.avito_photo)
                bot.send_message(call.message.chat.id, "Пожалуйста, загрузите фотографию для Авито.")
            elif param_type.lower() == "россия":
                state.add_data(is_need_packing=True)
                # Предлагаем пользователю выбрать упаковку
                markup = types.InlineKeyboardMarkup(row_width=2)
                markup.add(
                    types.InlineKeyboardButton("Да", callback_data="pack_yes"),
                    types.InlineKeyboardButton("Нет", callback_data="pack_no")
                )
                bot.send_message(call.message.chat.id, "Упакуете продукт самостоятельно?", reply_markup=markup)
                state.set(SaleStates.pack_id)
            else:
                bot.send_message(call.message.chat.id, "Ошибка в параметрах продукта.")
        elif total_products >= 2:
            print('---hi---')
            state.add_data(is_need_packing=True)
            # Упаковка требуется обязательно
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("Да", callback_data="pack_yes"),
                types.InlineKeyboardButton("Нет", callback_data="pack_no")
            )
            bot.send_message(call.message.chat.id, "Упакуете все продукты самостоятельно?", reply_markup=markup)
            # state.set(SaleStates.is_need_packing)
            state.set(SaleStates.pack_id)
    elif sale_type == "delivery":
        handle_sale_delivery(call, state)
    elif sale_type == "direct":
        # Завершение заказа
        state.set(SaleStates.total_price)
        bot.send_message(call.message.chat.id, "Введите сумму для оплаты:")
    bot.answer_callback_query(call.id)



# @bot.callback_query_handler(func=lambda call: call.data in ['sale_avito', 'sale_delivery'], state=SaleStates.sale_type)
# def on_pack(call: types.CallbackQuery, state: StateContext):
#     # Получаем информацию о продукте и его параметрах
#     command = call.data
#     state.add_data(command=command)
#     if command == 'sale_delivery':
#         handle_sale_delivery(call, state)
#         return
#     with state.data() as data:
#         product_id = data.get("product_id")
#         product_info = get_product_info_with_params(product_id)
#         param_type = product_info.get("product_values", {}).get("Тип", None)
#     # Проверяем значение параметра "Тип"
#     if not param_type or param_type.lower() == "Россия".lower():
#         # Пропускаем упаковку и переходим сразу к загрузке фотографии
#         bot.send_message(call.message.chat.id, "Данный продукт не требует упаковки")
#
#         state.set(AvitoStates.avito_photo)
#         bot.send_message(call.message.chat.id, "Пожалуйста, загрузите фотографию для Авито.")
#     elif param_type.lower() == "Китай".lower():
#         # Если продукт требует упаковки, то предлагаем пользователю выбрать
#         markup = types.InlineKeyboardMarkup(row_width=2)
#         markup.add(types.InlineKeyboardButton("Да", callback_data="pack_yes"))
#         markup.add(types.InlineKeyboardButton("Нет", callback_data="pack_no"))
#         bot.send_message(call.message.chat.id, "Упакуете продукт самостоятельно?", reply_markup=markup)
#         state.set(SaleStates.pack_id)
#     else:
#         bot.send_message(call.message.chat.id, "Ошибка в параметрах продукта.")

@bot.callback_query_handler(state=SaleStates.pack_id, func=lambda call: call.data in ['pack_yes', 'pack_no'])
def handle_pack(call: types.CallbackQuery, state: StateContext):
    data = call.data.split('_')[1]
    user_info = get_user_by_username(call.from_user.username, state)
    with state.data() as data:
        command = data.get("command")
    if data == 'yes':
        bot.send_message(call.message.chat.id, "Вы выбрали упаковать продукт самостоятельно.")
        state.add_data(pack_id=user_info['id'])
        state.set(AvitoStates.avito_photo)
        bot.send_message(call.message.chat.id, "Пожалуйста, загрузите фотографию для Авито.")
    else:
        state.set(AvitoStates.avito_photo)
        bot.send_message(call.message.chat.id, "Пожалуйста, загрузите фотографию для Авито.")

@bot.callback_query_handler(state=SaleStates.sale_type, func=lambda call: True)
def handle_sale_type(call: types.CallbackQuery,state:StateContext):
    sale_type = call.data.split('_')[1]
    # Сохраняем тип продажи
    state.add_data(sale_type=sale_type)

    if sale_type == "avito":
        # Переход к состоянию загрузки фото для Авито
        state.set(AvitoStates.avito_photo)
        bot.send_message(call.message.chat.id, "Пожалуйста, загрузите фотографию для Авито.")
    elif sale_type == "direct":
        # Завершение заказа
        state.set(SaleStates.total_price)
        bot.send_message(call.message.chat.id, "Введите сумму для оплаты:")
        # handle_total_price(call.message,state)
        # finalize_order(call.message.chat.id,call.from_user.username,call.message.message_id,state)

@bot.message_handler(state=SaleStates.total_price)
def handle_total_price(message:types.Message,state:StateContext):
    if not is_valid_command(message.text, state): return
    try:
        total_amount = float(message.text)
        state.add_data(total_price=total_amount)
        # Завершаем процесс оформления заказа
        print(123)
        review_order_data(message.chat.id, state)
        # finalize_order(message.chat.id,message.from_user.username,message.message_id,state)
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
                    order['id'], order['values'], gift, note, sale_type, manager_name, manager_username, total_price=total_price
                )
                bot.send_message(chat_id, order_message)
                reply_message_id = bot.send_message(CHANNEL_CHAT_ID, order_message)
                update_order_message_id(order['id'],reply_message_id.message_id)


                process_product_stock(product_dict)
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
