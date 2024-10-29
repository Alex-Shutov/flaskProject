from telebot import types
from telebot.types import CallbackQuery, ReplyParameters, Message
from telebot.states.sync.context import StateContext
from bot import bot
from config import CHANNEL_CHAT_ID
from database import (
    get_couriers,
    update_order_status,
    get_user_info,
    update_order_courier,
    update_order_invoice_photo,
    get_orders,
    get_order_by_id,
    decrement_stock
)
from app_types import OrderType, UserRole
from utils import format_order_message, create_media_group, extract_order_number
from middlewares.delivery_zones import (
    DeliveryZoneManager,
    DeliveryCostCalculator,
    CourierTripManager
)
from states import AppStates, CourierStates


def notify_couriers(order_message, avito_photos=None, reply_message_id=None, state: StateContext = None):
    """Уведомляет всех курьеров о новом заказе"""
    try:
        # Получаем список всех курьеров
        couriers = get_couriers()

        for courier in couriers:
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton(
                    "📦 Принять заказ",
                    callback_data=f"accept_order_{extract_order_number(order_message)}_{reply_message_id}"
                )
            )

            # Если есть фото (для Авито), отправляем их
            if avito_photos:
                media_group = create_media_group(avito_photos, order_message)
                bot.send_media_group(courier['telegram_id'], media=media_group)
                bot.send_message(
                    courier['telegram_id'],
                    "Если вы готовы принять заказ, нажмите кнопку ниже:",
                    reply_markup=markup
                )
            else:
                # Если фото нет, просто отправляем сообщение с кнопкой
                bot.send_message(
                    courier['telegram_id'],
                    f"{order_message}\n\nЕсли вы готовы принять заказ, нажмите кнопку ниже:",
                    reply_markup=markup
                )

    except Exception as e:
        print(f"Error in notify_couriers: {e}")

@bot.callback_query_handler(func=lambda call: call.data == 'orders_delivery', state=AppStates.picked_action)
def handle_orders_delivery(call: CallbackQuery, state: StateContext):
    """Обработчик нажатия кнопки 'Доставка товара'"""
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("📋 Активные заказы", callback_data='orders_show_active'),
        types.InlineKeyboardButton("🚚 Мои заказы в доставке", callback_data='orders_show_in_delivery')
    )
    bot.edit_message_text(
        "Выберите тип заказов:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )
    state.set(CourierStates.orders)


@bot.message_handler(func=lambda message: message.text == '#Доставка')
def show_courier_menu(message: Message):
    """Показывает главное меню курьера"""
    try:
        user_info = get_user_info(message.from_user.username)
        if not user_info or UserRole.COURIER.value not in user_info['roles']:
            bot.reply_to(message, "У вас нет доступа к функциям курьера.")
            return

        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🚗 Создать поездку", callback_data="create_trip"),
            types.InlineKeyboardButton("📋 Активные заказы", callback_data="show_active_orders"),
            types.InlineKeyboardButton("🚚 Мои поездки", callback_data="show_my_trips"),
            types.InlineKeyboardButton("📊 Статистика доставок", callback_data="delivery_stats")
        )

        bot.reply_to(
            message,
            "🚚 Меню курьера\nВыберите действие:",
            reply_markup=markup
        )

    except Exception as e:
        bot.reply_to(message, "Произошла ошибка при загрузке меню курьера.")
        print(f"Error in show_courier_menu: {e}")


