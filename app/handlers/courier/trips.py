from telebot.handler_backends import State, StatesGroup
from telebot import types
from telebot.types import Message, CallbackQuery
from telebot.states.sync.context import StateContext
from datetime import datetime

from middlewares.delivery_zones import CourierTripManager, DeliveryZoneManager, DeliveryCostCalculator
from bot import bot
from config import CHANNEL_CHAT_ID, YANDEX_API_KEY, DATABASE_CONFIG
from database import (
    get_orders,
    get_user_info,
    update_order_status,
    get_avito_photos,
    update_order_message_id,
)
from utils import format_order_message
from app_types import OrderType
import psycopg2

# Инициализация соединения с БД
connection = psycopg2.connect(**DATABASE_CONFIG)
connection.set_session(autocommit=True)

# Инициализация менеджеров
trip_manager = CourierTripManager(connection)
zone_manager = DeliveryZoneManager(connection, YANDEX_API_KEY)
cost_calculator = DeliveryCostCalculator(connection)


class TripStates(StatesGroup):
    """Состояния для создания поездки"""
    selecting_orders = State()  # Выбор заказов
    confirm_orders = State()  # Подтверждение выбранных заказов
    trip_in_progress = State()  # Поездка выполняется
    completing_delivery = State()  # Завершение доставки
    canceling_items = State()  # Отмена товаров


def get_orders_keyboard(orders: list) -> types.InlineKeyboardMarkup:
    """Создает клавиатуру для выбора заказов"""
    markup = types.InlineKeyboardMarkup(row_width=1)
    for order in orders:
        # Формируем текст кнопки
        button_text = f"Заказ #{order['id']} - {order['delivery_address']}"
        callback_data = f"select_order_{order['id']}"
        markup.add(types.InlineKeyboardButton(button_text, callback_data=callback_data))

    markup.add(types.InlineKeyboardButton("✅ Подтвердить выбор", callback_data="confirm_orders"))
    return markup


@bot.callback_query_handler(func=lambda call: call.data == 'create_trip')
def start_trip_creation(call: CallbackQuery, state: StateContext):
    """Начало создания поездки"""
    message = call.message
    print(123)
    try:
        # Получаем информацию о курьере
        courier_info = get_user_info(call.message.json['chat']['username'])
        if not courier_info:
            bot.reply_to(message, "Не удалось получить информацию о курьере.")
            return

        # Получаем активные заказы, готовые к доставке
        available_orders = get_orders(
            order_type=['avito', 'delivery'],
            status=[OrderType.READY_TO_DELIVERY.value],
            is_courier_null=True
        )

        if not available_orders:
            bot.reply_to(message, "Нет доступных заказов для доставки.")
            return

        # Создаем клавиатуру для выбора заказов
        markup = get_orders_keyboard(available_orders)

        bot.reply_to(
            message,
            "Выберите заказы для добавления в поездку:",
            reply_markup=markup
        )

        # Устанавливаем состояние выбора заказов
        state.set(TripStates.selecting_orders)
        state.add_data(selected_orders=[])

    except Exception as e:
        bot.reply_to(message, "Произошла ошибка при создании поездки.")
        print(f"Error in start_trip_creation: {e}")


def build_menu(buttons, n_cols=1, header_buttons=None, footer_buttons=None):
    """Строит меню кнопок с указанным количеством колонок"""
    menu = [buttons[i:i + n_cols] for i in range(0, len(buttons), n_cols)]
    if header_buttons:
        menu.insert(0, header_buttons)
    if footer_buttons:
        menu.append(footer_buttons)
    return menu


