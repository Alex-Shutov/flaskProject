from datetime import datetime

from telebot import types
from PIL import Image

from app_types import SaleType
from bot import get_bot_instance
from app_types import OrderType, OrderTypeRu
from database import get_product_info
import os
import io
import re
from io import BytesIO
from telebot.types import InputMediaPhoto
from urllib.parse import quote
from typing import List, Dict, Optional

from app_types import SaleTypeRu,UserRole


def get_available_buttons(roles):
    buttons = []
    if UserRole.MANAGER.value in roles or UserRole.ADMIN.value in roles or UserRole.OWNER.value in roles:
        buttons.append(types.KeyboardButton("#Продажа"))
    if UserRole.COURIER.value in roles or UserRole.ADMIN.value in roles or UserRole.OWNER.value  in roles :
        buttons.append(types.KeyboardButton("#Доставка"))
    buttons.append(types.KeyboardButton("#Заказы"))
    return buttons

def escape_markdown_v2(text):
    """Экранирует специальные символы для MarkdownV2."""
    return re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', text)


def format_order_message(order_id, product_list, gift, note, sale_type,
                         manager_name, manager_username, delivery_date=None,  show_item_status=False,
                         delivery_time=None, delivery_address=None, delivery_note=None,zone_name=None,
                         contact_phone=None, contact_name=None, total_price=None, avito_boxes=None,hide_track_prices=False,
                         packer_name=None, packer_username=None,):
    """
    Форматирует сообщение о заказе с учетом типа продажи

    Args:
        order_id: ID заказа
        product_list: Список продуктов (для Avito - словарь с трек-номерами)
        gift: Подарок
        note: Заметка
        sale_type: Тип продажи
        manager_name: Имя менеджера
        manager_username: Username менеджера
        delivery_date: Дата доставки (для доставки)
        delivery_time: Время доставки (для доставки)
        delivery_address: Адрес доставки (для доставки)
        zone_name: Зона доставки (для доставки)
        delivery_note: Заметка для доставки
        contact_phone: Контактный телефон (для доставки)
        contact_name: Имя контакта (для доставки)
        total_price: Общая сумма
        avito_boxes: Количество мешков для Avito
    """
    formatted_order_id = str(order_id).zfill(4)
    print(formatted_order_id)
    # Формируем базовую структуру сообщения
    print(sale_type.upper())

    order_parts = [
        f"📋 Заказ #{formatted_order_id}ㅤ\n",
        f"🏷️ Тип продажи: {SaleTypeRu[sale_type.upper()].value}",
        ""
    ]
    # Добавляем информацию о продуктах в зависимости от типа продажи
    if sale_type == SaleType.AVITO.value:
        for track_number, track_info in product_list.items():
            if hide_track_prices:
                order_parts.append(f"🔹 Трек-номер: {track_number}")
            else:
                track_price = track_info.get('price', 0)
                order_parts.append(f"🔹 Трек-номер: {track_number} - {track_price} руб.")

            for product in track_info['products']:
                emoji = "📦" if product.get('is_main_product') else "➕"
                product_line = f"  {emoji} {product['name']} - {product['param']}"

                if show_item_status:
                    status = product.get('status', 'pending')
                    status_emoji = {
                        'pending': '⏳Ожидает',
                        'delivered': '✅ Доставлен',
                        'cancelled': '❌ Отменен',
                        'refunded': '🔄 Возвращен'
                    }.get(status, '⏳ Ожидает')
                    product_line += f" {status_emoji}"

                order_parts.append(product_line)
            order_parts.append("")  # Пустая строка между трек-номерами

        order_parts.append(f"\n")
        if total_price is not None:
            order_parts.append(f"💰 Общая сумма: {total_price} руб.\n")
        order_parts.append(f"🛍️ Количество мешков: {avito_boxes}")

    else:
        # Для прямых продаж и доставки
        for product in product_list:
            emoji = "📦" if product['is_main_product'] else "➕"
            # product_line = f"{emoji} {product['product_name']} {product['param_title']}"
            product_line = f"{emoji} {product.get('product_name',product.get('name'))} {product.get('param_title',product.get('param'))}"

            if show_item_status:
                status = product.get('status', 'pending')
                status_emoji = {
                    'pending': '⏳Ожидает',
                    'delivered': '✅ Доставлен',
                    'cancelled': '❌ Отменен',
                    'refunded': '🔄 Возвращен'
                }.get(status, '⏳ Ожидает')
                product_line += f" {status_emoji}"

            order_parts.append(product_line)
        order_parts.append(f"\n")
        if total_price:
            order_parts.append(f"💰 Сумма: {total_price} руб.\n")

    # Добавляем подарок, если есть
    if gift:
        order_parts.append(f"🎁 Подарок: {gift}")

    # Добавляем информацию о доставке


    # Добавляем заметку, если есть
    if note:
        order_parts.append(f"📝 Заметка: {note}\n")

    if sale_type == SaleType.DELIVERY.value:
        delivery_parts = [
            f"📅 Дата доставки: {delivery_date}\n",
            f"⏰ Время доставки: {delivery_time}\n",
            f"📍 Адрес доставки: {delivery_address}\n",
            f"🗺️ Зона доставки: {zone_name}\n",
            f"👤 Получатель: {contact_name}\n",
            f"📞 Телефон: {contact_phone}\n"
        ]
        order_parts.extend(delivery_parts)

    # Добавляем информацию о менеджере
    order_parts.append(f"🧑‍💻 Менеджер: {manager_name} ({manager_username})\n")
    order_parts.append(f"🧑‍💻 Упаковщик: {manager_name} ({manager_username})\n") if packer_name and packer_username else ''

    # Собираем все части сообщения, фильтруя пустые строки
    return '\n'.join(filter(None, order_parts))


