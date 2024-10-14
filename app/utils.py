from datetime import datetime

from telebot import types
from PIL import Image

from app_types import OrderType, OrderTypeRu
from database import get_product_info
import os
import io
import re

from app_types import SaleTypeRu,UserRole


def get_available_buttons(roles):
    buttons = []
    if UserRole.MANAGER.value in roles or UserRole.ADMIN.value in roles or UserRole.OWNER.value in roles:
        buttons.append(types.KeyboardButton("#Продажа"))
    if UserRole.COURIER.value in roles or UserRole.ADMIN.value in roles or UserRole.OWNER.value in roles or UserRole.MANAGER.value in roles :
        buttons.append(types.KeyboardButton("#Заказы"))
    return buttons

def escape_markdown_v2(text):
    """Экранирует специальные символы для MarkdownV2."""
    return re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', text)

def format_order_message(order_id, product_name, product_param, gift, note, sale_type,
                         manager_name, manager_username, delivery_date=None,
                         delivery_time=None, delivery_address=None, delivery_note=None,
                         contact_phone=None, contact_name=None, total_price=None):
    formatted_order_id = str(order_id).zfill(4)  # Экранирование для MarkdownV2
    order_message = f"Заказ #{formatted_order_id}ㅤ\n\n"
    order_message += f"Тип продажи: {sale_type}\n\n"
    order_message += f"Продукт: 🌲 {product_name} {product_param}\n"
    if gift:
        order_message += f"Подарок: 🎁 {gift}\n\n"
    if sale_type == "Доставка":
        order_message += f"Дата доставки: 📅 {delivery_date}\n"
        order_message += f"Время доставки: ⏰ {delivery_time}\n\n"
        order_message += f"Адрес доставки: 📍 {delivery_address}\n\n"
        if note:
            order_message += f"Заметка: 📝 {note}\n\n"
        order_message += f"Контактный телефон: 📞 {contact_phone} ({contact_name})\n"
        order_message += f"Сумма для оплаты: 💰 {total_price} ₽\n"
    else:
        if note:
            order_message += f"Заметка: 📝 {note}\n"
    order_message += f"Менеджер: {manager_name} ({manager_username})"
    return order_message


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

def set_admin_commands(bot):
    admin_commands = [
        types.BotCommand("/type_product", "Управление типами продуктов"),
        types.BotCommand("/product", "Управление продуктами"),
        types.BotCommand("/product_param", "Управление параметрами продуктов"),
        types.BotCommand("/reports", "Отчеты"),
        types.BotCommand("/restart", "Перезапустить бота")
    ]
    bot.set_my_commands(admin_commands)

def is_valid_command(message_text,state):
    if message_text.startswith('#') or message_text.startswith('/restart'):
        state.delete()
        return False
    return True