def get_orders_keyboard(orders: list, selected_items: dict = None) -> types.InlineKeyboardMarkup:
    """
    Создает клавиатуру для выбора заказов

    Args:
        orders: список заказов
        selected_items: словарь выбранных товаров {order_id: [item_id1, item_id2, ...]}
    """
    button_list = []

    for order in orders:
        # Проверяем, есть ли выбранные товары в этом заказе
        has_selected_items = (selected_items and
                              order['id'] in selected_items and
                              len(selected_items[order['id']]) > 0)

        # Добавляем индикатор выбранных товаров
        prefix = "📦" if not has_selected_items else "✅"

        button_text = (
            f"{prefix} Заказ #{order['id']} - "
            f"{order.get('delivery_address', 'Адрес не указан')} "
            f"({len(order['products'].get('general', []))} товаров)"
        )

        button_list.append(
            types.InlineKeyboardButton(
                button_text,
                callback_data=f"show_order_items_{order['id']}"
            )
        )

    # Добавляем кнопку подтверждения только если есть выбранные товары
    footer_buttons = None
    if selected_items and any(selected_items.values()):
        footer_buttons = [
            types.InlineKeyboardButton("✅ Подтвердить выбор", callback_data="confirm_orders")
        ]

    return types.InlineKeyboardMarkup(
        build_menu(button_list, n_cols=1, footer_buttons=footer_buttons)
    )


def get_order_items_keyboard(order_id: int, items: list, selected_items: list = None) -> types.InlineKeyboardMarkup:
    """
    Создает клавиатуру для выбора товаров из заказа

    Args:
        order_id: ID заказа
        items: список товаров
        selected_items: список ID выбранных товаров
    """
    button_list = []
    selected_items = selected_items or []

    for item in items:
        # Определяем, выбран ли товар
        is_selected = item['id'] in selected_items
        prefix = "☑️" if is_selected else "⬜️"

        button_text = f"{prefix} {item['product_name']} - {item.get('param_title', '')}"
        callback_data = f"toggle_item_{order_id}_{item['id']}"

        button_list.append(
            types.InlineKeyboardButton(
                button_text,
                callback_data=callback_data
            )
        )

    # Добавляем кнопку "Назад"
    footer_buttons = [
        types.InlineKeyboardButton("🔙 Назад к заказам", callback_data="back_to_orders")
    ]

    return types.InlineKeyboardMarkup(
        build_menu(button_list, n_cols=1, footer_buttons=footer_buttons)
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('show_order_items_'),
                            state=TripStates.selecting_orders)
