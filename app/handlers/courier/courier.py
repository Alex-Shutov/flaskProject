from ast import parse

from telebot import types
from bot import get_bot_instance
from database import get_couriers, update_order_status,get_user_info,update_order_courier,update_order_invoice_photo
from telebot.types import CallbackQuery, ReplyParameters, Message
from utils import format_order_message_for_courier,save_photo_and_resize,extract_order_number
from telebot.states.sync.context import StateContext
from states import AvitoStates, CourierStates
from config import CHANNEL_CHAT_ID
from app_types import OrderType
from database import get_orders

from app_types import UserRole

from states import AppStates

from handlers.handlers import get_user_by_username
from utils import format_order_message

from database import get_order_by_id

from database import decrement_stock

bot = get_bot_instance()

# Уведомление курьеров
@bot.message_handler(state=AvitoStates.avito_message, func=lambda message: True)
def notify_couriers(order_message,avito_photo,reply_message_id, state: StateContext):
    couriers = get_couriers()  # Получаем список пользователей с ролью Courier
    print(order_message)
    print(reply_message_id)
    # with state.data() as state_data
    #     order_date = get_order_by_id(order_id)
    #     avito_photo = state_data.get('avito_photo')
    #     order_message = state_data.get('avito_message')
    #     order_id = state_data.get('order_id')
    #     reply_message_id = state_data.get('reply_message_id')
    # # state.delete()
    for courier in couriers:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Принять заказ!", callback_data=f"accept_order_{extract_order_number(order_message)}_{reply_message_id}_{'has_avito_photo' if avito_photo else False}"))

        # Проверяем, есть ли фото для отправки
        if avito_photo:
            bot.send_photo(courier['telegram_id'], open(avito_photo, 'rb'), caption=order_message, reply_markup=markup)
        else:
            bot.send_message(courier['telegram_id'], order_message, reply_markup=markup)
    state.set(CourierStates.reply_message_id)




# Обработка завершения заказа (загрузка накладной)
@bot.message_handler(state=AvitoStates.invoice_photo, content_types=['photo'])
def handle_invoice_photo(message: types.Message, state: StateContext):
    chat_id = message.chat.id
    with state.data() as data:
        order_id = data.get('order_id')
        reply_message_id = data.get('reply_message_id')
        message_to_edit_id = data.get('message_to_edit')
    if message.photo:
        photo = message.photo[-1]
        file_info = bot.get_file(photo.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        invoice_path = save_photo_and_resize(downloaded_file, f"invoice_{chat_id}")
        # Сохраняем путь к накладной

        state.add_data(invoice_photo=invoice_path)
        update_order_invoice_photo(order_id, invoice_path)
        complete_order(order_id,reply_message_id,message_to_edit_id,message,invoice_path,message.from_user.username)

    else:
        bot.send_message(chat_id, "Пожалуйста, загрузите фото накладной.")


# Функция для показа активных заказов
@bot.callback_query_handler(func=lambda call: call.data == 'orders_show_active')
def show_active_orders(call: types.CallbackQuery, state: StateContext):
    # Получаем все активные заказы с типом 'avito' или 'delivery' и courier_id == null
    orders = get_orders(order_type=['avito', 'delivery'], status=[OrderType.READY_TO_DELIVERY.value], is_courier_null=True)
    if orders:
        for order in orders:
            order_message = format_order_message_for_courier(order)
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("Принять заказ", callback_data=f"accept_order_{order['id']}_{order['message_id']}_{'has_avito_photo' if order['avito_photo'] else False}"))
            if order['order_type'] == 'avito' and order.get('avito_photo'):
                # Если это Avito заказ и фото доступно
                with open(order['avito_photo'], 'rb') as photo:
                    bot.send_photo(
                        call.message.chat.id,
                        photo,
                        caption=order_message,
                        reply_markup=markup
                    )
            else:
                # Для доставки или отсутствующего фото Avito
                bot.send_message(
                    call.message.chat.id,
                    order_message,
                    reply_markup=markup
                )
    else:
        bot.send_message(call.message.chat.id, "Нет активных заказов")
    state.set(CourierStates.reply_message_id)
    # bot.answer_callback_query(call.id)