@bot.callback_query_handler(func=lambda call: call.data == "show_active_orders")
def show_active_orders(call: CallbackQuery):
    """Показывает все активные заказы, доступные для доставки"""
    try:
        orders = get_orders(
            order_type=['avito', 'delivery'],
            status=[OrderType.READY_TO_DELIVERY.value],
            is_courier_null=True
        )

        if not orders:
            bot.answer_callback_query(call.id, "Нет активных заказов")
            bot.edit_message_text(
                "На данный момент нет активных заказов для доставки.",
                call.message.chat.id,
                call.message.message_id
            )
            return

        # Создаем сообщение со списком заказов
        message_text = "📦 Доступные заказы:\n\n"
        markup = types.InlineKeyboardMarkup(row_width=1)

        for order in orders:
            # Форматируем информацию о заказе
            order_info = format_order_message(
                order_id=order['id'],
                product_list=order['products'].get('general', []),
                gift=order['gift'],
                note=order['note'],
                sale_type=order['order_type'],
                delivery_date=order.get('delivery_date'),
                delivery_time=order.get('delivery_time'),
                delivery_address=order.get('delivery_address'),
                contact_phone=order.get('contact_phone'),
                contact_name=order.get('contact_name'),
                hide_track_prices=True
            )
            message_text += f"{order_info}\n{'—' * 30}\n"

            # Добавляем кнопку для каждого заказа
            markup.add(
                types.InlineKeyboardButton(
                    f"📦 Принять заказ #{order['id']}",
                    callback_data=f"accept_order_{order['id']}_{order['message_id']}"
                )
            )

        # Добавляем кнопку возврата в меню
        markup.add(
            types.InlineKeyboardButton("🔙 Вернуться в меню", callback_data="back_to_courier_menu")
        )

        bot.edit_message_text(
            message_text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

    except Exception as e:
        bot.answer_callback_query(call.id, "Произошла ошибка при загрузке заказов")
        print(f"Error in show_active_orders: {e}")


@bot.callback_query_handler(func=lambda call: call.data == "show_my_trips")
def show_courier_trips(call: CallbackQuery):
    """Показывает активные поездки курьера"""
    try:
        user_info = get_user_info(call.from_user.username)
        if not user_info:
            bot.answer_callback_query(call.id, "Ошибка получения информации о пользователе")
            return

        # Получаем заказы курьера в доставке
        orders = get_orders(
            username=call.from_user.username,
            status=['in_delivery'],
            role='courier'
        )

        if not orders:
            bot.answer_callback_query(call.id)
            bot.edit_message_text(
                "У вас нет активных поездок.",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton("🔙 Вернуться в меню", callback_data="back_to_courier_menu")
                )
            )
            return

        message_text = "🚚 Ваши активные поездки:\n\n"
        markup = types.InlineKeyboardMarkup(row_width=1)

        for order in orders:
            order_text = format_order_message(
                order_id=order['id'],
                product_list=order['products'].get('general', []),
                gift=order['gift'],
                note=order['note'],
                sale_type=order['order_type'],
                delivery_date=order.get('delivery_date'),
                delivery_time=order.get('delivery_time'),
                delivery_address=order.get('delivery_address'),
                contact_phone=order.get('contact_phone'),
                contact_name=order.get('contact_name'),
                hide_track_prices=True
            )
            message_text += f"{order_text}\n{'—' * 30}\n"

            markup.add(
                types.InlineKeyboardButton(
                    f"✅ Завершить доставку #{order['id']}",
                    callback_data=f"complete_delivery_{order['id']}_{order['message_id']}"
                )
            )

        markup.add(
            types.InlineKeyboardButton("🔙 Вернуться в меню", callback_data="back_to_courier_menu")
        )

        bot.edit_message_text(
            message_text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

    except Exception as e:
        bot.answer_callback_query(call.id, "Произошла ошибка при загрузке поездок")
        print(f"Error in show_courier_trips: {e}")


@bot.callback_query_handler(func=lambda call: call.data.startswith('accept_order_'))
def accept_order(call: CallbackQuery, state: StateContext):
    """Принятие заказа курьером"""
    try:
        order_id = call.data.split('_')[2]
        reply_message_id = call.data.split('_')[3]

        user_info = get_user_info(call.from_user.username)
        if not user_info:
            bot.answer_callback_query(call.id, "Не удалось получить информацию о курьере.")
            return

        # Снижаем количество товара на складе
        decrement_stock(order_id=order_id)

        # Привязываем заказ к курьеру и обновляем статус
        update_order_courier(order_id, user_info['id'])
        update_order_status(order_id, OrderType.IN_DELIVERY.value)

        # Отправляем сообщение курьеру
        bot.edit_message_text(
            f"✅ Вы приняли заказ #{order_id}\n\n"
            f"Теперь этот заказ доступен в разделе 'Мои поездки'",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("🚚 Мои поездки", callback_data="show_my_trips")
            )
        )

        # Отправляем сообщение в основной канал
        reply_params = ReplyParameters(message_id=int(reply_message_id))
        bot.send_message(
            CHANNEL_CHAT_ID,
            f"🚚 Заказ #{order_id} принят в доставку\n"
            f"Курьер: {user_info['name']} (@{user_info['username']})",
            reply_parameters=reply_params
        )

    except Exception as e:
        bot.answer_callback_query(call.id, "Произошла ошибка при принятии заказа")
        print(f"Error in accept_order: {e}")


@bot.callback_query_handler(func=lambda call: call.data == "delivery_stats")
def show_delivery_stats(call: CallbackQuery):
    """Показывает статистику доставок курьера"""
    try:
        user_info = get_user_info(call.from_user.username)
        if not user_info:
            bot.answer_callback_query(call.id, "Ошибка получения информации о пользователе")
            return

        # Получаем завершенные заказы курьера
        completed_orders = get_orders(
            username=call.from_user.username,
            status=['closed'],
            role='courier'
        )

        # Подсчитываем статистику
        total_deliveries = len(completed_orders)
        total_items = sum(
            len(order['products'].get('general', []))
            for order in completed_orders
        )

        # Формируем сообщение со статистикой
        stats_message = (
            "📊 Ваша статистика доставок:\n\n"
            f"📦 Всего доставлено заказов: {total_deliveries}\n"
            f"🎁 Всего доставлено товаров: {total_items}\n"
        )

        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🔙 Вернуться в меню", callback_data="back_to_courier_menu")
        )

        bot.edit_message_text(
            stats_message,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

    except Exception as e:
        bot.answer_callback_query(call.id, "Произошла ошибка при загрузке статистики")
        print(f"Error in show_delivery_stats: {e}")


@bot.callback_query_handler(func=lambda call: call.data == "back_to_courier_menu")
def back_to_menu(call: CallbackQuery):
    """Возврат в главное меню курьера"""
    try:
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🚗 Создать поездку", callback_data="create_trip"),
            types.InlineKeyboardButton("📋 Активные заказы", callback_data="show_active_orders"),
            types.InlineKeyboardButton("🚚 Мои поездки", callback_data="show_my_trips"),
            types.InlineKeyboardButton("📊 Статистика доставок", callback_data="delivery_stats")
        )

        bot.edit_message_text(
            "🚚 Меню курьера\nВыберите действие:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

    except Exception as e:
        bot.answer_callback_query(call.id, "Произошла ошибка при возврате в меню")
        print(f"Error in back_to_menu: {e}")