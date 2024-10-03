from telebot import types
from bot import get_bot_instance
from database import get_couriers, update_order_status,get_user_info,update_order_courier
from telebot.types import CallbackQuery
from utils import format_order_message_for_courier,save_photo_and_resize,extract_order_number
from telebot.states.sync.context import StateContext
from states import AvitoStates, CourierStates
from config import CHANNEL_CHAT_ID
from app_types import OrderType
from database import get_orders


bot = get_bot_instance()

# Уведомление курьеров
@bot.message_handler(state=AvitoStates.avito_message, func=lambda message: True)
def notify_couriers(message, state: StateContext):
    couriers = get_couriers()  # Получаем список пользователей с ролью Courier
    with state.data() as state_data:
        avito_photo = state_data.get('avito_photo')
        order_message = state_data.get('avito_message')
        state.set(CourierStates.accepted)
        for courier in couriers:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("Принять заказ", callback_data=f"accept_order_{courier['telegram_id']}"))

            bot.send_photo(courier['telegram_id'], open(avito_photo, 'rb'), caption=order_message, reply_markup=markup)




# Обработка завершения заказа (загрузка накладной)
@bot.message_handler(state=AvitoStates.invoice_photo, content_types=['photo'])
def handle_invoice_photo(message: types.Message, state: StateContext):
    chat_id = message.chat.id
    if message.photo:
        photo = message.photo[-1]
        file_info = bot.get_file(photo.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        invoice_path = save_photo_and_resize(downloaded_file, f"invoice_{chat_id}")

        # Сохраняем путь к накладной
        state.add_data(invoice_photo=invoice_path)

        # Завершаем заказ и изменяем статус на завершен
        order_id = state.data().get('order_id')  # Предположим, что order_id хранится в состоянии
        update_order_status(order_id, "Завершен")

        bot.send_message(chat_id, "Заказ успешно завершен.")
        state.delete()
    else:
        bot.send_message(chat_id, "Пожалуйста, загрузите фото накладной.")


# Функция для показа активных заказов
@bot.callback_query_handler(func=lambda call: call.data == 'orders_show_active', state=CourierStates.orders)
def show_active_orders(call: types.CallbackQuery, state: StateContext):
    # Получаем все активные заказы с типом 'avito' или 'delivery' и courier_id == null
    orders = get_orders(order_type=['avito', 'delivery'], status=['active'], is_courier_null=True)
    if orders:
        for order in orders:
            order_message = format_order_message_for_courier(order)
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("Принять заказ", callback_data=f"accept_order_{order['id']}"))
            bot.send_photo(call.message.chat.id, open(order['avito_photo'], 'rb'), caption=order_message,
                           reply_markup=markup)
    else:
        bot.send_message(call.message.chat.id, "Нет активных заказов")

    bot.answer_callback_query(call.id)


# Функция для показа заказов курьера в доставке
@bot.callback_query_handler(func=lambda call: call.data == 'orders_show_in_delivery', state=CourierStates.orders)
def show_courier_orders_in_delivery(call: types.CallbackQuery, state: StateContext):
    user_info = get_user_info(call.from_user.username)  # Получаем информацию о курьере
    if not user_info:
        bot.answer_callback_query(call.id, "Не удалось получить информацию о пользователе.")
        return

    courier_id = user_info['id']

    # Получаем заказы с типом 'in_delivery', где courier_id == id курьера
    orders = get_orders(order_type=['avito', 'delivery'], status=['in_delivery'], username=call.from_user.username)
    if orders:
        for order in orders:
            order_message = format_order_message_for_courier(order)
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("Завершить заказ", callback_data=f"complete_order_{order['id']}"))
            bot.send_photo(call.message.chat.id, open(order['avito_photo'], 'rb'), caption=order_message,
                           reply_markup=markup)
    else:
        bot.send_message(call.message.chat.id, "У вас нет заказов в доставке.")

    bot.answer_callback_query(call.id)


# Принятие заказа курьером
@bot.callback_query_handler(func=lambda call: call.data.startswith('accept_order_'), state=CourierStates.orders)
def accept_order(call: types.CallbackQuery, state: StateContext):
    order_id = call.data.split('_')[2]
    user_info = get_user_info(call.from_user.username)

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
    bot.edit_message_caption(f"Заказ #{order_id} принят в доставку", chat_id=call.message.chat.id,
                             message_id=call.message.message_id)
    bot.send_message(call.message.chat.id, "Теперь загрузите фото накладной после завершения заказа.")

    # Отправляем сообщение в основной канал с информацией о курьере
    bot.send_message(CHANNEL_CHAT_ID,
                     f"Заказ #{order_id} принят в доставку\nВыполнит курьер: {courier_name} (@{courier_username})",
                     reply_to_message_id=call.message.message_id)

    bot.answer_callback_query(call.id)


# Завершение заказа курьером
@bot.callback_query_handler(func=lambda call: call.data.startswith('complete_order_'), state=CourierStates.orders)
def complete_order(call: types.CallbackQuery, state: StateContext):
    order_id = call.data.split('_')[2]
    user_info = get_user_info(call.from_user.username)

    if not user_info:
        bot.answer_callback_query(call.id, "Не удалось получить информацию о курьере.")
        return

    courier_name = user_info['name']
    courier_username = user_info['username']

    # Обновляем статус заказа на завершенный
    update_order_status(order_id, 'completed')

    # Меняем текст сообщения о завершении заказа
    bot.edit_message_caption(f"Заказ #{order_id} был завершен", chat_id=call.message.chat.id,
                             message_id=call.message.message_id)

    # Отправляем сообщение в основной канал с информацией о курьере
    bot.send_message(CHANNEL_CHAT_ID,
                     f"Заказ #{order_id} был завершен\nВыполнен курьером: {courier_name} (@{courier_username})",
                     reply_to_message_id=call.message.message_id)

    bot.answer_callback_query(call.id)


# Начало работы с заказами (выбор типа заказа)
@bot.message_handler(func=lambda message: message.text == '#Заказы', state=None)
def handle_orders(message: types.Message, state: StateContext):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("Показать активные заказы", callback_data='orders_show_active'),
        types.InlineKeyboardButton("Показать мои заказы в доставке", callback_data='orders_show_in_delivery')
    )
    state.set(CourierStates.orders)
    bot.send_message(message.chat.id, "Выберите тип заказов:", reply_markup=markup)