def save_photo_and_resize(photo, order_id):
    directory = "avito_photos/"
    if not os.path.exists(directory):
        os.makedirs(directory)

    photo_path = f"{directory}{order_id}_avito.png"

    image = Image.open(io.BytesIO(photo))
    image.save(photo_path, optimize=True, quality=85)  # Сжимаем фото

    return photo_path


def utf16_offset_length(text, substring):
    """
    Возвращает offset и length для подстроки в строке text, используя UTF-16 кодовые единицы.
    """
    utf16_text = text.encode('utf-16-le')  # Кодируем текст в UTF-16 (LE)
    utf16_substring = substring.encode('utf-16-le')  # Кодируем подстроку в UTF-16 (LE)

    # Находим байтовый offset подстроки
    byte_offset = utf16_text.find(utf16_substring)

    if byte_offset == -1:
        raise ValueError(f"Подстрока '{substring}' не найдена в строке '{text}'")

    # UTF-16 кодовые единицы делятся на 2 байта, поэтому делим на 2 для получения offset в кодовых единицах
    utf16_offset = byte_offset // 2
    utf16_length = len(utf16_substring) // 2

    return utf16_offset, utf16_length


def format_order_message_for_courier(order):
    order_id = order.get('id')
    product_id = order.get('product_id')
    product_param_id = order.get('product_param_id')
    gift = order.get('gift', 'Не указано')
    note = order.get('note', 'Нет примечаний')
    order_type = order.get('order_type')
    status = order.get('status')
    delivery_date = order.get('delivery_date')
    delivery_time = order.get('delivery_time')
    delivery_address = order.get('delivery_address')
    delivery_note = order.get('delivery_note')
    contact_phone = order.get('contact_phone')
    contact_name = order.get('contact_name')
    total_price = order.get('total_price')

    product_name, product_param = get_product_info(product_id, product_param_id)
    formatted_order_id = str(order_id).zfill(4)

    message = (
        f"🆔 Заказ: #{formatted_order_id}ㅤ\n\n"
        f"📦 {product_name} {product_param}\n\n"
        f"🎁 Подарок: {gift}\n"
    )

    if note:
        message += f"📝 Примечание: {note}\n\n"

    message += (
        f"🔄 Тип продажи: {SaleTypeRu[order_type.upper()].value}\n\n"
        f"📊 Статус: {OrderTypeRu[status.upper()].value}\n"
    )

    if order_type == 'delivery':
        message += (
            f"🚚 Доставка: {delivery_date or 'Не указана'} {delivery_time or ''}\n"
            f"📍 Адрес: {delivery_address or 'Не указан'}\n"
            f"📞 Телефон: {contact_phone or 'Не указан'} ({contact_name or 'Не указано'})\n"
            f"💰 Сумма: {total_price or 'Не указана'}\n"
        )
        if delivery_note:
            message += f"📝 Заметка к доставке: {delivery_note}\n"

    elif 'avito_photo' in order and order['avito_photo']:
        message += "📷 Фото: прикреплено\n"

    return message


