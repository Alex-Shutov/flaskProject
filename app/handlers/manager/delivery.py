from telebot.handler_backends import State, StatesGroup
from telebot import types
from telebot.types import Message, CallbackQuery
from telebot.states.sync.context import StateContext
from datetime import datetime, timedelta
import re

from bot import bot
from database import get_user_info, update_order_status, get_product_info_with_params
from config import CHANNEL_CHAT_ID, DATABASE_CONFIG, YANDEX_API_KEY
from app_types import OrderType, SaleTypeRu
from utils import is_valid_command, format_order_message
from handlers.courier.courier import notify_couriers
from handlers.manager.address import DeliveryAddressStates

from middlewares.delivery_zones import (
    DeliveryZoneManager,
    DeliveryCostCalculator,
    AddressComponents
)

import psycopg2
from psycopg2.extras import RealDictCursor

from database import update_order_message_id, create_order
from handlers.handlers import process_product_stock

from states import DeliveryStates

from utils import normalize_time_input

from handlers.handlers import review_order_data

from handlers.handlers import get_user_by_username

from app_types import SaleType

from states import DirectStates

from database import get_connection as connection

# Инициализация менеджеров
zone_manager = DeliveryZoneManager(connection, YANDEX_API_KEY)
cost_calculator = DeliveryCostCalculator(connection)




def is_valid_date(date_string: str) -> bool:
    """Проверяет корректность формата даты"""
    try:
        datetime.strptime(date_string, '%d.%m.%Y')
        return True
    except ValueError:
        return False


def is_valid_time_format(time_string: str) -> bool:
    """Проверяет корректность формата времени"""
    pattern = r'^\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}$'
    return bool(re.match(pattern, time_string))


def validate_phone(phone: str) -> bool:
    """Проверяет корректность формата телефона"""
    pattern = r'^\+?[78][-\(]?\d{3}\)?-?\d{3}-?\d{2}-?\d{2}$'
    return bool(re.match(pattern, phone))