# Функция для показа заказов курьера в доставке
@bot.callback_query_handler(func=lambda call: call.data == 'orders_show_in_delivery')
def show_courier_orders_in_delivery(call: types.CallbackQuery, state: StateContext):
    user_info = get_user_info(call.from_user.username)  # Получаем информацию о курьере
    if not user_info:
        bot.answer_callback_query(call.id, "Не удалось получить информацию о пользователе.")
        return

    # Получаем заказы с типом 'in_delivery', где courier_id == id курьера
    orders = get_orders(order_type=['avito', 'delivery'], role='courier', status=['in_delivery'], username=call.from_user.username)
    state.set(CourierStates.accepted)
    if orders:
        for order in orders:
            order_message = format_order_message_for_courier(order)
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton(
                "Завершить заказ",
                callback_data=f"upload_invoice_{order['id']}_{order['message_id']}_{order['order_type'] if order['order_type'] else None}_{order['message_id'] if order['message_id'] else None }"
            ))

            if order['order_type'] == 'avito' and order.get('avito_photo'):
                # Если это Avito заказ и фото доступно
                with open(order['avito_photo'], 'rb') as photo:
                    bot.send_photo(
                        call.message.chat.id,
                        photo,
                        caption=order_message,
                        reply_markup=markup
                    )
            else:
                # Для доставки или отсутствующего фото Avito
                bot.send_message(
                    call.message.chat.id,
                    order_message,
                    reply_markup=markup
                )
    else:
        bot.send_message(call.message.chat.id, "У вас нет заказов в доставке.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('upload_invoice_'))
def upload_invoice(call: types.CallbackQuery, state: StateContext):
    print(call.data)
    order_type=call.data.split('_')[4]
    reply_message_id=call.data.split('_')[5]
    order_id = call.data.split('_')[2]
    state.add_data(message_to_edit=call.message.message_id)
    if order_type=='delivery':
        complete_order(order_id, reply_message_id, call.message.message_id, call.message, None, call.message.chat.username)
        return
    bot.send_message(call.message.chat.id, "Пожалуйста, загрузите фото накладной.")
    # Устанавливаем состояние ожидания фото
    state.set(AvitoStates.invoice_photo)
    state.add_data(order_id=order_id)

# Принятие заказа курьером
@bot.callback_query_handler(func=lambda call: call.data.startswith('accept_order_'))
def accept_order(call: types.CallbackQuery, state: StateContext):
    has_avito_photo = call.data.split('_')[4]
    order_id = call.data.split('_')[2]
    decrement_stock(order_id=order_id)
    reply_message_id = call.data.split('_')[3]
    user_info = get_user_info(call.from_user.username)
    state.add_data(reply_message_id=reply_message_id)
    print(has_avito_photo)
    if not user_info:
        bot.answer_callback_query(call.id, "Не удалось получить информацию о курьере.")
        return

    courier_id = user_info['id']
    courier_name = user_info['name']
    courier_username = user_info['username']
    # Привязываем заказ к курьеру и обновляем статус
    update_order_courier(order_id, courier_id)
    update_order_status(order_id, 'in_delivery')

    # Меняем текст сообщения о принятии заказа
    acceptance_message = (
        f"Заказ \#{str(order_id).zfill(4)}ㅤ принят *в доставку*\n\n"
        f"Вы сможете найти данный заказ по кнопке *Заказы* \-\> *Мои заказы в доставке*"
    )

    # Изменяем сообщение о принятии заказа в зависимости от наличия фото
    if has_avito_photo != 'False':
        bot.edit_message_caption(acceptance_message, chat_id=call.message.chat.id,
                                 message_id=call.message.message_id, parse_mode='MarkdownV2')
    else:
        bot.edit_message_text(acceptance_message, chat_id=call.message.chat.id,
                              message_id=call.message.message_id, parse_mode='MarkdownV2')

    # Отправляем сообщение в основной канал с информацией о курьере
    reply_params = ReplyParameters(message_id=int(reply_message_id))

    bot.send_message(CHANNEL_CHAT_ID,
                     f"Заказ \#{str(order_id).zfill(4)}ㅤ принят *в доставку*\n\nКурьер\: {courier_name} \({courier_username}\)",
                     reply_parameters=reply_params, parse_mode='MarkdownV2')


    bot.answer_callback_query(call.id)


# Завершение заказа курьером
def complete_order(order_id, reply_message_id, message_to_edit_id, message, invoice_photo,username):
    print(message)
    user_info = get_user_info(username)
    print(user_info)
    if not user_info:
        # bot.answer_callback_query(message.id, "Не удалось получить информацию о курьере.")
        return

    courier_name = user_info['name']
    courier_username = user_info['username']

    # Обновляем статус заказа на завершенный
    update_order_status(order_id, OrderType.CLOSED.value)

    # Отправляем сообщение о завершении заказа пользователю
    print(message.chat.id)
    print('message.chat.id')
    print('reply_message_id')
    print(reply_message_id)
    bot.delete_message(chat_id=message.chat.id, message_id=message_to_edit_id)
    bot.send_message(
        message.chat.id,
        f"Заказ \#{str(order_id).zfill(4)}ㅤ *завершен*",
        parse_mode='MarkdownV2'
    )

    reply_params = ReplyParameters(message_id=int(reply_message_id))
    # Отправляем сообщение в основной канал с информацией о курьере
    if invoice_photo:
        with open(invoice_photo, 'rb') as photo:
            bot.send_photo(
                CHANNEL_CHAT_ID,
                photo,
                caption=f"Заказ \#{str(order_id).zfill(4)}ㅤ *завершен*\n\nКурьер\: {courier_name} \({courier_username}\)",
                reply_parameters=reply_params,
                parse_mode='MarkdownV2'
            )
    else:
        bot.send_message(
            CHANNEL_CHAT_ID,
            f"Заказ \#{str(order_id).zfill(4)}ㅤ *завершен*\n\nКурьер\: {courier_name} \({courier_username}\)",
            reply_parameters=reply_params,
            parse_mode='MarkdownV2'
        )
    # bot.answer_callback_query(call.id)


# Начало работы с заказами (выбор типа заказа)
@bot.callback_query_handler(func=lambda call: call.data.startswith('orders_delivery'), state=AppStates.picked_action)
def handle_orders(call: CallbackQuery, state: StateContext):
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("Активные заказы", callback_data='orders_show_active'),
        types.InlineKeyboardButton("Мои заказы (в доставке)", callback_data='orders_show_in_delivery')
    )
    state.set(CourierStates.orders)
    bot.send_message(call.message.chat.id, "Выберите тип заказов:", reply_markup=markup)

# Обработчик доставленных товаров
@bot.callback_query_handler(func=lambda call: call.data == 'orders_delivered', state=AppStates.picked_action)
def show_delivered_orders(call: types.CallbackQuery, state: StateContext):
    with state.data() as data:
        start_date = data['start_date']
        end_date = data['end_date']

    user_info = get_user_by_username(call.from_user.username, state)

    # Получаем заказы, где courier_id совпадает с текущим пользователем и статус "closed" или "refund"
    orders = get_orders(username=call.from_user.username, status=['closed', 'refund'], start_date=start_date, end_date=end_date, courier=True)

    if not orders:
        bot.send_message(call.message.chat.id, "Нет доставленных товаров за выбранный период.")
        return

    # Отправляем каждое сообщение через format_order_message
    for order in orders:
        order_message = format_order_message(
            order['id'], order['product_id'], order['product_param_id'], order['gift'],
            order['note'], order['order_type'], user_info['name'], user_info['username']
        )
        bot.send_message(call.message.chat.id, order_message)