def extract_order_number(caption):
    # Ищем паттерн, который соответствует символу '#' и цифрам сразу после него
    match = re.search(r"#(\d+)", caption)
    if match:
        # Преобразуем строку в целое число
        return int(match.group(1))
    return None

# Валидация ввода даты
def validate_date_range(date_range):
    pattern = r'^\d{2}.\d{2}.\d{4}\-\d{2}.\d{2}.\d{4}$'
    if re.match(pattern, date_range):
        try:
            start_date, end_date = date_range.split('-')

            start_date = datetime.strptime(start_date, "%d.%m.%Y")
            end_date = datetime.strptime(end_date, "%d.%m.%Y")
            return start_date, end_date
        except ValueError:
            return None
    return None

def set_admin_commands(bot,message):
    admin_commands = [
        types.BotCommand("/type_product", "Управление типами продуктов"),
        types.BotCommand("/product", "Управление продуктами"),
        types.BotCommand("/product_param", "Управление параметрами продуктов"),
        types.BotCommand("/manage_stock", "Управление стоком и ценами"),
        types.BotCommand("/reports", "Отчеты"),
        types.BotCommand("/settings", "Настройки"),
        types.BotCommand("/restart", "Перезапустить бота")
    ]
    bot.set_my_commands(admin_commands,scope=types.BotCommandScopeChat(message.chat.id))

def is_valid_command(message_text,state):
    if message_text.startswith('#') or message_text.startswith('/restart'):
        state.delete()
        return False
    return True

def create_media_group(avito_photos, order_message):
    """
    Формирует медиа-группу из фотографий и добавляет caption только для первого элемента.

    :param avito_photos: массив фото.
    :param order_message: Сообщение для первого фото.
    :return: Список InputMediaPhoto для отправки через send_media_group.
    """
    media_group = []
    for idx, photo_path in enumerate(avito_photos):
        with open(photo_path, 'rb') as photo_file:
            # Читаем содержимое файла в память
            file_data = BytesIO(photo_file.read())

            if idx == 0:
                # Добавляем caption только для первого элемента
                media_group.append(InputMediaPhoto(file_data, caption=order_message))
            else:
                # Для остальных элементов caption не указываем
                media_group.append(InputMediaPhoto(file_data))

    return media_group


def normalize_time_input(time_input: str) -> str:
    """
    Нормализует ввод времени, поддерживая различные форматы.
    Примеры:
    - 14:30
    - с 14:30
    - до 19:00
    - с 14:30 до 19:00
    - 14:30 - 19:00
    """
    # Очищаем строку от лишних пробелов
    time_input = time_input.strip().lower()

    # Паттерн для поиска времени в формате ЧЧ:ММ
    time_pattern = r'\d{1,2}:\d{2}'

    # Находим все временные значения в строке
    times = re.findall(time_pattern, time_input)

    if len(times) == 1:
        # Если найдено одно время
        if 'до' in time_input:
            return f"до {times[0]}"
        elif 'с' in time_input:
            return f"с {times[0]}"
        else:
            return times[0]
    elif len(times) == 2:
        # Если найдено два времени
        if 'с' in time_input and 'до' in time_input:
            return f"с {times[0]} до {times[1]}"
        else:
            return f"{times[0]} - {times[1]}"

    return time_input


def generate_map_link(trip_items: List[Dict], warehouse_location: Dict) -> str:
    """Генерирует ссылку на маршрут"""
    # Начинаем с координат склада
    points = [f"{warehouse_location['longitude']},{warehouse_location['latitude']}"]

    # Добавляем уникальные точки доставки
    seen_addresses = set()
    for item in trip_items:
        if item['coordinates'] and item['delivery_address'] not in seen_addresses:
            points.append(f"{item['coordinates'][1]},{item['coordinates'][0]}")
            seen_addresses.add(item['delivery_address'])

    # Формируем маршрут
    route_points = "~".join(points)

    return (
        "https://yandex.ru/maps/?"
        f"rtext={route_points}"
        "&rtt=auto"
        "&z=11"
        "&l=map"
    )