# @bot.callback_query_handler(func=lambda call: call.data == 'sale_delivery')
def handle_sale_delivery(call: CallbackQuery, state: StateContext):
    """Начало создания заказа на доставку"""
    if not is_valid_command(call.message.text, state):
        return

    state.add_data(sale_type="delivery")

    # Создаем клавиатуру с выбором даты
    markup = types.InlineKeyboardMarkup(row_width=2)

    # Добавляем кнопки с ближайшими датами
    today = datetime.now()
    for i in range(7):  # На неделю вперед
        date = today + timedelta(days=i)
        date_str = date.strftime('%d.%m.%Y')
        date_display = date.strftime('%d.%m.%Y')  # Добавляем год в отображение
        markup.add(types.InlineKeyboardButton(
            f"📅 {date_display}",
            callback_data=f"delivery_date_{date_str}"
        ))

    # Добавляем кнопку для ручного ввода даты
    markup.add(types.InlineKeyboardButton(
        "✍️ Ввести дату вручную",
        callback_data="delivery_date_manual"
    ))

    bot.edit_message_text(
        "Выберите дату доставки:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )
    state.set(DeliveryStates.delivery_date)

@bot.callback_query_handler(func=lambda call: call.data == "delivery_date_manual", state=DeliveryStates.delivery_date)
def handle_manual_date_input(call: CallbackQuery, state: StateContext):
    """Обработчик запроса на ручной ввод даты"""
    bot.edit_message_text(
        "Введите дату доставки в формате ДД.ММ.ГГГГ\n"
        "Например: 31.12.2024",
        call.message.chat.id,
        call.message.message_id
    )
    state.set(DeliveryStates.manual_date_input)

@bot.message_handler(state=DeliveryStates.manual_date_input)
def process_manual_date(message: Message, state: StateContext):
    """Обработка введенной вручную даты"""
    try:
        # Проверяем формат даты
        input_date = datetime.strptime(message.text.strip(), '%d.%m.%Y')
        today = datetime.now()

        # Проверяем, что дата не в прошлом
        if input_date.date() < today.date():
            bot.reply_to(
                message,
                "❌ Нельзя выбрать дату в прошлом. Пожалуйста, введите корректную дату:"
            )
            return

        # Проверяем, что дата не слишком далеко в будущем (например, год вперед)
        max_future_date = today + timedelta(days=365)
        if input_date.date() > max_future_date.date():
            bot.reply_to(
                message,
                "❌ Дата слишком далеко в будущем. Пожалуйста, выберите более близкую дату:"
            )
            return

        # Сохраняем дату в нужном формате
        delivery_date = input_date.strftime('%d.%m.%Y')
        state.add_data(delivery_date=delivery_date)

        # Создаем клавиатуру с временными интервалами
        bot.reply_to(
            message,
            "Введите время доставки в любом удобном формате:\n"
            "Примеры:\n"
            "• 14:30\n"
            "• с 14:30\n"
            "• до 19:00\n"
            "• с 14:30 до 19:00\n"
            "• 14:30 - 19:00",
        )
        state.set(DeliveryStates.delivery_time)

    except ValueError:
        bot.reply_to(
            message,
            "❌ Неверный формат даты. Пожалуйста, введите дату в формате ДД.ММ.ГГГГ\n"
            "Например: 31.12.2024"
        )


@bot.callback_query_handler(
    func=lambda call: call.data.startswith('delivery_date_') and call.data != 'delivery_date_manual')
def handle_delivery_date_selection(call: CallbackQuery, state: StateContext):
    """Обработка выбора даты доставки"""
    try:
        selected_date = call.data.split('_')[2]
        state.add_data(delivery_date=selected_date)

        # Форматируем дату для отображения
        display_date = datetime.strptime(selected_date, '%d.%m.%Y').strftime('%d.%m.%Y')

        bot.edit_message_text(
            f"Выбрана дата: {display_date}\n\n"
            "Введите время доставки в любом удобном формате:\n"
            "Примеры:\n"
            "• 14:30\n"
            "• с 14:30\n"
            "• до 19:00\n"
            "• с 14:30 до 19:00\n"
            "• 14:30 - 19:00",
            call.message.chat.id,
            call.message.message_id
        )
        state.set(DeliveryStates.delivery_time)

    except Exception as e:
        bot.answer_callback_query(call.id, "Произошла ошибка при выборе даты")
        print(f"Error in handle_delivery_date_selection: {e}")


@bot.message_handler(state=DeliveryStates.delivery_time)
def handle_delivery_time(message: Message, state: StateContext):
    """Обработка ввода времени доставки"""
    if not is_valid_command(message.text, state):
        return

    time_input = message.text.strip()

    try:
        # Нормализуем ввод времени
        normalized_time = normalize_time_input(time_input)

        if not normalized_time or normalized_time == time_input:
            # Если время не удалось нормализовать, сохраняем как есть
            # Это позволяет принимать любые форматы, даже если они не соответствуют шаблонам
            state.add_data(delivery_time=time_input)
        else:
            state.add_data(delivery_time=normalized_time)

        # Переходим к вводу адреса


        # Передаем управление в модуль address.py
        state.set(DeliveryAddressStates.waiting_for_city)
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
                "Екатеринбург",
                callback_data=f"Екатеринбург"
            ))
        bot.send_message(
            message.chat.id,
            "Введите город доставки:",
            reply_markup=markup
        )

    except Exception as e:
        bot.reply_to(
            message,
            "Произошла ошибка при обработке времени. "
            "Пожалуйста, попробуйте ввести время снова."
        )
        print(f"Error in handle_delivery_time: {e}")

@bot.message_handler(state=DeliveryStates.contact_phone)
def handle_contact_phone(message: Message, state: StateContext):
    """Обработка ввода контактного телефона"""
    if not is_valid_command(message.text, state):
        return

    phone = message.text.strip()
    if not validate_phone(phone):
        bot.reply_to(
            message,
            "Неверный формат телефона. Пожалуйста, введите номер в формате: +7XXXXXXXXXX"
        )
        return

    state.add_data(contact_phone=phone)
    bot.reply_to(message, "Введите имя контактного лица:")
    state.set(DeliveryStates.contact_name)


@bot.message_handler(state=DeliveryStates.contact_name)
def handle_contact_name(message: Message, state: StateContext):
    """Обработка ввода контактного имени"""
    if not is_valid_command(message.text, state):
        return
    #
    contact_name = message.text.strip()
    if not contact_name:
        bot.reply_to(message, "Имя не может быть пустым. Пожалуйста, введите имя:")
        return
    #
    state.add_data(contact_name=contact_name)
    #
    # # Получаем данные из состояния
    # state_data = state.get_data()
    # product_dict = state_data.get('product_dict', {})
    # zone_id = state_data.get('temp_address_data', {}).get('selected_zone_id')
    #
    # # Подсчитываем общее количество товаров
    # total_items = sum(len(param_ids) for param_ids in product_dict.values())
    #
    # # Создаем список заказов для калькулятора
    # order_items = []
    # for product_id, param_ids in product_dict.items():
    #     for param_id in param_ids:
    #         order_items.append({
    #             'product_id': product_id,
    #             'param_id': param_id
    #         })
    #
    # # Рассчитываем стоимость доставки
    # delivery_cost = cost_calculator.calculate_for_trip(order_items, zone_id)
    #
    # if delivery_cost:
    #     message_text = (
    #         f"💰 Расчет стоимости доставки:\n"
    #         f"🎯 Зона доставки: {delivery_cost.zone_name}\n"
    #         f"📦 Количество товаров: {total_items}\n"
    #         f"💳 Базовая стоимость: {delivery_cost.base_price} руб.\n"
    #     )
    #
    #     if delivery_cost.additional_items_price > 0:
    #         message_text += f"📦 Доплата за дополнительные товары: {delivery_cost.additional_items_price} руб.\n"
    # message_text = ""
    # message_text += (
    #     f"Введите сумму заказа"
    # )
    #
    # bot.send_message(message.chat.id, message_text)
    state.set(DirectStates.gift)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Пропустить", callback_data="skip"))
    bot.send_message(message.chat.id, "Введите текст подарка или нажмите 'Пропустить':",
                     reply_markup=markup)


