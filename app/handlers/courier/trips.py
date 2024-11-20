from pprint import pprint

from telebot.handler_backends import State, StatesGroup
from telebot import types
from telebot.types import Message, CallbackQuery
from telebot.states.sync.context import StateContext
from datetime import datetime

from middlewares.delivery_zones import (
    DeliveryZoneManager,
    AddressComponents,
    DeliveryCostCalculator,
CourierTripManager
)
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

from database import get_order_by_id

from utils import generate_map_link

from database import update_order_item_status, update_order_delivery_note, update_order_delivery_sum
from states import CourierStates

from config import WAREHOUSE_LOCATION

from database import get_delivery_coordinates

from handlers.handlers import delete_multiple_states

from handlers.handlers import get_user_by_username

from database import update_trip_item, increment_stock

from utils import is_valid_command

from database import update_order_invoice_photo
from utils import create_media_group, save_photo_and_resize
import time
from database import get_connection as connection

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
    selected_items=State()
    cancelled_items=State()


@bot.callback_query_handler(func=lambda call: call.data == 'create_trip')
def start_trip_creation(call: CallbackQuery, state: StateContext):
    """Начало создания поездки"""
    message = call.message
    delete_multiple_states(state,['selecting_orders','confirm_orders','trip_in_progress','completing_delivery','canceling_items','selected_items'])
    delete_multiple_states(state,['selecting_delivered_items','avito_photos_sent'])
    delete_multiple_states(state, [
        'selecting_delivered_items',
        'avito_photos_sent',
        'avito_order_shown',
        'avito_message_id',
        'current_order_id'
        'avito_photos_messages'
    ])
    try:
        # Получаем информацию о курьере
        courier_info = get_user_info(call.message.json['chat']['username'])
        if not courier_info:
            bot.edit_message_text(
                "Не удалось получить информацию о курьере.",
                call.message.chat.id,
                call.message.message_id
            )
            return

        # Проверяем наличие активных поездок
        active_trips = trip_manager.get_courier_active_trips(courier_info['id'])
        if active_trips:
            # Создаем клавиатуру с кнопкой перехода к текущей поездке
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton(
                    "🚚 Текущая поездка",
                    callback_data="show_current_trip"
                )
            )

            # Отправляем сообщение о необходимости завершить текущую поездку
            bot.edit_message_text(
                "⚠️ У вас есть незаконченная поездка\n"
                "Закончите или отмените ее, чтобы начать новую",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )
            return

        # Если активных поездок нет, продолжаем создание новой
        available_orders = get_orders(
            item_status=[OrderType.READY_TO_DELIVERY.value],
            order_type=['avito', 'delivery'],
            status=[OrderType.READY_TO_DELIVERY.value, OrderType.PARTLY_DELIVERED.value],
            role='courier',
            username=courier_info['username']
        )

        if not available_orders:
            bot.edit_message_text(
                "Нет доступных заказов для доставки.",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_courier_menu")
                )
            )
            return

        # Создаем клавиатуру для выбора заказов
        markup = get_orders_keyboard(available_orders)

        bot.edit_message_text(
            "Выберите заказы для добавления в поездку. \nВы можете выбрать один или несколько товаров (трекномеров для авито) для доставки, просто нажмите на желаемый товар(трекномер) \n\nЕсли в заказе все товары выбраны, на товаре загорится значок ✅\n Если выбрана только часть товаров - значок ⚡️\n\nПосле выбора товаров для доставки нажмите кнопку ✅Подтвердить выбор",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup.add(
                    types.InlineKeyboardButton("🔙 Вернуться в меню", callback_data="back_to_courier_menu"))
        )

        # Устанавливаем состояние выбора заказов
        state.set(TripStates.selecting_orders)
        state.add_data(selected_orders=[])

    except Exception as e:
        bot.edit_message_text(
            "Произошла ошибка при создании поездки.",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_courier_menu")
            )
        )
        print(f"Error in start_trip_creation: {e}")


def build_menu(buttons, n_cols=1, header_buttons=None, footer_buttons=None):
    """Строит меню кнопок с указанным количеством колонок"""
    menu = [buttons[i:i + n_cols] for i in range(0, len(buttons), n_cols)]
    if header_buttons:
        menu.insert(0, header_buttons)
    if footer_buttons:
        menu.append(footer_buttons)
    return menu


@bot.callback_query_handler(func=lambda call: call.data.startswith('show_avito_order_'))
def show_avito_order(call: CallbackQuery, state: StateContext):
    """Показывает информацию о заказе Авито и его трек-номерах"""
    try:
        order_id = int(call.data.split('_')[3])

        # Получаем информацию о заказе
        order = get_order_by_id(order_id, [OrderType.READY_TO_DELIVERY.value])
        if not order:
            bot.answer_callback_query(call.id, "Заказ не найден")
            return

        # Проверяем первый ли это показ заказа
        with state.data() as data:
            selected_items = data.get('selected_items', {})
            current_order_selections = selected_items.get(str(order_id), [])
            avito_order_shown = data.get('avito_order_shown', False)
            orders_message_id = call.message.message_id

        # Получаем список трек-номеров
        track_numbers = {}
        for track_number, track_info in order['products'].items():
            if track_number != 'no_track':
                track_numbers[track_number] = track_info['products']

        # Если заказ показывается впервые
        if not avito_order_shown:
            # Удаляем сообщение со списком заказов
            bot.delete_message(call.message.chat.id, orders_message_id)

            # Отправляем фотографии
            avito_photos = []
            for track_number in track_numbers.keys():
                photos = get_avito_photos(order_id)
                if photos:
                    avito_photos.extend(photos)

            if avito_photos:
                try:
                    media_group = create_media_group(avito_photos, None)
                    sent_photos = bot.send_media_group(call.message.chat.id, media=media_group)
                    state.add_data(avito_photos_messages=[msg.message_id for msg in sent_photos])
                except Exception as e:
                    print(f"Error sending media group: {e}")

            # Отправляем новое сообщение с информацией о заказе
            message_text = get_avito_order_message(order, track_numbers, current_order_selections)
            markup = get_avito_order_markup(order_id, track_numbers, current_order_selections)

            new_message = bot.send_message(
                call.message.chat.id,
                message_text,
                reply_markup=markup
            )

            # Сохраняем информацию о том, что заказ уже показан и ID нового сообщения
            state.add_data(
                avito_order_shown= True,
                current_order_id= order_id,
                avito_message_id= new_message.message_id,
                current_message_to_edit = new_message.message_id,
            )
        else:
            # Если заказ уже показывался, просто обновляем существующее сообщение
            with state.data() as data:
                avito_message_id = data.get('avito_message_id')
                previous_message = data.get('previous_message_text', '')

            message_text = get_avito_order_message(order, track_numbers, current_order_selections)
            markup = get_avito_order_markup(order_id, track_numbers, current_order_selections)

            if message_text != previous_message:
                mes = bot.edit_message_text(
                    message_text,
                    call.message.chat.id,
                    avito_message_id,
                    reply_markup=markup
                )
                # Сохраняем новый текст сообщения
                state.add_data(previous_message_text=message_text, current_message_to_edit=mes.id)

    except Exception as e:
        bot.answer_callback_query(call.id, "Ошибка при отображении заказа")
        print(f"Error in show_avito_order: {e}")


def get_avito_order_message(order, track_numbers, current_order_selections):
    """Формирует текст сообщения для заказа Авито"""
    message_text = [
        f"📦 Заказ #{str(order['id']).zfill(4)}ㅤ",
        f"Тип заказа - Авито",
        f"Менеджер - {order.get('manager_username', 'Не указан')}",
        f"Заметка - {order.get('note', 'Не указано')}"
        f"\nСостав заказа:"
    ]

    for track_number, products in track_numbers.items():
        message_text.append(f"\n{track_number}:")
        for product in products:
            message_text.append(f"\t• {product['name']} - {product.get('param', '')}")

    message_text.append("\nВыберите трек-номера для добавления в поездку:")

    return '\n'.join(message_text)


def get_avito_order_markup(order_id, track_numbers, current_order_selections):
    """Формирует клавиатуру для заказа Авито"""
    markup = types.InlineKeyboardMarkup(row_width=1)

    for track_number, items in track_numbers.items():
        # Собираем все order_item_id для данного трек-номера
        order_item_ids = [str(item['order_item_id']) for item in items]
        item_key = f"{track_number}|{order_id}|{','.join(order_item_ids)}"
        is_selected = item_key in current_order_selections
        prefix = "☑️" if is_selected else "⬜️"

        markup.add(types.InlineKeyboardButton(
            f"{prefix} Трек-номер: {track_number}",
            callback_data=f"toggle_avito_item_{order_id}_{','.join(order_item_ids)}_{track_number}"
        ))

    markup.add(
        # types.InlineKeyboardButton("✅ Выбрать все", callback_data=f"select_all_avito_{order_id}"),
        types.InlineKeyboardButton("🔙 Назад к заказам", callback_data="back_to_orders")
    )

    return markup
