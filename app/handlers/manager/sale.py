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

from database import get_all_users, get_user_info_by_id, get_active_showroom_visits, update_showroom_visit_status, \
    get_showroom_visit, create_showroom_visit


# Инициализация хранилища состояний
bot = get_bot_instance()


@bot.message_handler(func=lambda message: message.text == '#Продажа')
def handle_sale(message, state: StateContext):
    chat_id = message.chat.id
    state.delete()

    # Начинаем с выбора типа продажи
    state.set(SaleStates.sale_type)
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("Прямая", callback_data="select_viewer"))
    markup.add(types.InlineKeyboardButton("Доставка", callback_data="sale_delivery"))
    markup.add(types.InlineKeyboardButton("Авито", callback_data="sale_avito"))
    markup.add(types.InlineKeyboardButton("СДЭК", callback_data="sale_sdek"))
    markup.add(types.InlineKeyboardButton("ПЭК", callback_data="sale_pek"))
    markup.add(types.InlineKeyboardButton("ЛУЧ", callback_data="sale_luch"))
    bot.send_message(chat_id, "Выберите тип продажи:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('sale_') or call.data in ['sale_sdek', 'sale_pek', 'sale_luch'], state=SaleStates.sale_type)
def handle_sale_type(call: types.CallbackQuery, state: StateContext):
    with state.data() as data:
        sale_type_state = data.get('sale_type', None)
    sale_type =  call.data.split('_')[1] if not sale_type_state else sale_type_state
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
            elif sale_type in ['direct', 'sdek', 'pek', 'luch']:  # Обработка новых типов
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





@bot.callback_query_handler(func=lambda call: call.data == 'skip')
def skip_note(call: types.CallbackQuery, state: StateContext):
    state.add_data(note=None)
    with state.data() as data:
        sale_type = data.get('sale_type')
    if sale_type == 'avito':
        check_packing_requirements(call.message.chat.id, state)
    elif sale_type in ['sdek', 'pek', 'luch']:  # Для новых типов запрашиваем delivery_sum
        state.set(SaleStates.delivery_sum)
        bot.send_message(call.message.chat.id, "Введите стоимость доставки:")
    else:
        state.set(SaleStates.total_price)
        bot.send_message(call.message.chat.id, "Введите общую сумму для заказа")

@bot.message_handler(state=SaleStates.note, func=lambda message: True)
def process_note(message: types.Message, state: StateContext):
    note = message.text.strip()
    state.add_data(note=note)
    with state.data() as data:
        sale_type = data.get('sale_type')
    if sale_type == 'avito':
        check_packing_requirements(message.chat.id, state)
    elif sale_type in ['sdek', 'pek', 'luch']:  # Для новых типов запрашиваем delivery_sum
        state.set(SaleStates.delivery_sum)
        bot.send_message(message.chat.id, "Введите стоимость доставки:")
    else:
        state.set(SaleStates.total_price)
        bot.send_message(message.chat.id, "Введите общую сумму")


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
            original_manager_id = order_data.get("original_manager_id",None)
            original_manager_name = order_data.get("original_manager_name",None)
            original_manager_username = order_data.get("original_manager_username",None)
            visit_id = order_data.get("visit_id",None)
            gift = order_data.get("gift")
            note = order_data.get("note")
            sale_type = order_data.get("sale_type")
            total_price = order_data.get("total_price")
            viewer_id = order_data.get("viewer_id")
            delivery_sum = order_data.get("delivery_sum")

            if not all([product_dict, sale_type]):
                bot.send_message(chat_id, "Не хватает данных для оформления заказа. Пожалуйста, начните процесс заново.")
                return

            try:
                manager_info = get_user_info(username)
                if not manager_info:
                    bot.send_message(chat_id, "Не удалось получить информацию о менеджере.")
                    return
                viewer_info = None
                if viewer_id:
                    viewer_info = get_user_info_by_id(viewer_id)
                print(manager_info)
                print('manager_info')
                manager_id = manager_info['id']
                manager_name = manager_info['name']
                manager_username = manager_info['username']

                process_product_stock(product_dict)

                # Создаем основной заказ
                order = create_order(product_dict, gift, note, sale_type, manager_id, message_id,
                                     viewer_id=viewer_id,
                                        total_price=total_price,
                delivery_sum = delivery_sum)
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
                    order['id'], order['values']['general'], gift, note, sale_type, manager_name if not viewer_info else original_manager_name, manager_username if not viewer_info else original_manager_username, total_price=total_price, delivery_sum=delivery_sum,  viewer_name=viewer_info['name'] if viewer_info else None,
                    viewer_username=viewer_info['username'] if viewer_info else None,
                )
                bot.send_message(chat_id, order_message)
                reply_message_id = bot.send_message(CHANNEL_CHAT_ID, order_message)
                update_order_message_id(order['id'],reply_message_id.message_id)

                update_showroom_visit_status(visit_id, 'completed') if not visit_id else None

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