def show_order_items(call: CallbackQuery, state: StateContext):
    """Показывает товары в выбранном заказе"""
    try:
        order_id = int(call.data.split('_')[3])

        # Получаем информацию о заказе
        order = get_orders(order_id=order_id)[0]
        if not order:
            bot.answer_callback_query(call.id, "Заказ не найден")
            return

        # Получаем ранее выбранные товары из состояния
        with state.data() as data:
            selected_items = data.get('selected_items', {})
            current_order_selections = selected_items.get(order_id, [])

        # Создаем сообщение с информацией о заказе и товарах
        message_text = (
            f"📦 Заказ #{order['id']}\n"
            f"📍 Адрес: {order.get('delivery_address', 'Не указан')}\n"
            f"📱 Контакт: {order.get('contact_name', 'Не указан')} "
            f"({order.get('contact_phone', 'Не указан')})\n\n"
            f"Выберите товары для добавления в поездку:"
        )

        # Создаем клавиатуру с товарами
        markup = get_order_items_keyboard(
            order_id,
            order['products'].get('general', []),
            current_order_selections
        )

        # Обновляем сообщение
        bot.edit_message_text(
            message_text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

        # Сохраняем текущий заказ в состоянии
        state.add_data(current_order_id=order_id)

    except Exception as e:
        bot.answer_callback_query(call.id, "Ошибка при отображении товаров")
        print(f"Error in show_order_items: {e}")


@bot.callback_query_handler(func=lambda call: call.data.startswith('toggle_item_'), state=TripStates.selecting_orders)
def toggle_item_selection(call: CallbackQuery, state: StateContext):
    """Обработка выбора/отмены выбора товара"""
    try:
        _, order_id, item_id = call.data.split('_')[1:]
        order_id, item_id = int(order_id), int(item_id)

        with state.data() as data:
            selected_items = data.get('selected_items', {})
            if order_id not in selected_items:
                selected_items[order_id] = []

            # Переключаем выбор товара
            if item_id in selected_items[order_id]:
                selected_items[order_id].remove(item_id)
                action = "удален из"
            else:
                selected_items[order_id].append(item_id)
                action = "добавлен в"

            data['selected_items'] = selected_items

        # Получаем заказ и обновляем клавиатуру
        order = get_orders(order_id=order_id)[0]
        markup = get_order_items_keyboard(
            order_id,
            order['products'].get('general', []),
            selected_items[order_id]
        )

        bot.edit_message_reply_markup(
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

        bot.answer_callback_query(
            call.id,
            f"Товар {action} поездку"
        )

    except Exception as e:
        bot.answer_callback_query(call.id, "Ошибка при выборе товара")
        print(f"Error in toggle_item_selection: {e}")


@bot.callback_query_handler(func=lambda call: call.data == 'back_to_orders', state=TripStates.selecting_orders)
def back_to_orders_list(call: CallbackQuery, state: StateContext):
    """Возврат к списку заказов"""
    try:
        # Получаем все активные заказы
        orders = get_orders(
            order_type=['avito', 'delivery'],
            status=[OrderType.READY_TO_DELIVERY.value],
            is_courier_null=True
        )

        # Получаем выбранные товары из состояния
        with state.data() as data:
            selected_items = data.get('selected_items', {})

        # Создаем клавиатуру с учетом выбранных товаров
        markup = get_orders_keyboard(orders, selected_items)

        bot.edit_message_text(
            "Выберите заказы для добавления товаров в поездку:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

    except Exception as e:
        bot.answer_callback_query(call.id, "Ошибка при возврате к списку заказов")
        print(f"Error in back_to_orders_list: {e}")


@bot.callback_query_handler(func=lambda call: call.data == "confirm_orders", state=TripStates.selecting_orders)
def confirm_orders_selection(call: CallbackQuery, state: StateContext):
    """Подтверждение выбранных заказов"""
    try:
        with state.data() as data:
            selected_orders = data.get('selected_orders', [])

        if not selected_orders:
            bot.answer_callback_query(call.id, "Выберите хотя бы один заказ")
            return

        # Получаем информацию о курьере
        courier_info = get_user_info(call.from_user.username)
        if not courier_info:
            bot.answer_callback_query(call.id, "Ошибка получения информации о курьере")
            return

        # Определяем самую дальнюю зону из выбранных заказов
        orders_info = []
        furthest_zone_id = None
        furthest_zone_price = 0

        for order_id in selected_orders:
            order = get_orders(order_id=order_id)[0]
            orders_info.append(order)

            # Определяем зону доставки
            delivery_address = order['delivery_address']
            coordinates = zone_manager.geocode_address(delivery_address)
            if coordinates:
                zone = zone_manager.get_zone_by_coordinates(*coordinates)
                if zone and zone.base_price > furthest_zone_price:
                    furthest_zone_id = zone.id
                    furthest_zone_price = zone.base_price

        if not furthest_zone_id:
            bot.answer_callback_query(call.id, "Ошибка определения зоны доставки")
            return

        # Создаем поездку
        trip_id = trip_manager.create_trip(courier_info['id'], furthest_zone_id)
        if not trip_id:
            bot.answer_callback_query(call.id, "Ошибка создания поездки")
            return

        # Добавляем заказы в поездку
        success = trip_manager.add_items_to_trip(trip_id, selected_orders)
        if not success:
            bot.answer_callback_query(call.id, "Ошибка добавления заказов в поездку")
            return

        # Обновляем статусы заказов
        for order_id in selected_orders:
            update_order_status(order_id, OrderType.IN_DELIVERY.value)

        # Рассчитываем стоимость доставки
        delivery_cost = cost_calculator.calculate_for_trip(orders_info, furthest_zone_id)

        # Формируем сообщение о созданной поездке
        trip_message = (
            f"🚚 Создана новая поездка\n\n"
            f"Курьер: {courier_info['name']} (@{courier_info['username']})\n"
            f"Количество заказов: {len(selected_orders)}\n"
            f"Стоимость доставки: {delivery_cost.total_price} руб.\n\n"
            f"Заказы в поездке:\n"
        )

        for order in orders_info:
            trip_message += f"- Заказ #{order['id']}: {order['delivery_address']}\n"

        # Создаем клавиатуру для управления поездкой
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("✅ Завершить поездку", callback_data=f"complete_trip_{trip_id}"),
            types.InlineKeyboardButton("❌ Отменить поездку", callback_data=f"cancel_trip_{trip_id}")
        )

        # Отправляем сообщение о создании поездки
        bot.edit_message_text(
            trip_message,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

        # Обновляем состояние
        state.set(TripStates.trip_in_progress)
        state.add_data(
            trip_id=trip_id,
            orders_info=orders_info,
            delivery_cost=delivery_cost.__dict__
        )

    except Exception as e:
        bot.answer_callback_query(call.id, "Произошла ошибка при создании поездки")
        print(f"Error in confirm_orders_selection: {e}")


@bot.callback_query_handler(func=lambda call: call.data.startswith('complete_trip_'))
def handle_trip_completion(call: CallbackQuery, state: StateContext):
    """Обработка завершения поездки"""
    try:
        trip_id = int(call.data.split('_')[2])

        # Получаем информацию о товарах в поездке
        trip_items = trip_manager.get_trip_items(trip_id)

        # Создаем клавиатуру для отметки доставленных товаров
        markup = types.InlineKeyboardMarkup(row_width=1)
        for item in trip_items:
            if item['trip_item_status'] == 'pending':
                btn_text = f"✅ {item['product_name']} - {item['city']}, {item['street']}"
                callback_data = f"deliver_item_{trip_id}_{item['trip_item_id']}"
                markup.add(types.InlineKeyboardButton(btn_text, callback_data=callback_data))

        markup.add(types.InlineKeyboardButton("🏁 Завершить поездку", callback_data=f"finalize_trip_{trip_id}"))

        bot.edit_message_text(
            "Отметьте доставленные товары:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

        state.set(TripStates.completing_delivery)

    except Exception as e:
        bot.answer_callback_query(call.id, "Ошибка при завершении поездки")
        print(f"Error in handle_trip_completion: {e}")


@bot.callback_query_handler(func=lambda call: call.data.startswith('cancel_trip_'))
def handle_trip_cancellation(call: CallbackQuery, state: StateContext):
    """Обработка отмены поездки"""
    trip_id = int(call.data.split('_')[2])

    # Получаем информацию о товарах в поездке
    trip_items = trip_manager.get_trip_items(trip_id)

    # Создаем клавиатуру для выбора товаров для отмены
    markup = types.InlineKeyboardMarkup(row_width=1)
    for item in trip_items:
        if item['trip_item_status'] == 'pending':
            btn_text = f"❌ {item['product_name']} - {item['city']}, {item['street']}"
            callback_data = f"cancel_item_{trip_id}_{item['trip_item_id']}"
            markup.add(types.InlineKeyboardButton(btn_text, callback_data=callback_data))

    markup.add(types.InlineKeyboardButton("🔄 Подтвердить отмену", callback_data=f"confirm_cancellation_{trip_id}"))

    bot.edit_message_text(
        "Выберите товары для отмены:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

    state.set(TripStates.canceling_items)
    state.add_data(cancelled_items=[])


@bot.callback_query_handler(func=lambda call: call.data.startswith('deliver_item_'))
def handle_item_delivery(call: CallbackQuery, state: StateContext):
    """Обработка доставки отдельного товара"""
    try:
        _, trip_id, item_id = call.data.split('_')
        trip_id, item_id = int(trip_id), int(item_id)

        # Обновляем статус товара
        success = trip_manager.update_trip_item_status(item_id, 'delivered')
        if not success:
            bot.answer_callback_query(call.id, "Ошибка при обновлении статуса товара")
            return

        bot.answer_callback_query(call.id, "Товар отмечен как доставленный")

        # Обновляем клавиатуру
        trip_items = trip_manager.get_trip_items(trip_id)
        markup = types.InlineKeyboardMarkup(row_width=1)

        has_pending_items = False
        for item in trip_items:
            if item['trip_item_status'] == 'pending':
                has_pending_items = True
                btn_text = f"✅ {item['product_name']} - {item['city']}, {item['street']}"
                callback_data = f"deliver_item_{trip_id}_{item['trip_item_id']}"
                markup.add(types.InlineKeyboardButton(btn_text, callback_data=callback_data))

        if has_pending_items:
            markup.add(types.InlineKeyboardButton("🏁 Завершить поездку", callback_data=f"finalize_trip_{trip_id}"))
        else:
            # Если все товары доставлены, автоматически завершаем поездку
            finalize_trip(call, trip_id, state)
            return

        bot.edit_message_reply_markup(
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

    except Exception as e:
        bot.answer_callback_query(call.id, "Произошла ошибка при обработке доставки")
        print(f"Error in handle_item_delivery: {e}")


def finalize_trip(call: CallbackQuery, trip_id: int, state: StateContext):
    """Завершение поездки"""
    try:
        # Обновляем статус поездки
        success = trip_manager.update_trip_status(trip_id, 'completed')
        if not success:
            raise Exception("Failed to update trip status")

        # Получаем информацию о поездке
        trip_items = trip_manager.get_trip_items(trip_id)

        # Формируем итоговое сообщение
        summary_message = "🏁 Поездка завершена\n\n"

        # Группируем товары по статусам
        delivered_items = []
        cancelled_items = []

        for item in trip_items:
            item_info = f"• {item['product_name']} - {item['city']}, {item['street']}"
            if item['trip_item_status'] == 'delivered':
                delivered_items.append(item_info)
            elif item['trip_item_status'] in ['declined', 'refunded']:
                cancelled_items.append(item_info)

        # Добавляем информацию о доставленных товарах
        if delivered_items:
            summary_message += "✅ Доставлено:\n" + "\n".join(delivered_items) + "\n\n"

        # Добавляем информацию об отмененных товарах
        if cancelled_items:
            summary_message += "❌ Отменено:\n" + "\n".join(cancelled_items) + "\n"

        # Отправляем итоговое сообщение
        bot.edit_message_text(
            summary_message,
            call.message.chat.id,
            call.message.message_id
        )

        # Очищаем состояние
        state.delete()

    except Exception as e:
        bot.answer_callback_query(call.id, "Произошла ошибка при завершении поездки")
        print(f"Error in finalize_trip: {e}")


@bot.callback_query_handler(func=lambda call: call.data.startswith('finalize_trip_'))
def handle_trip_finalization(call: CallbackQuery, state: StateContext):
    """Обработчик завершения поездки"""
    try:
        trip_id = int(call.data.split('_')[2])
        # Проверяем, все ли товары имеют финальный статус
        trip_items = trip_manager.get_trip_items(trip_id)
        pending_items = [item for item in trip_items if item['trip_item_status'] == 'pending']

        if pending_items:
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    "✅ Да, завершить",
                    callback_data=f"force_finalize_{trip_id}"
                ),
                types.InlineKeyboardButton(
                    "🔄 Нет, вернуться",
                    callback_data=f"return_to_trip_{trip_id}"
                )
            )

            bot.answer_callback_query(call.id)
            bot.edit_message_text(
                "⚠️ Есть товары без статуса доставки. Уверены, что хотите завершить поездку?",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )
        else:
            finalize_trip(call, trip_id, state)

    except Exception as e:
        bot.answer_callback_query(call.id, "Произошла ошибка при завершении поездки")
        print(f"Error in handle_trip_finalization: {e}")


@bot.callback_query_handler(func=lambda call: call.data.startswith('force_finalize_'))
def handle_force_finalization(call: CallbackQuery, state: StateContext):
    """Принудительное завершение поездки"""
    trip_id = int(call.data.split('_')[2])
    # Помечаем все pending товары как отмененные
    trip_items = trip_manager.get_trip_items(trip_id)
    pending_items = [item['trip_item_id'] for item in trip_items if item['trip_item_status'] == 'pending']

    if pending_items:
        trip_manager.cancel_trip_items(trip_id, pending_items)

    finalize_trip(call, trip_id, state)


@bot.callback_query_handler(func=lambda call: call.data.startswith('return_to_trip_'))
def handle_return_to_trip(call: CallbackQuery, state: StateContext):
    """Возврат к управлению поездкой"""
    trip_id = int(call.data.split('_')[2])
    trip_items = trip_manager.get_trip_items(trip_id)

    markup = types.InlineKeyboardMarkup(row_width=1)
    for item in trip_items:
        if item['trip_item_status'] == 'pending':
            btn_text = f"✅ {item['product_name']} - {item['city']}, {item['street']}"
            callback_data = f"deliver_item_{trip_id}_{item['trip_item_id']}"
            markup.add(types.InlineKeyboardButton(btn_text, callback_data=callback_data))

    markup.add(types.InlineKeyboardButton("🏁 Завершить поездку", callback_data=f"finalize_trip_{trip_id}"))

    bot.edit_message_text(
        "Отметьте доставленные товары:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('cancel_item_'))
def handle_item_cancellation(call: CallbackQuery, state: StateContext):
    """Обработка отмены отдельного товара"""
    try:
        _, trip_id, item_id = call.data.split('_')
        trip_id, item_id = int(trip_id), int(item_id)

        with state.data() as data:
            cancelled_items = data.get('cancelled_items', [])
            if item_id not in cancelled_items:
                cancelled_items.append(item_id)
            data['cancelled_items'] = cancelled_items

        bot.answer_callback_query(call.id, "Товар отмечен для отмены")

        # Обновляем клавиатуру
        trip_items = trip_manager.get_trip_items(trip_id)
        markup = types.InlineKeyboardMarkup(row_width=1)

        for item in trip_items:
            if item['trip_item_status'] == 'pending':
                is_cancelled = item['trip_item_id'] in cancelled_items
                btn_text = f"{'❌' if is_cancelled else '🔄'} {item['product_name']} - {item['city']}, {item['street']}"
                callback_data = f"cancel_item_{trip_id}_{item['trip_item_id']}"
                markup.add(types.InlineKeyboardButton(btn_text, callback_data=callback_data))

        markup.add(types.InlineKeyboardButton(
            "🔄 Подтвердить отмену",
            callback_data=f"confirm_cancellation_{trip_id}"
        ))

        bot.edit_message_reply_markup(
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

    except Exception as e:
        bot.answer_callback_query(call.id, "Произошла ошибка при отмене товара")
        print(f"Error in handle_item_cancellation: {e}")


@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_cancellation_'))
def handle_cancellation_confirmation(call: CallbackQuery, state: StateContext):
    """Подтверждение отмены товаров"""
    try:
        trip_id = int(call.data.split('_')[2])

        with state.data() as data:
            cancelled_items = data.get('cancelled_items', [])

        if not cancelled_items:
            bot.answer_callback_query(call.id, "Выберите товары для отмены")
            return

        # Отменяем выбранные товары
        success = trip_manager.cancel_trip_items(trip_id, cancelled_items)
        if not success:
            raise Exception("Failed to cancel items")

        # Проверяем, остались ли активные товары
        trip_items = trip_manager.get_trip_items(trip_id)
        pending_items = [item for item in trip_items if item['trip_item_status'] == 'pending']

        if pending_items:
            # Если есть активные товары, возвращаемся к управлению поездкой
            markup = types.InlineKeyboardMarkup(row_width=1)
            for item in pending_items:
                btn_text = f"✅ {item['product_name']} - {item['city']}, {item['street']}"
                callback_data = f"deliver_item_{trip_id}_{item['trip_item_id']}"
                markup.add(types.InlineKeyboardButton(btn_text, callback_data=callback_data))

            markup.add(types.InlineKeyboardButton("🏁 Завершить поездку", callback_data=f"finalize_trip_{trip_id}"))

            bot.edit_message_text(
                "Товары отменены. Продолжите доставку оставшихся товаров:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )
        else:
            # Если активных товаров не осталось, завершаем поездку
            finalize_trip(call, trip_id, state)

    except Exception as e:
        bot.answer_callback_query(call.id, "Произошла ошибка при подтверждении отмены")
        print(f"Error in handle_cancellation_confirmation: {e}")