def show_avito_trip_order(call: CallbackQuery, state: StateContext, order_id: int):
    """Показывает информацию о заказе Авито в поездке"""
    try:
        order = get_order_by_id(order_id, item_statuses=[OrderType.IN_DELIVERY.value])
        if not order:
            bot.answer_callback_query(call.id, "Заказ не найден")
            return

        # Получаем товары заказа в поездке
        trip_items = trip_manager.get_trip_items_for_order(
            order_id,
            order_item_status=[OrderType.IN_DELIVERY.value],
            trip_status=['pending'],
            courier_trip_status=['created']
        )

        # Группируем товары по трек-номерам
        tracks_in_trip = {}
        for item in trip_items:
            product_name = item['product_name']
            param_title = item.get('param_title', '')
            track_number = next(
                (track for track, info in order['products'].items()
                 if any(p['name'] == product_name and p.get('param') == param_title
                        for p in info.get('products', []))),
                None
            )
            if track_number:
                if track_number not in tracks_in_trip:
                    tracks_in_trip[track_number] = {
                        'products': [],
                        'trip_items': []
                    }
                tracks_in_trip[track_number]['products'].append(f"{product_name} - {param_title}")
                tracks_in_trip[track_number]['trip_items'].append(item)

        # Формируем сообщение
        message_text = [
            f"📦 Заказ #{str(order['id']).zfill(4)}ㅤ",
            f"Тип заказа - Авито",
            f"Менеджер - @{order.get('manager_username', 'Не указан')}",
            f"Заметка - {order.get('note', 'Нет')}",
            f"\nСостав заказа в поездке:"
        ]

        for track_number, track_data in tracks_in_trip.items():
            message_text.append(f"\n{track_number}:")
            for product in track_data['products']:
                message_text.append(f"\t• {product}")

        # Создаем клавиатуру с трек-номерами
        markup = types.InlineKeyboardMarkup(row_width=1)

        for track_number, track_data in tracks_in_trip.items():
            markup.add(types.InlineKeyboardButton(
                f"📦 Трек-номер: {track_number}",
                callback_data=f"process_avito_track_{order_id}_{track_number}"
            ))

        markup.add(types.InlineKeyboardButton(
            "🔙 Назад к поездке",
            callback_data="show_current_trip"
        ))

        # Получаем и отправляем фотографии для трек-номеров в поездке
        avito_photos = []
        for track_number in tracks_in_trip.keys():
            photos = get_avito_photos(order_id)
            avito_photos.extend([photo for photo in photos if photo])

        if avito_photos:
            media_group = create_media_group(avito_photos, None)
            bot.send_media_group(call.message.chat.id, media=media_group)

        bot.edit_message_text(
            '\n'.join(message_text),
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

    except Exception as e:
        print(f"Error in show_avito_trip_order: {e}")
        bot.send_message(call.message.chat.id, "Произошла ошибка при отображении заказа")


@bot.callback_query_handler(func=lambda call: call.data.startswith('process_avito_track_'))
def process_avito_track(call: CallbackQuery, state: StateContext):
    """Обработка действий с трек-номером в поездке"""
    try:
        _, order_id, track_number = call.data.split('_')
        order_id = int(order_id)

        # Получаем заказ и его товары
        order = get_order_by_id(order_id, item_statuses=[OrderType.IN_DELIVERY.value])

        # Получаем информацию о товарах в треке
        track_products = []
        if order and track_number in order['products']:
            track_products = order['products'][track_number]['products']

        # Формируем сообщение
        message_text = [
            f"📦 Заказ #{str(order_id).zfill(4)}ㅤ",
            f"Трек-номер: {track_number}",
            f"Менеджер: @{order.get('manager_username', 'Не указан')}",
            f"Количество мешков: {order.get('avito_boxes', 0)}",
            "\nТовары в треке:"
        ]

        for product in track_products:
            message_text.append(f"• {product['name']} - {product.get('param', '')}")

        # Создаем клавиатуру
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("✅ Далее", callback_data=f"complete_avito_track_{order_id}_{track_number}"),
            types.InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_avito_track_{order_id}_{track_number}"),

        )

        # Получаем фото для трек-номера
        photos = get_avito_photos(order_id)
        if photos:
            track_photos = [photo for photo in photos if photo]
            if track_photos:
                media_group = create_media_group(track_photos, None)
                bot.send_media_group(call.message.chat.id, media=media_group)

        bot.edit_message_text(
            '\n'.join(message_text),
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

    except Exception as e:
        print(f"Error in process_avito_track: {e}")
        bot.answer_callback_query(call.id, "Произошла ошибка при обработке трек-номера")


@bot.callback_query_handler(func=lambda call: call.data.startswith('complete_avito_track_'))
def handle_complete_avito_track(call: CallbackQuery, state: StateContext):
    """Обработчик завершения доставки трек-номера Авито"""
    try:
        _,_,_, order_id, track_number = call.data.split('_')
        order_id = int(order_id)

        # Сохраняем информацию в state для последующей обработки
        state.add_data(
            processing_order_id= order_id,
            processing_track_number= track_number
        )

        # Запрашиваем фото накладной
        bot.edit_message_text(
            "📸 Пожалуйста, отправьте фото накладной",
            call.message.chat.id,
            call.message.message_id
        )

        state.set(CourierStates.waiting_for_invoice)

    except Exception as e:
        print(f"Error in handle_complete_avito_track: {e}")
        bot.answer_callback_query(call.id, "Произошла ошибка при обработке трек-номера")


@bot.message_handler(content_types=['photo'], state=CourierStates.waiting_for_invoice)
def handle_invoice_photo(message: Message, state: StateContext):
    """Обработчик получения фото накладной"""
    try:
        with state.data() as data:
            order_id = data.get('processing_order_id')
            track_number = data.get('processing_track_number')

        if not order_id or not track_number:
            bot.reply_to(message, "Ошибка: не найдена информация о заказе")
            return

        # Сохраняем фото накладной
        photo = message.photo[-1]
        file_info = bot.get_file(photo.file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        # Сохраняем фото и получаем путь к файлу
        photo_path = save_photo_and_resize(downloaded_file, f"invoice_{order_id}_{track_number}")

        # Обновляем запись в базе данных
        if not update_order_invoice_photo(order_id, track_number, photo_path):
            raise Exception("Failed to update invoice photo")

        # Переходим к завершению доставки
        process_avito_delivery_completion(message.from_user.username, message.chat.id, order_id, track_number,photo_path, state)

    except Exception as e:
        print(f"Error in handle_invoice_photo: {e}")
        bot.reply_to(message, "Произошла ошибка при сохранении фото накладной")


@bot.callback_query_handler(func=lambda call: call.data.startswith('cancel_avito_track_'))
def handle_cancel_avito_track(call: CallbackQuery, state: StateContext):
    """Обработчик отмены доставки трек-номера Авито"""
    try:
        _,_,_, order_id, track_number = call.data.split('_')
        order_id = int(order_id)

        order = get_order_by_id(order_id, [OrderType.IN_DELIVERY.value] )

        # Получаем все товары этого трек-номера
        trip_items = trip_manager.get_trip_items_for_order(
            order_id,
            order_item_status=[OrderType.IN_DELIVERY.value],
            trip_status=['pending']
        )

        # Фильтруем товары по трек-номеру
        track_items = []
        for item in trip_items:
            product_name = item['product_name']
            param_title = item.get('param_title', '')
            item_track = next(
                (track for track, info in order['products'].items()
                 if any(p['name'] == product_name and p.get('param') == param_title
                        for p in info.get('products', []))),
                None
            )
            if item_track == track_number:
                track_items.append(item)

        # Обрабатываем отмену
        for item in track_items:
            # Обновляем статус товара в order_items на REFUND
            update_order_item_status(item['order_item_id'], OrderType.REFUND.value)
            # Обновляем статус в trip_items
            update_trip_item('refunded', item['order_item_id'])
            # Увеличиваем сток
            increment_stock(item['product_param_id'])

        # Проверяем состояние остальных трек-номеров
        remaining_items = trip_manager.get_trip_items_for_order(
            order_id,
            order_item_status=[OrderType.IN_DELIVERY.value],
            trip_status=['pending']
        )

        if not remaining_items:
            # Если нет активных товаров, проверяем все товары заказа
            all_trip_items = trip_manager.get_trip_items_for_order(order_id)
            all_statuses = [item['status'] for item in all_trip_items]

            if all(status in [OrderType.CLOSED.value, OrderType.REFUND.value] for status in all_statuses):
                # Если все товары имеют финальный статус, закрываем заказ
                update_order_status(order_id, OrderType.CLOSED.value)
            else:
                # Иначе ставим частичную доставку
                update_order_status(order_id, OrderType.PARTLY_DELIVERED.value)
            active_trip = trip_manager.get_courier_active_trips(order['courier_id'])[0]
            trip_manager.update_trip_status(active_trip['id'], 'completed')
        # Формируем сообщение об отмене
        cancel_message = (
            f"❌ Трек-номер {track_number} отменён\n"
            f"Заказ #{str(order_id).zfill(4)}ㅤ\n"
            "Товары возвращены на склад"
        )

        bot.edit_message_text(
            cancel_message,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("🔙 Назад к поездке", callback_data="show_current_trip")
            )
        )

        # Отправляем сообщение в канал
        bot.send_message(
            CHANNEL_CHAT_ID,
            cancel_message,
            reply_to_message_id=order.get('message_id')
        )

    except Exception as e:
        print(f"Error in handle_cancel_avito_track: {e}")
        bot.answer_callback_query(call.id, "Произошла ошибка при отмене трек-номера")


def process_avito_delivery_completion(username: str, chat_id: int, order_id: int, track_number: str,invoice_path,
                                      state: StateContext):
    """
    Обработка успешной доставки трек-номера Авито

    Args:
        username: Username курьера
        chat_id: ID чата для отправки сообщений
        order_id: ID заказа
        track_number: Номер трека Авито
        state: Состояние бота
    """
    try:
        # Получаем информацию о заказе
        order = get_order_by_id(order_id)
        if not order:
            raise ValueError(f"Order {order_id} not found")

        # Получаем товары этого трек-номера в поездке
        trip_items = trip_manager.get_trip_items_for_order(
            order_id,
            order_item_status=[OrderType.IN_DELIVERY.value],
            trip_status=['pending']
        )

        # Фильтруем товары по трек-номеру
        track_items = []
        delivered_products = []
        for item in trip_items:
            product_name = item['product_name']
            param_title = item.get('param_title', '')
            order_item_id = item.get('order_item_id', '')
            item_track = next(
                (track for track, info in order['products'].items()
                 if any(p['name'] == product_name and p.get('param') == param_title and order_item_id == p.get('order_item_id')
                        for p in info.get('products', []))),
                None
            )
            if item_track == track_number:
                track_items.append(item)
                delivered_products.append(f"• {product_name} - {param_title}")

        # Обрабатываем доставку
        for item in track_items:
            # Обновляем статус товара в order_items на CLOSED
            update_order_item_status(item['order_item_id'], OrderType.CLOSED.value)
            # Обновляем статус в trip_items
            update_trip_item('delivered', item['order_item_id'])

        # Проверяем состояние остальных трек-номеров
        remaining_items = trip_manager.get_trip_items_for_order(
            order_id,
            order_item_status=[OrderType.IN_DELIVERY.value],
            trip_status=['pending']
        )

        if not remaining_items:
            # Если нет активных товаров, проверяем все товары заказа
            all_trip_items = trip_manager.get_trip_items_for_order(order_id)
            all_statuses = [item['status'] for item in all_trip_items]

            if all(status in [OrderType.CLOSED.value, OrderType.REFUND.value] for status in all_statuses):
                # Если все товары имеют финальный статус, закрываем заказ
                update_order_status(order_id, OrderType.CLOSED.value)
            else:
                # Иначе ставим частичную доставку
                update_order_status(order_id, OrderType.PARTLY_DELIVERED.value, )

        # Получаем информацию о курьере
        courier_info = get_user_by_username(username, state)

        # Формируем сообщение о доставке
        delivery_message = (
            f"✅ Трек-номер {track_number} доставлен\n"
            f"📦 Заказ #{str(order_id).zfill(4)}ㅤ\n"
            f"👤 Менеджер: {order.get('manager_username', 'Не указан')}\n\n"
            "📋 Доставленные товары:\n"
            f"{chr(10).join(delivered_products)}\n\n"
            f"🚚 Курьер: {courier_info['name']} ({courier_info['username']})"
        )

        # Проверяем остались ли активные заказы в поездке
        courier_id = courier_info['id']
        active_trip = trip_manager.get_courier_active_trips(courier_id)[0]
        remaining_trip_items = trip_manager.get_trip_items(active_trip['id'])

        markup = types.InlineKeyboardMarkup()

        if not remaining_trip_items:
            # Если активных заказов больше нет, завершаем поездку
            trip_manager.update_trip_status(active_trip['id'], 'completed')
            delivery_message += "\n\n✅ Поездка завершена"
            markup.add(types.InlineKeyboardButton("Вернуться в меню", callback_data='back_to_courier_menu'))
        else:
            markup.add(
                types.InlineKeyboardButton("Текущая поездка", callback_data="show_current_trip"),
                types.InlineKeyboardButton("Вернуться в меню", callback_data='back_to_courier_menu')
            )

        # Отправляем сообщение курьеру
        bot.send_message(
            chat_id,
            delivery_message,
            reply_markup=markup
        )

        # Отправляем сообщение в канал
        # bot.send_message(
        #     CHANNEL_CHAT_ID,
        #     delivery_message,
        #     reply_to_message_id=order.get('message_id')
        # )
        media_group = create_media_group([invoice_path], delivery_message)
        bot.send_media_group(CHANNEL_CHAT_ID, media=media_group,reply_to_message_id=order.get('message_id'))

        # Очищаем состояния
        delete_multiple_states(state, [
            'processing_order_id',
            'processing_track_number',
            'delivered_items',
            'current_order_id',
            'delivery_sum'
        ])

    except Exception as e:
        print(f"Error in process_avito_delivery_completion: {e}")
        bot.send_message(chat_id, "Произошла ошибка при обработке доставки")


@bot.callback_query_handler(func=lambda call: call.data.startswith('toggle_avito_item_'))
def toggle_avito_item_selection(call: CallbackQuery, state: StateContext):
    """Обработка выбора/отмены выбора трек-номера"""
    try:
        parts = call.data.split('_')
        order_id = parts[3]
        order_item_ids = parts[4]
        track_number = parts[5]

        item_key = f"{track_number}|{order_id}|{order_item_ids}"

        # Получаем информацию о заказе
        order = get_order_by_id(int(order_id), [OrderType.READY_TO_DELIVERY.value])
        if not order:
            raise ValueError(f"Order {order_id} not found")

        with state.data() as data:
            selected_items = data.get('selected_items', {})
            if str(order_id) not in selected_items:
                selected_items[str(order_id)] = []

            if item_key in selected_items[str(order_id)]:
                selected_items[str(order_id)].remove(item_key)
                action = "удален из"
            else:
                selected_items[str(order_id)].append(item_key)
                action = "добавлен в"

            avito_message_id = data.get('avito_message_id')

        state.add_data(selected_items=selected_items)

        # Получаем список трек-номеров
        track_numbers = {}
        for tn, track_info in order['products'].items():
            if tn != 'no_track':
                track_numbers[tn] = track_info['products']

        # Обновляем сообщение напрямую
        message_text = get_avito_order_message(order, track_numbers, selected_items.get(str(order_id), []))
        markup = get_avito_order_markup(order_id, track_numbers, selected_items.get(str(order_id), []))

        mes = bot.edit_message_text(
            message_text,
            call.message.chat.id,
            avito_message_id,
            reply_markup=markup
        )
        state.add_data(current_message_to_edit=mes.message_id)
        bot.answer_callback_query(
            call.id,
            f"Трек-номер {action} поездку"
        )

    except Exception as e:
        print(f"Error in toggle_avito_item_selection: {e}")
        bot.answer_callback_query(call.id, "Ошибка при выборе трек-номера")


def get_orders_keyboard(orders: list, selected_items: dict = None) -> types.InlineKeyboardMarkup:
    button_list = []
    for order in orders:
        order_id = str(order['id']).zfill(4)

        # Получаем список order_item_ids для заказа
        if order['order_type'] == 'avito':
            # Для Авито считаем количество трекномеров
            track_numbers = list(order['products'].keys())
            track_numbers = [tn for tn in track_numbers if tn != 'no_track']
            total_items = len(track_numbers)
            items_text = f"{total_items} трек-номеров"
            default_prefix = "📬"  # Специальный смайлик для Авито
        else:
            # Для обычных заказов считаем количество товаров
            order_items = order['products'].get('no_track', {}).get('products', [])
            total_items = len(order_items)
            items_text = f"{total_items} товаров"
            default_prefix = "📦"

        # Проверяем выбранные товары
        selected_count = 0
        if selected_items and str(order['id']) in selected_items:
            if order['order_type'] == 'avito':
                # Для Авито считаем выбранные трекномера
                selected_tracks = set(item_key.split('|')[0] for item_key in selected_items[str(order['id'])])
                selected_count = len(selected_tracks)
            else:
                selected_count = len(selected_items[str(order['id'])])

        # Определяем префикс
        if selected_count == 0:
            prefix = default_prefix
        elif selected_count == total_items:
            prefix = "✅"
        else:
            prefix = "⚡️"

        # Формируем адресную часть
        if order['order_type'] == 'avito':
            address_text = "Авито"
        else:
            full_address = order.get('delivery_address', '')
            if full_address:
                address_parts = [part.strip() for part in full_address.split(',')]
                if len(address_parts) > 1:
                    address_text = ', '.join(address_parts[1:])
                else:
                    address_text = 'Адрес не указан'
            else:
                address_text = 'Адрес не указан'

        button_text = f"{prefix} Заказ #{order_id}ㅤ- {address_text} ({items_text})"

        callback_data = f"show_avito_order_{order['id']}" if order[
                                                                 'order_type'] == 'avito' else f"show_order_items_{order['id']}"

        button_list.append(
            types.InlineKeyboardButton(
                button_text,
                callback_data=callback_data
            )
        )

    footer_buttons = None
    if selected_items and any(selected_items.values()):
        footer_buttons = [
            types.InlineKeyboardButton("✅ Подтвердить выбор", callback_data="confirm_orders")
        ]

    return types.InlineKeyboardMarkup(
        build_menu(button_list, n_cols=1, footer_buttons=footer_buttons)
    )


def get_order_items_keyboard(order_id: int, items: list, selected_items: list = None,
                             order_type: str = 'delivery') -> types.InlineKeyboardMarkup:
    """
    Создает клавиатуру для выбора товаров из заказа

    Args:
        order_id: ID заказа
        items: список товаров
        selected_items: список выбранных товаров
        order_type: тип заказа ('delivery' или 'avito')
    """
    button_list = []
    selected_items = selected_items or []

    if order_type == 'avito':
        button_list.extend([
            # types.InlineKeyboardButton("✅ Выбрать все", callback_data=f"select_all_{order_id}"),
            # types.InlineKeyboardButton("❌ Убрать все", callback_data=f"deselect_all_{order_id}"),
            types.InlineKeyboardButton("🔙 Назад к заказам", callback_data="back_to_orders")
        ])
    else:
        for idx, item in enumerate(items):
            # Создаем уникальный ключ для товара на основе order_item_id или других данных
            item_key = f"{item['order_item_id']}|{item.get('product_id')}|{item.get('param_id')}"

            # Проверяем, выбран ли товар
            is_selected = item_key in selected_items

            # Выбираем префикс в зависимости от состояния
            prefix = "☑️" if is_selected else "⬜️"

            # Получаем информацию о товаре
            product_name = item.get('name', item.get('product_name', 'Неизвестный товар'))
            param_title = item.get('param', item.get('param_title', ''))

            # Формируем текст кнопки
            button_text = f"{prefix} {product_name} - {param_title}"

            # Создаем callback_data
            callback_data = f"toggle_item_{order_id}_{item_key}"

            button_list.append(
                types.InlineKeyboardButton(button_text, callback_data=callback_data)
            )

    # Добавляем кнопки внизу
    footer_buttons = [
        # types.InlineKeyboardButton("✅ Выбрать все", callback_data=f"select_all_{order_id}"),
        types.InlineKeyboardButton("🔙 Назад к заказам", callback_data="back_to_orders")
    ]

    return types.InlineKeyboardMarkup(
        build_menu(button_list, n_cols=1, footer_buttons=footer_buttons if order_type != 'avito' else [])
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('select_all_'), state=TripStates.selecting_orders)
def select_all_items(call: CallbackQuery, state: StateContext):
    """Обработчик выбора всех товаров"""
    try:
        order_id = int(call.data.split('_')[2])

        # Получаем заказ
        order = get_order_by_id(order_id,[OrderType.READY_TO_DELIVERY.value])
        if not order:
            raise ValueError(f"Order {order_id} not found")

        # Получаем список всех товаров
        if order['order_type'] == 'delivery':
            no_track_data = order['products'].get('no_track', {})
            items = no_track_data.get('products', []) if isinstance(no_track_data, dict) else []
        else:
            items = []
            for track_info in order['products'].values():
                if isinstance(track_info, dict) and 'products' in track_info:
                    items.extend(track_info['products'])

        # Создаем список всех item_keys
        all_item_keys = [f"{item.get('order_item_id')}|{item.get('product_id')}|{item.get('param_id')}" for idx, item in enumerate(items)]

        # Сохраняем в state
        with state.data() as data:
            selected_items = data.get('selected_items', {})
            selected_items[str(order_id)] = all_item_keys
        # data['selected_items'] = selected_items
        state.add_data(selected_items=selected_items)

        # Возвращаемся к списку заказов
        orders = get_orders(
            order_type=['avito', 'delivery'],
            status=[OrderType.READY_TO_DELIVERY.value],
            role='courier',
            username=call.message.json['chat']['username'],
            item_status=[OrderType.READY_TO_DELIVERY.value]

        )
        if orders:
            markup = get_orders_keyboard(orders, selected_items)

            bot.edit_message_text(
                "📦 Доступные заказы:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )

            bot.answer_callback_query(
                call.id,
                "Все товары выбраны"
            )

    except Exception as e:
        print(f"Error in select_all_items: {e}")
        bot.answer_callback_query(call.id, "Ошибка при выборе товаров")

@bot.callback_query_handler(func=lambda call: call.data.startswith('show_order_items_'))
def show_order_items(call: CallbackQuery, state: StateContext):
    """Показывает товары в выбранном заказе"""
    try:
        order_id = int(call.data.split('_')[3])

        # Получаем информацию о заказе
        order = get_order_by_id(order_id,[OrderType.READY_TO_DELIVERY.value])
        if not order:
            bot.answer_callback_query(call.id, "Заказ не найден")
            return

        # Получаем ранее выбранные товары из состояния
        with state.data() as data:
            selected_items = data.get('selected_items', {})
            current_order_selections = selected_items.get(str(order_id), [])
        print(selected_items,'123',current_order_selections)
        # Получаем список товаров в зависимости от типа заказа
        if order['order_type'] == 'delivery':
            no_track_data = order['products'].get('no_track', {})
            items = no_track_data.get('products', []) if isinstance(no_track_data, dict) else []
        else:
            items = []
            for track_info in order['products'].values():
                if isinstance(track_info, dict) and 'products' in track_info:
                    items.extend(track_info['products'])

        # Форматируем адрес для отображения
        if order['order_type'] == 'avito':
            address_display = "Авито"
        else:
            full_address = order.get('delivery_address', '')
            if full_address:
                # Убираем город из адреса
                address_parts = [part.strip() for part in full_address.split(',')]
                address_display = full_address
            else:
                address_display = 'Адрес не указан'

        # Создаем сообщение с информацией о заказе и товарах
        message_text = [
            f"📦 Заказ #{str(order['id']).zfill(4)}ㅤ",
            f"📍 Адрес: {address_display}"
        ]

        if order['order_type'] == 'delivery':
            message_text.extend([
                f"📱 Контакт: {order.get('contact_name', 'Не указан')}",
                f"☎️ Телефон: {order.get('contact_phone', 'Не указан')}",
                f"🕒 Время: {order.get('delivery_time', 'Не указано')}",
                f"📅 Дата: {order.get('delivery_date', 'Не указана')}"

            ])
        message_text.append("\nВыберите товары для добавления в поездку:")

        # Создаем клавиатуру с товарами
        markup = get_order_items_keyboard(
            order_id,
            items,
            current_order_selections,
            order['order_type']
        )

        # Обновляем сообщение
        mes = bot.edit_message_text(
            '\n'.join(message_text),
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

        # Сохраняем текущий заказ в состоянии
        state.add_data(current_order_id=order_id,current_message_to_edit=mes.message_id)

    except Exception as e:
        bot.answer_callback_query(call.id, "Ошибка при отображении товаров")
        print(f"Error in show_order_items: {e}")
        print(f"Order ID: {order_id}")
        if 'order' in locals():
            print(f"Order data: {order}")


@bot.callback_query_handler(func=lambda call: call.data.startswith('toggle_item_'))
def toggle_item_selection(call: CallbackQuery, state: StateContext):
    """
    Обработка выбора/отмены выбора товара
    """
    try:
        # Разбираем callback_data, используем полное разделение
        parts = call.data.split('_')
        if len(parts) != 4:  # должно быть: ['toggle', 'item', 'order_id', 'item_key']
            raise ValueError(f"Invalid callback data format: {call.data}")

        order_id = parts[2]
        item_key = parts[3]

        with state.data() as data:
            # Инициализируем структуру для хранения выбранных товаров
            selected_items = data.get('selected_items', {})
            if str(order_id) not in selected_items:
                selected_items[str(order_id)] = []

            # Переключаем выбор товара
            if item_key in selected_items[str(order_id)]:
                selected_items[str(order_id)].remove(item_key)
                action = "удален из"
            else:
                selected_items[str(order_id)].append(item_key)
                action = "добавлен в"


        state.add_data(selected_items=selected_items)


        # Получаем информацию о заказе
        order = get_order_by_id(int(order_id),[OrderType.READY_TO_DELIVERY.value])
        if not order:
            raise ValueError(f"Order {order_id} not found")

        # Получаем список товаров
        if order['order_type'] == 'delivery':
            no_track_data = order['products'].get('no_track', {})
            items = no_track_data.get('products', []) if isinstance(no_track_data, dict) else []
        else:
            items = []
            for track_info in order['products'].values():
                if isinstance(track_info, dict) and 'products' in track_info:
                    items.extend(track_info['products'])

        # Обновляем клавиатуру
        markup = get_order_items_keyboard(
            int(order_id),
            items,
            selected_items[str(order_id)],
            order['order_type']
        )

        try:
            mes = bot.edit_message_reply_markup(
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )
            state.add_data(current_message_to_edit=mes.message_id)
        except Exception as telegram_error:
            if "message is not modified" not in str(telegram_error):
                raise telegram_error

        # Показываем уведомление о действии
        bot.answer_callback_query(
            call.id,
            f"Товар {action} поездку"
        )

    except Exception as e:
        error_msg = f"Error in toggle_item_selection: {str(e)}"
        print(error_msg)
        if 'order_id' in locals():
            print(f"Order ID: {order_id}")
        if 'item_key' in locals():
            print(f"Item Key: {item_key}")
        if 'order' in locals():
            print(f"Order data: {order}")
        bot.answer_callback_query(call.id, "Ошибка при выборе товара")

@bot.callback_query_handler(func=lambda call: call.data.startswith('deselect_all_'), state=TripStates.selecting_orders)
def deselect_all_items(call: CallbackQuery, state: StateContext):
    """Обработчик отмены выбора всех товаров"""
    try:
        order_id = int(call.data.split('_')[2])

        # Удаляем все товары этого заказа из выбранных
        with state.data() as data:
            selected_items = data.get('selected_items', {})
            if str(order_id) in selected_items:
                del selected_items[str(order_id)]
        state.add_data(selected_items=selected_items)

        # Обновляем клавиатуру
        order = get_order_by_id(order_id,[OrderType.READY_TO_DELIVERY.value])
        if order:
            markup = get_order_items_keyboard(order_id, [], [], order['order_type'])
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
            bot.answer_callback_query(call.id, "Все товары убраны из поездки")
        else:
            bot.answer_callback_query(call.id, "Заказ не найден")

    except Exception as e:
        print(f"Error in deselect_all_items: {e}")
        bot.answer_callback_query(call.id, "Ошибка при отмене выбора товаров")


@bot.callback_query_handler(func=lambda call: call.data == 'back_to_orders')
def back_to_orders_list(call: CallbackQuery, state: StateContext):
    """Возврат к списку заказов"""
    try:
        # courier_info = get_user_info(call.message.json['chat']['username'])
        # Получаем все активные заказы

        with state.data() as data:
            avito_message_id = data.get('avito_message_id')
            avito_photos_messages = data.get('avito_photos_messages', [])
            selected_items = data.get('selected_items', {})
            message_to_edit = data.get('current_message_to_edit',{})

            # Удаляем сообщение с авито заказом
        # if avito_message_id:
        #     bot.delete_message(call.message.chat.id, avito_message_id)

            # Удаляем все фотографии
        for photo_message_id in avito_photos_messages:
            try:
                bot.delete_message(call.message.chat.id, photo_message_id)
            except Exception as e:
                print(f"Error deleting photo message: {e}")
        orders = get_orders(
            order_type=['avito', 'delivery'],
            status=[OrderType.READY_TO_DELIVERY.value, OrderType.PARTLY_DELIVERED.value],
            role='courier',
            username=call.message.json['chat']['username'],
            item_status=[OrderType.READY_TO_DELIVERY.value]

        )


        # Создаем клавиатуру с учетом выбранных товаров
        markup = get_orders_keyboard(orders, selected_items)
        markup.add(types.InlineKeyboardButton("🔙 Вернуться в меню", callback_data="back_to_courier_menu"))

        new_message = bot.edit_message_text(
            "Выберите заказы для добавления товаров в поездку:",
            call.message.chat.id,
            message_to_edit,
            reply_markup=markup
        )


        # Очищаем состояния и сохраняем ID нового сообщения
        delete_multiple_states(state, [
            'selecting_delivered_items',
            'avito_photos_sent',
            'avito_order_shown',
            'avito_message_id',
            'current_order_id'
            'avito_photos_messages',
            'current_message_to_edit'
        ])
        state.add_data(orders_message_id=new_message.message_id)

    except Exception as e:
        bot.answer_callback_query(call.id, "Ошибка при возврате к списку заказов")
        print(f"Error in back_to_orders_list: {e}")


@bot.callback_query_handler(func=lambda call: call.data == "show_current_trip")
def show_current_trip(call: CallbackQuery, state: StateContext):
    """Показывает информацию о текущей поездке"""
    try:

        with state.data() as data:
            avito_photos_messages = data.get('avito_photos_messages', [])
            avito_message_id = data.get('avito_message_id')

            # Удаляем фотографии
        for photo_id in avito_photos_messages:
            try:
                bot.delete_message(call.message.chat.id, photo_id)
            except Exception as e:
                print(f"Error deleting photo: {e}")

            # Удаляем сообщение с информацией о заказе если оно есть
        if avito_message_id:
            try:
                bot.delete_message(call.message.chat.id, avito_message_id)
            except Exception as e:
                print(f"Error deleting message: {e}")

            # Очищаем состояния
        delete_multiple_states(state, [
            'avito_photos_messages',
            'avito_message_id',
            'current_order_id'
        ])

        courier_info = get_user_info(call.from_user.username)
        if not courier_info:
            bot.answer_callback_query(call.id, "Ошибка получения информации о курьере")
            return

        # Получаем активную поездку
        trip = trip_manager.get_courier_active_trips(courier_info['id'])
        if not trip:
            bot.edit_message_text(
                "У вас нет активных поездок.",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_courier_menu")
                )
            ) if not avito_message_id else (
                bot.send_message(call.message.chat.id,
                                 "У вас нет активных поездок.",
                                 reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_courier_menu"))
            ))

            return

        active_trip = trip[0]
        trip_items = trip_manager.get_trip_items(active_trip['id'])

        # Фильтруем items по статусам
        filtered_items = [
            item for item in trip_items
            if item['status'] in [OrderType.PARTLY_DELIVERED.value, OrderType.IN_DELIVERY.value]
        ]

        delivery_items = []
        for item in filtered_items:
            if item and item['order_type'] != 'avito':
                item['delivery_address'] = item.get('delivery_address')
                delivery_items.append(item)

        if not filtered_items:
            bot.edit_message_text(
                "Все заказы в поездке выполнены.",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_courier_menu")
                )
            ) if not avito_message_id else (
            bot.send_message(
                call.message.chat.id,
                "Все заказы в поездке выполнены.",
                reply_markup=types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_courier_menu")
                ))
            )
            return

        map_link = generate_map_link(delivery_items, WAREHOUSE_LOCATION)

        # Формируем сообщение
        trip_message = (
            "🚚 Текущая поездка\n\n"
            f"Курьер: {courier_info['name']} ({courier_info['username']})\n"
            f"Количество заказов: {len(set(item['order_id'] for item in filtered_items))}\n\n"
            "Если хотите отменить поездку(например, попросили перенести доставку), и доставить его в след. раз, нажмите ❌ Отменить поездку\n"
            "Все заказы можно будет доставить повторно\n"
            "Также у вас есть кнопка Проложить маршрут, она откроет Яндекс карты и отобразит, куда нужно доставить заказы (Только для заказов с типом ДОСТАВКА)"
            "Для АВИТО заказов смотрите в заказе, куда доставлять"
        )

        # Группируем товары по заказам
        orders_dict = {}
        for item in filtered_items:
            if item['order_id'] not in orders_dict:
                orders_dict[item['order_id']] = []
            orders_dict[item['order_id']].append(item)

        # Создаем кнопки заказов
        markup = types.InlineKeyboardMarkup(row_width=1)

        all_orders_completed = True
        for order_id, items in orders_dict.items():
            order = get_order_by_id(order_id)
            # Формируем адресную часть
            if order['order_type'] == 'avito':
                address_text = "Авито"
            else:
                address_parts = order.get('delivery_address', '').split(',')
                address_text = ', '.join(address_parts[1:]) if len(address_parts) > 1 else 'Адрес не указан'

            # Проверяем статусы товаров
            if any(item['status'] not in ['closed', 'partial_closed', 'refund'] for item in items):
                all_orders_completed = False

            markup.add(
                types.InlineKeyboardButton(
                    f"📦 Заказ #{str(order_id).zfill(4)}ㅤ- {address_text}",
                    callback_data=f"show_trip_order_{order_id}"
                )
            )

        state.add_data(current_trip_orders=orders_dict)

        markup.add(types.InlineKeyboardButton("❌ Отменить поездку", callback_data="cancel_trip"))

        if any(item.get('coordinates') for item in filtered_items):
            markup.add(types.InlineKeyboardButton(
                text="🗺️ Проложить маршрут",
                url=map_link
            ))

        markup.add(types.InlineKeyboardButton("🔙 Вернуться в меню", callback_data="back_to_courier_menu"))

        bot.edit_message_text(
            trip_message,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup,
            parse_mode='HTML'
        ) if not avito_message_id else (
            bot.send_message(
                call.message.chat.id,
                trip_message,
                reply_markup=markup,
                parse_mode='HTML'
            )
        )

    except Exception as e:
        print(f"Error in show_current_trip: {e}")
        bot.answer_callback_query(call.id, "Произошла ошибка при отображении поездки")

