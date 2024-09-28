from telebot import types
from enum import Enum

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

def format_order_message(order_id,product_name, product_param, gift, note, sale_type, manager_name, manager_username):
    formatted_order_id = str(order_id).zfill(4)
    order_message = f"Заказ #{formatted_order_id}\n\n"
    order_message += f"{product_name} {product_param}\n\n"
    if gift:
        order_message += f"🎁 Подарок: {gift}\n\n"
    if note:
        order_message += f"📝 Заметка: {note}\n\n"
    order_message += f"Тип продажи: {SaleTypeRu[sale_type.lower()].value}\n"
    order_message += f"Менеджер: {manager_name} {manager_username}"
    return order_message