# @bot.message_handler(state=DeliveryStates.total_amount)
# def handle_total_amount(message: Message, state: StateContext):
#     """Обработка ввода общей суммы заказа"""
#     if not is_valid_command(message.text, state):
#         return
#
#     try:
#         total_amount = float(message.text.strip())
#         if total_amount <= 0:
#             raise ValueError("Amount must be positive")
#
#         state.add_data(total_amount=total_amount)
#         review_order_data(message.chat.id,state)
#     except ValueError:
#         bot.reply_to(
#             message,
#             "Неверный формат суммы. Пожалуйста, введите число больше нуля:"
#         )


def finalize_delivery_order(chat_id,message_id,username, state: StateContext):
    """Завершение создания заказа на доставку"""
    try:
        with state.data() as order_data:
            manager_info = get_user_by_username(username,state)
            if not manager_info:
                raise ValueError("Manager info not found")

            product_dict = order_data.get("product_dict")
            if not product_dict:
                raise ValueError("No products selected")
            print(manager_info,'info')
            # Создаем заказ с обновленными параметрами
            print(order_data)
            print(message_id)
            order_result = create_order(
                product_dict=product_dict,  # Используем product_dict из состояния
                gift=order_data.get('gift'),  # Базовый подарок если не указан
                note=order_data.get('note'),
                sale_type='delivery',
                manager_id=manager_info['id'],
                message_id=message_id,
                # avito_photos_tracks=None,
                # packer_id=None,
                status_order=OrderType.READY_TO_DELIVERY.value,
                delivery_date=order_data.get('delivery_date'),
                delivery_time=order_data.get('delivery_time'),
                delivery_address=order_data.get('delivery_address')['full_address'],
                contact_phone=order_data.get('contact_phone'),
                contact_name=order_data.get('contact_name'),
                total_price=order_data.get('total_price')
            )
            print(order_result,'result')
            if not order_result:
                raise ValueError("Failed to create order")

            order_id = order_result['id']
            products_info = order_result['values']

            # Формируем сообщение о заказе
            order_message = format_order_message(
                order_id=order_id,
                product_list=products_info.get('general', []),  # Список продуктов из результата
                gift=order_data.get('gift', "Гирлянда 2м"),
                note=order_data.get('note'),
                sale_type=SaleType.DELIVERY.value,
                manager_name=manager_info['name'],
                manager_username=manager_info['username'],
                delivery_date=order_data.get('delivery_date'),
                delivery_time=order_data.get('delivery_time'),
                delivery_address=order_data.get('full_address', order_data.get('delivery_address')['full_address']),
                contact_phone=order_data.get('contact_phone'),
                contact_name=order_data.get('contact_name'),
                total_price=order_data.get('total_amount'),
                zone_name=order_data.get('zone_name'),
            )
            # Отправляем сообщение менеджеру
            bot.send_message(chat_id, order_message)

            # Отправляем сообщение в канал
            channel_message = bot.send_message(CHANNEL_CHAT_ID, order_message)

            # Обновляем message_id в заказе
            update_order_message_id(order_id, channel_message.message_id)

            zone_manager.save_delivery_address(order_id,
                                            order_data.get('temp_address_data')['components'],
                                            order_data.get('temp_address_data')['coordinates'])
            # Уменьшаем количество товара на складе
            process_product_stock(product_dict)

            # Уведомляем курьеров
            notify_couriers(
                order_message,
                state,
                avito_photos=[],
                reply_message_id=channel_message.message_id
            )

            # Очищаем состояние
            state.delete()

    except Exception as e:
        bot.reply_to(
            message_id,
            "Произошла ошибка при создании заказа. Пожалуйста, попробуйте еще раз."
        )
        print(f"Error in finalize_delivery_order: {e}")