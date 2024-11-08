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

from database import get_avito_photos

from database import get_delivery_zone_for_order

from database import get_courier_trips
from utils import validate_date_range

from app_types import TripStatusRu, OrderTypeRu


def notify_couriers(order_message, state: StateContext,avito_photos=None, reply_message_id=None,):
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
            types.InlineKeyboardButton("🚚 Текущая поездка", callback_data="show_current_trip"),
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
def show_active_orders(call: CallbackQuery, state: StateContext):
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

        # Отправляем заголовок
        bot.edit_message_text(
            "📦 Доступные заказы:",
            call.message.chat.id,
            call.message.message_id
        )

        # Отправляем каждый заказ отдельным сообщением
        for order in orders:
            try:
                # Создаем клавиатуру для заказа
                markup = types.InlineKeyboardMarkup(row_width=1)
                button_text = (
                    f"📦 Принять заказ #{order['id']}"
                    if order['order_type'] == 'delivery'
                    else f"📦 Принять заказ #{order['id']} (Авито)"
                )
                markup.add(
                    types.InlineKeyboardButton(
                        button_text,
                        callback_data=f"accept_order_{order['id']}_{order['message_id']}"
                    )
                )

                # Получаем зону доставки для заказа с доставкой
                delivery_zone = None
                if order['order_type'] == 'delivery':
                    # Здесь нужно добавить функцию получения зоны доставки
                    delivery_zone = get_delivery_zone_for_order(order['id'])

                # Подготавливаем список товаров
                products_for_message = []
                if order['order_type'] == 'avito':
                    # Для Авито оставляем исходную структуру
                    products_for_message = order['products']
                else:
                    # Для доставки преобразуем структуру no_track
                    no_track_products = order['products'].get('no_track', {}).get('products', [])
                    for product in no_track_products:
                        products_for_message.append({
                            'product_name': product['name'],
                            'param_title': product['param'],
                            'is_main_product': product.get('is_main_product', False)
                        })
                print(delivery_zone,'123')
                # Форматируем сообщение о заказе
                order_info = format_order_message(
                    order_id=order['id'],
                    product_list=products_for_message,
                    gift=order['gift'],
                    note=order['note'],
                    sale_type=order['order_type'],
                    manager_name=order.get('manager_name', 'Не указан'),
                    manager_username=order.get('manager_username', 'Не указан'),
                    delivery_date=order.get('delivery_date'),
                    delivery_time=order.get('delivery_time'),
                    delivery_address=order.get('delivery_address'),
                    contact_phone=order.get('contact_phone'),
                    contact_name=order.get('contact_name'),
                    zone_name=delivery_zone.get('name') if delivery_zone else None,
                    total_price=order.get('total_price'),
                    avito_boxes=order.get('avito_boxes'),
                    hide_track_prices=True,
                    show_item_status=True
                )

                if order['order_type'] == 'avito':
                    # Получаем и отправляем фотографии для заказов Авито
                    photos = get_avito_photos(order['id'])
                    if photos:
                        try:
                            media = create_media_group(photos, order_info)
                            bot.send_media_group(call.message.chat.id, media)
                            bot.send_message(
                                call.message.chat.id,
                                "Если вы хотите принять этот заказ, нажмите на кнопку ниже:",
                                reply_markup=markup
                            )
                        except Exception as photo_error:
                            print(f"Error sending photos for order {order['id']}: {str(photo_error)}")
                            bot.send_message(
                                call.message.chat.id,
                                order_info,
                                reply_markup=markup
                            )
                else:
                    bot.send_message(
                        call.message.chat.id,
                        order_info,
                        reply_markup=markup
                    )

            except Exception as order_error:
                print(f"Error processing order {order['id']}: {str(order_error)}")
                continue

        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("🔙 Вернуться в меню", callback_data="back_to_courier_menu")
        )
        bot.send_message(
            call.message.chat.id,
            "Выберите заказ или вернитесь в меню:",
            reply_markup=markup
        )

    except Exception as e:
        error_message = f"Error in show_active_orders: {str(e)}"
        print(error_message)
        try:
            bot.answer_callback_query(call.id, "Произошла ошибка при загрузке заказов")
            bot.send_message(
                call.message.chat.id,
                "Не удалось загрузить список заказов. Пожалуйста, попробуйте позже."
            )
        except:
            print("Failed to send error message to user")

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
        # decrement_stock(order_id=order_id)

        # Привязываем заказ к курьеру и обновляем статус
        update_order_courier(order_id, user_info['id'])
        update_order_status(order_id, OrderType.READY_TO_DELIVERY.value)

        # Отправляем сообщение курьеру
        bot.edit_message_text(
            f"✅ Вы приняли заказ #{order_id}\n\n"
            f"Теперь вы можете добавить его в поездку",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("🚚 Создать поездку", callback_data="create_trip")
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
    """Запрашивает период для просмотра статистики доставок"""
    bot.edit_message_text(
        "Введите диапазон дат для просмотра статистики доставок в формате:\n"
        "день.месяц.год-день.месяц.год\n"
        "Например: 01.01.2024-31.01.2024",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id
    )
    bot.register_next_step_handler(call.message, process_delivery_stats_dates)


def process_delivery_stats_dates(message: types.Message):
    dates = validate_date_range(message.text)
    if not dates:
        bot.reply_to(message, "Неверный формат дат. Пожалуйста, попробуйте снова.")
        return

    start_date, end_date = dates
    trips = get_courier_trips(
        courier_username=message.from_user.username,
        start_date=start_date.strftime("%Y-%m-%d"),
        end_date=end_date.strftime("%Y-%m-%d")
    )

    if not trips:
        bot.reply_to(message, "За указанный период поездок не найдено.")
        return

    # Обрабатываем каждую поездку отдельно
    for trip in trips:
        if trip['status'] != 'completed':
            continue

        trip_message = [
            f"🚚 Поездка #{str(trip['id']).zfill(4)}",
            f"📅 Дата: {trip['created_at'].strftime('%d.%m.%Y')}",
            f"📊 Статус: {TripStatusRu[trip['status'].upper()].value}\n"
        ]

        # Группируем товары по заказам
        orders = {}
        for item in trip['items']:
            order_id = item['order_id']
            if order_id not in orders:
                orders[order_id] = {
                    'type': item['order_type'],
                    'address': item['delivery_address'],
                    'delivered_items': [],
                    'returned_items': [],
                    'pending_items': [],
                    'tracking_numbers': set()
                }

            # Для Авито добавляем трек-номер
            if item['order_type'] == 'avito' and item['product'].get('tracking_number'):
                orders[order_id]['tracking_numbers'].add(item['product']['tracking_number'])

            # Добавляем товар в соответствующий список с учетом статуса позиции
            try:
                status_text = OrderTypeRu[item['item_status'].upper()].value
            except KeyError:
                status_text = item['item_status']

            product_info = f"- {item['product']['name']} {item['product']['param_title']} ({status_text})"

            if item['item_status'] == 'closed':
                orders[order_id]['delivered_items'].append(product_info)
            elif item['item_status'] == 'refund':
                orders[order_id]['returned_items'].append(product_info)
            else:
                orders[order_id]['pending_items'].append(product_info)

        # Выводим доставленные товары
        delivered_orders = [order for order in orders.items() if order[1]['delivered_items']]
        if delivered_orders:
            trip_message.append("✅ Доставлено:")
            for order_id, order_info in delivered_orders:
                trip_message.append(f"\n📦 Заказ #{str(order_id).zfill(4)}")
                if order_info['type'] == 'avito':
                    trip_message.append("📍 Авито")
                    for track in sorted(order_info['tracking_numbers']):
                        trip_message.append(f"📝 Трек-номер: {track}")
                else:
                    trip_message.append(f"📍 {order_info['address'] or 'Адрес не указан'}")
                trip_message.extend(order_info['delivered_items'])

        # Выводим возвращенные товары
        returned_orders = [order for order in orders.items() if order[1]['returned_items']]
        if returned_orders:
            trip_message.append("\n❌ Возвращено:")
            for order_id, order_info in returned_orders:
                trip_message.append(f"\n📦 Заказ #{str(order_id).zfill(4)}")
                if order_info['type'] == 'avito':
                    trip_message.append("📍 Авито")
                    for track in sorted(order_info['tracking_numbers']):
                        trip_message.append(f"📝 Трек-номер: {track}")
                else:
                    trip_message.append(f"📍 {order_info['address'] or 'Адрес не указан'}")
                trip_message.extend(order_info['returned_items'])

        # Выводим ожидающие товары
        pending_orders = [order for order in orders.items() if order[1]['pending_items']]
        if pending_orders:
            trip_message.append("\n⏳ В ожидании:")
            for order_id, order_info in pending_orders:
                trip_message.append(f"\n📦 Заказ #{str(order_id).zfill(4)}")
                if order_info['type'] == 'avito':
                    trip_message.append("📍 Авито")
                    for track in sorted(order_info['tracking_numbers']):
                        trip_message.append(f"📝 Трек-номер: {track}")
                else:
                    trip_message.append(f"📍 {order_info['address'] or 'Адрес не указан'}")
                trip_message.extend(order_info['pending_items'])

        # Отправляем сообщение для поездки
        bot.send_message(message.chat.id, '\n'.join(trip_message))

@bot.callback_query_handler(func=lambda call: call.data == "back_to_courier_menu")
def back_to_menu(call: CallbackQuery):
    """Возврат в главное меню курьера"""
    try:
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🚗 Создать поездку", callback_data="create_trip"),
            types.InlineKeyboardButton("📋 Активные заказы", callback_data="show_active_orders"),
            types.InlineKeyboardButton("🚚 Текущая поездка", callback_data="show_current_trip"),
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