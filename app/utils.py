from telebot import types
from enum import Enum
from PIL import Image
import os
import io
import re

class UserRole(Enum):
    MANAGER = 'Manager'
    COURIER = 'Courier'
    ADMIN = 'Admin'
    OWNER = 'Owner'

class SaleType(Enum):
    DIRECT='direct'
    DELIVERY='delivery'
    AVITO='avito'

class SaleTypeRu(Enum):
    direct='Прямая'
    delivery='Доставка'
    avito='Авито'

def get_available_buttons(roles):
    buttons = []
    if UserRole.MANAGER.value in roles or UserRole.ADMIN.value in roles or UserRole.OWNER.value in roles:
        buttons.append(types.KeyboardButton("#Продажа"))
    if UserRole.COURIER.value in roles or UserRole.ADMIN.value in roles or UserRole.OWNER.value in roles:
        buttons.append(types.KeyboardButton("#Доставка"))
    return buttons

def escape_markdown_v2(text):
    """Экранирует специальные символы для MarkdownV2."""
    return re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', text)

def format_order_message(order_id, product_name, product_param, gift, note, sale_type, manager_name, manager_username):
    formatted_order_id = str(order_id).zfill(4)  # Экранирование для MarkdownV2
    order_message = f"Заказ #{formatted_order_id}ㅤ\n\n"
    order_message += f"Тип продажи: {SaleTypeRu[sale_type.lower()].value}\n\n"
    order_message += f"{product_name} {product_param}\n\n"
    if gift:
        order_message += f"🎁 Подарок: {gift}\n\n"
    if note:
        order_message += f"📝 Заметка: {note}\n\n"
    order_message += f"Менеджер: {manager_name} {manager_username}"
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