@bot.callback_query_handler(func=lambda call: call.data.startswith('show_trip_avito_order_'))
def show_trip_avito_order(call: CallbackQuery, state: StateContext, order_id):
    """Показывает детальную информацию о заказе Авито в поездке"""
    try:
        # order_id = int(call.data.split('_')[4])
        order = get_order_by_id(order_id, item_statuses=[OrderType.IN_DELIVERY.value])

        if not order:
            bot.answer_callback_query(call.id, "Заказ не найден")
            return

        # Проверяем, откуда пришел пользователь
        with state.data() as data:
            avito_photos_messages = data.get('avito_photos_messages', [])
            avito_message_id = data.get('avito_message_id')
            is_from_track = call.data.startswith('show_track_')

        # Если пришли из списка заказов, а не из трек-номера
        if not is_from_track:
            # Удаляем предыдущее сообщение
            bot.delete_message(call.message.chat.id, call.message.message_id)

            # Удаляем предыдущие фото если они есть
            for photo_id in avito_photos_messages:
                try:
                    bot.delete_message(call.message.chat.id, photo_id)
                except Exception as e:
                    print(f"Error deleting photo: {e}")

        # Получаем трек-номера для заказа
        track_numbers = {}
        for track_number, track_info in order['products'].items():
            if track_number != 'no_track':
                track_numbers[track_number] = track_info['products']

        # Отправляем фотографии
        avito_photos = []
        photos_message_ids = []
        for track_number in track_numbers.keys():
            photos = get_avito_photos(order_id)
            if photos:
                avito_photos.extend(photos)

        if avito_photos:
            media_group = create_media_group(avito_photos, None)
            sent_photos = bot.send_media_group(call.message.chat.id, media=media_group)
            photos_message_ids = [msg.message_id for msg in sent_photos]

        # Формируем сообщение
        message_text = [
            f"📦 Заказ #{str(order['id']).zfill(4)}ㅤ",
            f"Тип заказа - Авито",
            f"Менеджер - @{order.get('manager_username', 'Не указан')}",
            f"Заметка - {order.get('note', 'Нет')}",
            "Выберите нужный трекномер для взаимодействия с ним"
        ]

        for track_number, track_info in track_numbers.items():
            message_text.append(f"\n📬 Трек-номер: {track_number}")
            for product in track_info:
                message_text.append(f"  • {product.get('name', '')} - {product.get('param', '')}")

        # Создаем клавиатуру
        markup = types.InlineKeyboardMarkup(row_width=1)
        for track_number in track_numbers.keys():
            markup.add(
                types.InlineKeyboardButton(
                    f"📬 Трек-номер: {track_number}",
                    callback_data=f"show_track_{order_id}_{track_number}"
                )
            )
        markup.add(types.InlineKeyboardButton("🔙 Назад к поездке", callback_data="show_current_trip"))

        # Отправляем новое сообщение
        new_message = bot.send_message(
            call.message.chat.id,
            '\n'.join(message_text),
            reply_markup=markup
        )

        # Сохраняем информацию в state
        state.add_data(
            avito_photos_messages= photos_message_ids,
            avito_message_id= new_message.message_id,
            current_order_id= order_id
        )

    except Exception as e:
        print(f"Error in show_trip_avito_order: {e}")
        bot.answer_callback_query(call.id, "Произошла ошибка при отображении заказа")