@bot.callback_query_handler(func=lambda call: call.data == 'select_viewer', state=SaleStates.sale_type)
def handle_direct_sale(call: types.CallbackQuery, state: StateContext):
    """Handler for direct sales - shows viewer selection"""
    users = get_all_users()

    markup = types.InlineKeyboardMarkup()

    # Создаем временный список для хранения кнопок
    buttons = []
    for user in users:
        btn_text = f"{user['name']}"
        buttons.append(types.InlineKeyboardButton(btn_text, callback_data=f"viewer_{user['id']}"))

    # Добавляем кнопки попарно
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            # Если есть пара кнопок, добавляем обе
            markup.row(buttons[i], buttons[i + 1])
        else:
            # Если осталась одна кнопка, добавляем её одну
            markup.row(buttons[i])

    # Добавляем кнопку "Пропустить" отдельной строкой на всю ширину
    markup.row(types.InlineKeyboardButton("Пропустить", callback_data="sale_direct"))

    bot.edit_message_text(
        "Выберите, кто будет показывать товары в шоуруме:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )
    state.set(SaleStates.sale_type)

@bot.callback_query_handler(func=lambda call: call.data.startswith('viewer_'))
def handle_viewer_selection(call: types.CallbackQuery, state: StateContext):
    """Handles viewer selection and note input"""
    viewer_id = int(call.data.split('_')[1])
    state.add_data(viewer_id=viewer_id)

    bot.edit_message_text(
        "Введите заметку для показывающего:",
        call.message.chat.id,
        call.message.message_id
    )
    state.set(SaleStates.viewer_note)


@bot.message_handler(state=SaleStates.viewer_note)
def handle_viewer_note(message: types.Message, state: StateContext):
    if not is_valid_command(message.text, state):
        return
    """Handles viewer note and creates showroom visit"""
    with state.data() as data:
        viewer_id = data['viewer_id']
        viewer_info = get_user_info_by_id(viewer_id)
        manager_info = get_user_info(message.from_user.username)

        # Create showroom visit
        visit_id = create_showroom_visit(
            manager_id=manager_info['id'],
            viewer_id=viewer_id,
            note=message.text
        )
        # Notify manager
        bot.reply_to(message,
                     f"Просмотр зарегистрирован за {viewer_info['name']} ({viewer_info['username']})")

        # Notify viewer
        viewer_markup = types.InlineKeyboardMarkup(row_width=1)
        viewer_markup.add(
            types.InlineKeyboardButton("Оформить продажу", callback_data=f"complete_visit_{visit_id}"),
            types.InlineKeyboardButton("Отказались от покупки", callback_data=f"cancel_visit_{visit_id}")
        )

        bot.send_message(
            viewer_info['telegram_id'],
            f"Менеджер {manager_info['name']} ({manager_info['username']}) зарегистрировал на вас просмотр\n\n"
            f"Заметка от менеджера:\n{message.text}\n\n"
            "После того, как покупатель выберет товары, нажмите на Оформить продажу\n\n"
            "Если покупатель отказался от покупки, нажмите на 'Отказались от покупки'",
            reply_markup=viewer_markup
        )
        state.delete()




@bot.callback_query_handler(func=lambda call: call.data.startswith('complete_visit_'))
def handle_complete_visit(call: types.CallbackQuery, state: StateContext):
    """Handles completion of showroom visit"""
    visit_id = int(call.data.split('_')[2])
    visit_info = get_showroom_visit(visit_id)

    state.add_data(
        sale_type ='direct',
        original_manager_id = visit_info['manager_id'],
        original_manager_name=visit_info['manager_name'],
        original_manager_username=visit_info['manager_username'],
        viewer_id =visit_info['viewer_id']
    )

    handle_sale_type(call, state)


@bot.callback_query_handler(func=lambda call: call.data.startswith('cancel_visit_'))
def handle_cancel_visit(call: types.CallbackQuery, state: StateContext):
    """Handles cancellation of showroom visit"""
    visit_id = int(call.data.split('_')[2])
    update_showroom_visit_status(visit_id, 'cancelled')

    bot.edit_message_reply_markup(
        call.message.chat.id,
        call.message.message_id,
        reply_markup=None
    )
    bot.delete_message(call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id, "Продажа отменена((((")


@bot.message_handler(state=SaleStates.delivery_sum)
def handle_delivery_sum(message: types.Message, state: StateContext):
    if not is_valid_command(message.text, state): return
    try:
        delivery_sum = float(message.text)
        state.add_data(delivery_sum=delivery_sum)
        state.set(SaleStates.total_price)  # После delivery_sum переходим к total_price
        bot.send_message(message.chat.id, "Введите общую сумму для заказа:")
    except ValueError:
        bot.send_message(message.chat.id, "Некорректный формат стоимости доставки. Введите число.")