@bot.callback_query_handler(func=lambda call: call.data.startswith('show_track_'))
def show_track_details(call: CallbackQuery, state: StateContext):
    """Показывает детали конкретного трек-номера"""
    try:
        _,_, order_id, track_number = call.data.split('_')
        order_id = int(order_id)

        # Получаем информацию о заказе и трек-номере
        order = get_order_by_id(order_id, item_statuses=[OrderType.IN_DELIVERY.value])
        if not order:
            bot.answer_callback_query(call.id, "Заказ не найден")
            return

        track_info = order['products'].get(track_number, {})
        if not track_info:
            bot.answer_callback_query(call.id, "Трек-номер не найден")
            return

        # Формируем сообщение
        message_text = [
            f"📦 Заказ #{str(order_id).zfill(4)}ㅤ",
            f"📬 Трек-номер: {track_number}",
            f"Менеджер: @{order.get('manager_username', 'Не указан')}",
            f"Количество мешков: {order.get('avito_boxes', 0)}",
            "Если вы доставили трекномер, нажмите Далее\n"
            "Если пришла отмена, нажмите Отменить\nОбратите внимание, данный трекномер повторно нельзя будет доставить, товары из него пополнят склад\n"
            "\nТовары в треке:"
        ]

        for product in track_info.get('products', []):
            message_text.append(f"• {product.get('name', '')} - {product.get('param', '')}")

        # Создаем клавиатуру
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("✅ Далее", callback_data=f"complete_avito_track_{order_id}_{track_number}"),
            types.InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_avito_track_{order_id}_{track_number}"),
            types.InlineKeyboardButton("🔙 Назад", callback_data=f"show_trip_order_{order_id}")
        )

        # Обновляем сообщение
        bot.edit_message_text(
            '\n'.join(message_text),
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

    except Exception as e:
        print(f"Error in show_track_details: {e}")
        bot.answer_callback_query(call.id, "Произошла ошибка при отображении трек-номера")

@bot.callback_query_handler(func=lambda call: call.data.startswith('show_trip_order_'))
def show_trip_order(call: CallbackQuery, state: StateContext):
    """Показывает детальную информацию о заказе в поездке"""
    try:
        order_id = int(call.data.split('_')[3])
        order = get_order_by_id(order_id,item_statuses=[OrderType.IN_DELIVERY.value])

        if not order:
            bot.answer_callback_query(call.id, "Заказ не найден")
            return

        if order['order_type'] == 'avito':
            show_trip_avito_order(call, state, order_id)
            return

        # Формируем сообщение с информацией о заказе
        message_text = (
            f"📦 Заказ #{str(order_id).zfill(4)}ㅤ\n"
            f"📍 Адрес: {order.get('delivery_address', 'Не указан')}\n"
            f"📱 Контакт: {order.get('contact_name', 'Не указан')}\n"
            f"☎️ Телефон: {order.get('contact_phone', 'Не указан')}\n"
            f"🕒 Время: {order.get('delivery_time', 'Не указано')}\n"
            f"📅 Дата: {order.get('delivery_date', 'Не указана')}\n\n"
            "Если вам пришла отмена по какому-то товару, просто не выбирайте его.\nОбратите внимание, данный товар нельзя будет повторно доставить, он отмеяется и едет на склад\n\n"
            
            "Выберите доставленные товары:\n"

        )

        # Получаем товары заказа в поездке
        trip_items = trip_manager.get_trip_items_for_order(order_id,order_item_status=[OrderType.IN_DELIVERY.value],trip_status=['pending'], courier_trip_status=['created'])

        # Создаем клавиатуру с товарами
        markup = types.InlineKeyboardMarkup(row_width=1)

        # Получаем ранее выбранные товары из состояния
        with state.data() as data:
            delivered_items = data.get('delivered_items', {}).get(str(order_id), [])

        for item in trip_items:
            prefix = "✅" if item['id'] in delivered_items else "⬜️"
            markup.add(
                types.InlineKeyboardButton(
                    f"{prefix} {item['product_name']} - {item.get('param_title', '')}",
                    callback_data=f"toggle_delivered_{order_id}_{item['id']}"
                )
            )

        # Добавляем управляющие кнопки
        markup.add(
            # types.InlineKeyboardButton("✅ Подтвердить все", callback_data=f"deliver_all_{order_id}"),
            types.InlineKeyboardButton("➡️ Далее", callback_data=f"proceed_delivery_{order_id}"),
            types.InlineKeyboardButton("🔙 Назад к поездке", callback_data="show_current_trip")
        )

        bot.edit_message_text(
            message_text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

        state.set(CourierStates.selecting_delivered_items)

    except Exception as e:
        print(f"Error in show_trip_order: {e}")
        bot.answer_callback_query(call.id, "Произошла ошибка при отображении заказа")


@bot.callback_query_handler(func=lambda call: call.data == "confirm_orders")
def confirm_orders_selection(call: CallbackQuery, state: StateContext):
    """Подтверждение выбранных заказов"""
    try:
        with state.data() as data:
            selected_items = data.get('selected_items', {})

        if not selected_items:
            bot.answer_callback_query(call.id, "Выберите хотя бы один товар")
            return

        # Получаем информацию о курьере
        courier_info = get_user_info(call.from_user.username)
        if not courier_info:
            bot.answer_callback_query(call.id, "Ошибка получения информации о курьере")
            return

        # Определяем самую дальнюю зону из выбранных заказов
        orders_info = []
        # furthest_zone_id = None
        # furthest_zone_price = 0
        #
        # for order_id in selected_items:
        #     order = get_order_by_id(order_id)
        #     if order:
        #         orders_info.append(order)
        #
        #         # Определяем зону доставки только для заказов с типом 'delivery'
        #         if order['order_type'] == 'delivery':
        #             delivery_address = order['delivery_address']
        #             coordinates = zone_manager.geocode_address(delivery_address)
        #             if coordinates:
        #                 zone = zone_manager.get_zone_by_coordinates(*coordinates)
        #                 if zone and zone.base_price > furthest_zone_price:
        #                     furthest_zone_id = zone.id
        #                     furthest_zone_price = zone.base_price
        orders_info = []
        delivery_orders_exist = False

        for order_id in selected_items:
            order = get_order_by_id(order_id)
            if order:
                order_info = {'id': order['id'], 'type': order['order_type']}
                if order['order_type'] == 'delivery':
                    delivery_orders_exist = True
                    delivery_address = order['delivery_address']
                    coordinates = zone_manager.geocode_address(delivery_address)
                    if coordinates:
                        zone = zone_manager.get_zone_by_coordinates(*coordinates)
                        if zone:
                            order_info['zone'] = zone
                orders_info.append(order_info)

        # if not furthest_zone_id:
        #     # Если нет заказов с доставкой, используем первую зону
        #     default_zone = zone_manager.get_all_zones()[0]
        #     furthest_zone_id = default_zone.id

        # Создаем поездку
        # print(furthest_zone_id,'zone')
        delivery_cost={}
        if delivery_orders_exist:
            delivery_cost = cost_calculator.calculate_for_trip(orders_info, selected_items)
            total_price = delivery_cost.total_price
            zone_id = delivery_cost.zone_id
        else:
            # Для поездки только с Авито заказами
            #TODO dodelat
            total_price = cost_calculator.calculate_for_trip(orders_info, selected_items).total_price
            zone_id = None
        trip_id = trip_manager.create_trip(courier_info['id'], zone_id, total_price)
        if not trip_id:
            bot.answer_callback_query(call.id, "Ошибка создания поездки")
            return

            # Добавляем товары в поездку
        for order_id, item_keys in selected_items.items():
            order = get_order_by_id(int(order_id))
            if order['order_type'] == 'avito':
                # Для Авито обрабатываем трек-номера
                for item_key in item_keys:
                    track_number = item_key.split('|')[0]
                    track_info = order['products'].get(track_number, {})
                    if track_info and 'products' in track_info:
                        for product in track_info['products']:
                            success = trip_manager.add_item_to_trip(
                                trip_id['id'],
                                int(order_id),
                                f"{product.get('order_item_id')}|{product.get('product_id')}|{product.get('param_id')}"
                            )
                            if not success:
                                print(f"Failed to add item from track {track_number} to trip {trip_id}")
            else:
                # Существующая логика для обычных заказов
                for item_key in item_keys:
                    success = trip_manager.add_item_to_trip(
                        trip_id['id'],
                        int(order_id),
                        item_key
                    )
                    if not success:
                        print(f"Failed to add item {item_key} from order {order_id} to trip {trip_id}")
        # Обновляем статусы заказов и товаров
        # for order_id in selected_items:
        #
        #     order = get_order_by_id(order_id)
            # if order:
            #     if len(selected_items[order_id]) == len(order['products']):
            #         # Если выбраны все товары заказа, обновляем статус заказа на 'in_delivery'
            #         update_order_status(order_id, OrderType.IN_DELIVERY.value)
            #     else:
            #         # Если выбрана только часть товаров, обновляем статус заказа на 'partly_delivered'
            #         update_order_status(order_id, OrderType.PARTLY_DELIVERED.value)
            #
            #     # Обновляем статусы выбранных товаров на 'in_delivery'
            #     for item_key in selected_items[order_id]:
            #         product_id, param_id, idx = item_key.split('|')
            #         # update_order_item_status(order_id, product_id, param_id, OrderType.IN_DELIVERY.value)
        for order_id in selected_items:
            order = get_order_by_id(int(order_id))
            if order:
                if order['order_type'] == 'avito':
                    selected_tracks = [key.split('|')[0] for key in selected_items[order_id]]
                    total_tracks = len([k for k in order['products'].keys() if k != 'no_track'])
                    if len(selected_tracks) == total_tracks:
                        update_order_status(order_id, OrderType.IN_DELIVERY.value)
                    else:
                        update_order_status(order_id, OrderType.PARTLY_DELIVERED.value, with_order_items = False)
                        for item_key in selected_items[order_id]:
                            _, _ ,order_item_ids = item_key.split('|')
                            # Обновляем статус для каждого order_item_id
                            order_item_ids = order_item_ids.split(',')
                            for order_item_id in order_item_ids:
                                update_order_item_status(int(order_item_id), OrderType.IN_DELIVERY.value)
                else:
                    if len(selected_items[order_id]) == len(order['products']['no_track']):
                        # Если выбраны все товары заказа
                            update_order_status(order_id, OrderType.IN_DELIVERY.value, )
                    else:
                        # Если выбрана только часть товаров
                        update_order_status(order_id, OrderType.PARTLY_DELIVERED.value, with_order_items = False)
                        for item_key in selected_items[order_id]:
                            order_item_id, product_id, param_id= item_key.split('|')
                            update_order_item_status(order_item_id, OrderType.IN_DELIVERY.value)
        # Рассчитываем стоимость доставки

        # Формируем сообщение о созданной поездке
        trip_message = (
            f"🚚 Создана новая поездка\n\n"
            f"Курьер: {courier_info['name']} ({courier_info['username']})\n"
            f"Количество заказов: {len(selected_items)}\n"
            # f"Стоимость доставки: {delivery_cost.total_price} руб.\n\n"
            f"Заказы в поездке:\n"
        )

        # Добавляем информацию о заказах и выбранных товарах
        for order in orders_info:
            trip_message += f"\n📦 Заказ #{order['id']}"
            if order.get('delivery_address'):
                trip_message += f"\n📍 Адрес: {order['delivery_address']}"

            # Добавляем выбранные товары для этого заказа
            if str(order['id']) in selected_items:
                trip_message += "\n🛍️ Выбранные товары:"
                order_data = get_order_by_id(order['id'])
                for item_key in selected_items[str(order['id'])]:
                    if order_data['order_type'] == 'delivery':
                        # Для заказов с доставкой
                        order_item_id, product_id, param_id = item_key.split('|')
                        products = order_data['products'].get('no_track', {}).get('products', [])
                        for product in products:
                            if str(product.get('product_id')) == product_id and str(
                                    product.get('param_id')) == param_id:
                                trip_message += f"\n  • {product.get('name', 'Неизвестный товар')} - {product.get('param', '')}"
                                break
                    else:
                        # Для заказов Авито
                        track_number, order_id,_ = item_key.split('|')
                        track_info = order_data['products'].get(track_number, {})
                        if track_info and 'products' in track_info:
                            trip_message += f"\n  📬 Трек-номер: {track_number}"
                            for product in track_info['products']:
                                trip_message += f"\n    • {product.get('name', 'Неизвестный товар')} - {product.get('param', '')}"

            trip_message += "\n"
        # Получаем ссылку на карты


        # Добавляем инструкцию для курьера
        trip_message += "\n\n💡 Чтобы перейти в текущую поездку, нажмите кнопку \"Текущая поездка\" в главном меню или нажмите кнопку ниже"
        markup = types.InlineKeyboardMarkup()
        markup.add( types.InlineKeyboardButton("🚚 Текущая поездка", callback_data="show_current_trip"))
        markup.add(
                types.InlineKeyboardButton("🔙 Вернуться в меню", callback_data="back_to_courier_menu"))
        # Отправляем сообщение о создании поездки без кнопок управления поездкой
        bot.edit_message_text(
            trip_message,
            call.message.chat.id,
            call.message.message_id,
            parse_mode='HTML',
            disable_web_page_preview=True,
            reply_markup=markup
            )


        # Обновляем состояние
        state.set(TripStates.trip_in_progress)
        state.add_data(
            trip_id=trip_id,
            orders_info=orders_info,
            delivery_cost=delivery_cost
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
        state.add_data(cancelled_items=cancelled_items)

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
def parse_item_key(item_key):
    """Разбирает ключ товара на product_id и индекс"""
    order_item_id, product_id,param_id = item_key.split('|')
    return int(order_item_id), int(product_id), int(param_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith('toggle_delivered_'))
def toggle_delivered_item(call: CallbackQuery, state: StateContext):
    """Обработчик выбора/отмены выбора доставленного товара"""
    try:
        # Разбираем callback_data
        _, order_id, item_id = call.data.split('_')[1:]
        order_id = str(order_id)
        item_id = int(item_id)

        # Получаем/обновляем список доставленных товаров
        with state.data() as data:
            delivered_items = data.get('delivered_items', {})
            if order_id not in delivered_items:
                delivered_items[order_id] = []

            # Переключаем статус товара
            if item_id in delivered_items[order_id]:
                delivered_items[order_id].remove(item_id)
                action = "удален из"
            else:
                delivered_items[order_id].append(item_id)
                action = "добавлен в"

            # data['delivered_items'] = delivered_items
        state.add_data(delivered_items=delivered_items)
        # Обновляем отображение заказа
        order = get_order_by_id(int(order_id),item_statuses=[OrderType.IN_DELIVERY.value])
        trip_items = trip_manager.get_trip_items_for_order(order_id, order_item_status=[OrderType.IN_DELIVERY.value],
                                                           trip_status=['pending'], courier_trip_status=['created'])

        message_text = (
            f"📦 Заказ #{order_id.zfill(4)}ㅤ\n"
            f"📍 Адрес: {order.get('delivery_address', 'Не указан')}\n"
            f"📱 Контакт: {order.get('contact_name', 'Не указан')}\n"
            f"☎️ Телефон: {order.get('contact_phone', 'Не указан')}\n"
            f"🕒 Время: {order.get('delivery_time', 'Не указано')}\n"
            f"📅 Дата: {order.get('delivery_date', 'Не указана')}\n\n"
            "Если вам пришла отмена по какому-то товару, просто не выбирайте его.\nОбратите внимание, данный товар нельзя будет повторно доставить, он отмеяется и едет на склад\n\n"
            
            "Выберите доставленные товары:\n"
        )

        markup = types.InlineKeyboardMarkup(row_width=1)
        for item in trip_items:
            prefix = "✅" if item['id'] in delivered_items[order_id] else "⬜️"
            markup.add(
                types.InlineKeyboardButton(
                    f"{prefix} {item['product_name']} - {item.get('param_title', '')}",
                    callback_data=f"toggle_delivered_{order_id}_{item['id']}"
                )
            )

        markup.add(
            # types.InlineKeyboardButton("✅ Подтвердить все", callback_data=f"deliver_all_{order_id}"),
            types.InlineKeyboardButton("➡️ Далее", callback_data=f"proceed_delivery_{order_id}"),
            types.InlineKeyboardButton("🔙 Назад к поездке", callback_data="show_current_trip")
        )

        bot.edit_message_text(
            message_text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

        bot.answer_callback_query(call.id, f"Товар {action} список доставленных")

    except Exception as e:
        print(f"Error in toggle_delivered_item: {e}")
        bot.answer_callback_query(call.id, "Произошла ошибка при выборе товара")


@bot.callback_query_handler(func=lambda call: call.data.startswith('deliver_all_'))
def deliver_all_items(call: CallbackQuery, state: StateContext):
    """Обработчик выбора всех товаров как доставленных"""
    try:
        order_id = str(call.data.split('_')[2])

        # Получаем все товары заказа
        trip_items = trip_manager.get_trip_items_for_order(int(order_id))

        # Отмечаем все товары как доставленные
        with state.data() as data:
            delivered_items = data.get('delivered_items', {})
            delivered_items[order_id] = [item['id'] for item in trip_items]
        # data['delivered_items'] = delivered_items
        state.add_data(delivered_items=delivered_items)
        # Переходим к вводу суммы доставки
        proceed_with_delivery(call.message, order_id, state)

    except Exception as e:
        print(f"Error in deliver_all_items: {e}")
        bot.answer_callback_query(call.id, "Произошла ошибка при выборе всех товаров")


@bot.callback_query_handler(func=lambda call: call.data.startswith('proceed_delivery_'))
def proceed_with_delivery(call: CallbackQuery, state: StateContext):
    """Обработчик перехода к вводу суммы доставки"""
    try:
        order_id = str(call.data.split('_')[2])

        with state.data() as data:
            delivered_items = data.get('delivered_items', {}).get(order_id, [])

            data['current_order_id'] = order_id

        bot.edit_message_text(
            "Введите сумму доставки(сколько перевели):",
            call.message.chat.id,
            call.message.message_id
        )

        state.set(CourierStates.entering_delivery_sum)

    except Exception as e:
        print(f"Error in proceed_with_delivery: {e}")
        bot.answer_callback_query(call.id, "Произошла ошибка при переходе к вводу суммы")


@bot.message_handler(state=CourierStates.entering_delivery_sum)
def handle_delivery_sum(message: Message, state: StateContext):
    """Обработчик ввода суммы доставки"""
    if not is_valid_command(message.text, state): return
    try:
        delivery_sum = float(message.text)

        # with state.data() as data:
        #     order_id = data.get('current_order_id')
        # data['delivery_sum'] = delivery_sum
        state.add_data(delivery_sum=delivery_sum)

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Пропустить", callback_data="skip"))

        bot.send_message(
            message.chat.id,
            "Введите заметку к доставке(н-р, куда перевели):",
            reply_markup=markup
        )

        state.set(CourierStates.entering_delivery_note)

    except ValueError:
        bot.reply_to(message, "Пожалуйста, введите корректную сумму числом")
    except Exception as e:
        print(f"Error in handle_delivery_sum: {e}")
        bot.reply_to(message, "Произошла ошибка при сохранении суммы")

@bot.callback_query_handler(state=CourierStates.entering_delivery_note, func=lambda call: call.data == 'skip')
def skip_delivery_note(call: CallbackQuery, state: StateContext):
    """Обработчик пропуска заметки"""
    if not is_valid_command(call.message.text, state): return

    process_delivery_completion(call.message.json['chat']['username'],call.message.chat.id, None, state)
    bot.delete_message(call.message.chat.id, call.message.message_id)

@bot.message_handler(state=CourierStates.entering_delivery_note)
def handle_delivery_note(message: Message, state: StateContext):
    """Обработчик ввода заметки"""
    if not is_valid_command(message.text, state): return
    delivery_note = message.text.strip()
    process_delivery_completion(message.from_user.username,message.chat.id, delivery_note, state)


def process_delivery_completion(username: str, chat_id: int, delivery_note: str | None, state: StateContext):
    """Общая логика завершения доставки"""
    try:
        with state.data() as data:
            order_id = data.get('current_order_id')
            delivery_sum = data.get('delivery_sum')
            delivered_items = data.get('delivered_items', {}).get(order_id, [])

        # Обновляем статусы заказа и товары
        order = get_order_by_id(int(order_id))

        # Обновляем сумму доставки
        current_delivery_sum = order.get('delivery_sum', 0)
        update_order_delivery_sum(int(order_id), current_delivery_sum + delivery_sum)

        # Обновляем заметку если она есть
        if delivery_note:
            update_order_delivery_note(int(order_id), delivery_note)

        # Обновляем статусы товаров и trip_items
        all_items = trip_manager.get_trip_items_for_order(int(order_id), trip_status=['pending'], courier_trip_status=['created'])
        delivered_products = []
        returned_products = []
        deliver_or_returned_ids = []


        for item in all_items:
            if item['id'] in delivered_items:
                # Обновляем статус товара в order_items
                update_order_item_status(item['order_item_id'], OrderType.CLOSED.value)
                # Обновляем статус и время доставки в trip_items
                # with get_connection() as conn:
                #     with conn.cursor() as cursor:
                #         cursor.execute("""
                #             UPDATE trip_items
                #             SET status = 'delivered', delivered_at = %s
                #             WHERE order_item_id = %s
                #         """, (current_time, item['order_item_id']))
                update_trip_item('delivered',item['order_item_id'])
                delivered_products.append(f"• {item['product_name']} - {item.get('param_title', '')}")
            else:
                # Обновляем статус товара в order_items
                update_order_item_status(item['order_item_id'], OrderType.REFUND.value)
                # Обновляем статус в trip_items на refunded
                update_trip_item('refunded', item['order_item_id'])
                # Увеличиваем сток для возвращенного товара
                increment_stock(item['product_param_id'])
                returned_products.append(f"• {item['product_name']} - {item.get('param_title', '')}")
            deliver_or_returned_ids.append(item['order_item_id'])


        # Проверяем, остались ли необработанные товары
        remaining_items_for_order = trip_manager.get_items_for_order_in_ride(int(order_id), status=OrderType.READY_TO_DELIVERY.value)
        if not remaining_items_for_order:
            update_order_status(int(order_id), OrderType.CLOSED.value, with_order_items=False)
        else:
            update_order_status(int(order_id), OrderType.PARTLY_DELIVERED.value, with_order_items=False)

        # Формируем сообщение о доставке
        courier_info = get_user_by_username(username, state)
        delivery_message = (
            f"📦 Заказ #{str(order_id).zfill(4)}ㅤ\n"
            f"📍 Адрес: {order.get('delivery_address', 'Не указан')}\n\n"
            f" Сумма доставки: {delivery_sum}\n"
            f" Заметка от курьера: {delivery_note}\n\n"
        )

        if delivered_products:
            delivery_message += "✅ Доставленные товары:\n" + "\n".join(delivered_products) + "\n\n"

        if returned_products:
            delivery_message += "↩️ Возврат:\n" + "\n".join(returned_products) + "\n\n"

        delivery_message += f"🚚 Курьер: {courier_info['name']} ({courier_info['username']})"

        # Проверяем остались ли активные заказы в поездке
        active_trip = trip_manager.get_courier_active_trips(courier_info['id'])[0]

        # Фильтруем items по статусам
        remaining_trip_items = trip_manager.get_trip_items(active_trip['id'])

        markup = types.InlineKeyboardMarkup()

        if not remaining_trip_items:
            # Если активных заказов больше нет, завершаем поездку
            trip_manager.update_trip_status(active_trip['id'], 'completed')
            delivery_message += "\n\n✅ Поездка завершена"
            markup.add(types.InlineKeyboardButton("Вернуться в меню", callback_data='back_to_courier_menu'))
        else:
            markup.add(types.InlineKeyboardButton("Текущая поездка", callback_data=f"show_current_trip"))
            markup.add(types.InlineKeyboardButton("Вернуться в меню", callback_data='back_to_courier_menu'))

        # Отправляем сообщение
        bot.send_message(chat_id, delivery_message,reply_markup=markup)
        bot.send_message(
            CHANNEL_CHAT_ID,
            delivery_message,
            reply_to_message_id=order.get('message_id'),
        )

        # Очищаем состояния
        delete_multiple_states(state, ['delivered_items', 'current_order_id', 'delivery_sum'])

    except Exception as e:
        print(f"Error in process_delivery_completion: {e}")
        bot.send_message(chat_id, "Произошла ошибка при обработке доставки")


@bot.callback_query_handler(func=lambda call: call.data == "close_trip")
def close_trip(call: CallbackQuery, state: StateContext):
    """Обработчик закрытия поездки"""
    try:
        courier_info = get_user_info(call.from_user.username)
        trip = trip_manager.get_courier_active_trips(courier_info['id'])[0]

        # Проверяем, все ли заказы завершены
        trip_items = trip_manager.get_trip_items(trip['id'])
        all_completed = all(
            item['status'] in [OrderType.CLOSED.value, OrderType.PARTIALLY_CLOSED.value, OrderType.REFUND.value]
            for item in trip_items)

        if not all_completed:
            bot.answer_callback_query(call.id, "Нельзя закрыть поездку, пока есть незавершенные заказы")
            return

        # Закрываем поездку
        trip_manager.update_trip_status(trip['id'], 'completed')

        bot.edit_message_text(
            "✅ Поездка успешно завершена",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("🔙 Вернуться в меню", callback_data="back_to_courier_menu")
            )
        )

    except Exception as e:
        print(f"Error in close_trip: {e}")
        bot.answer_callback_query(call.id, "Произошла ошибка при закрытии поездки")


@bot.callback_query_handler(func=lambda call: call.data == "cancel_trip")
def cancel_trip(call: CallbackQuery, state: StateContext):
    """Обработчик отмены поездки"""
    try:
        courier_info = get_user_info(call.from_user.username)
        trip = trip_manager.get_courier_active_trips(courier_info['id'])[0]

        # Получаем все товары из поездки
        all_trip_items = trip_manager.get_trip_items(trip['id'])

        # Фильтруем только pending товары
        pending_items = [item for item in all_trip_items if item['trip_item_status'] == 'pending']

        # Собираем уникальные order_id из pending товаров
        order_ids = set(item['order_id'] for item in pending_items)

        # Отменяем поездку
        trip_manager.update_trip_status(trip['id'], 'cancelled')

        # Обрабатываем каждый заказ
        for order_id in order_ids:
            # Получаем все товары данного заказа из поездки
            order_items = [item for item in all_trip_items if item['order_id'] == order_id]

            # Проверяем, есть ли доставленные товары в заказе
            has_delivered = any(item['trip_item_status'] != 'pending' for item in order_items)

            # Если есть доставленные товары, меняем статус заказа на partly_delivered
            if has_delivered:
                update_order_status(order_id, OrderType.PARTLY_DELIVERED.value,with_order_items=False)
            else:
                update_order_status(order_id, OrderType.READY_TO_DELIVERY.value, with_order_items=False)

        # Возвращаем все pending товары в статус ready_to_delivery
        for item in pending_items:
            update_order_item_status(item['order_item_id'], OrderType.READY_TO_DELIVERY.value)

        bot.edit_message_text(
            "❌ Поездка отменена, товары вновь готовы к отправке",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("🔙 Вернуться в меню", callback_data="back_to_courier_menu")
            )
        )
        delete_multiple_states(state, ['delivered_items', 'current_order_id', 'delivery_sum'])


    except Exception as e:
        print(f"Error in cancel_trip: {e}")
        bot.answer_callback_query(call.id, "Произошла ошибка при отмене поездки")
