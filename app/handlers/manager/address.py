from telebot.handler_backends import State, StatesGroup
from telebot import types
from telebot.types import Message, CallbackQuery
from telebot.states.sync.context import StateContext
from typing import Optional
from database import get_user_info
from bot import bot
from middlewares.delivery_zones import (
    DeliveryZoneManager,
    AddressComponents,
    DeliveryCostCalculator
)
from config import YANDEX_API_KEY, DATABASE_CONFIG
import psycopg2
from psycopg2.extras import RealDictCursor

from utils import is_valid_command

from middlewares.delivery_zones import DeliveryZone
from states import DeliveryStates

from handlers.handlers import delete_multiple_states

# Инициализация соединения с БД
connection = psycopg2.connect(**DATABASE_CONFIG)
connection.set_session(autocommit=True)

# Инициализация менеджеров
zone_manager = DeliveryZoneManager(connection, YANDEX_API_KEY)
cost_calculator = DeliveryCostCalculator(connection)


class DeliveryAddressStates(StatesGroup):
    """Состояния для процесса ввода адреса"""
    waiting_for_city = State()
    waiting_for_street = State()
    waiting_for_house = State()
    waiting_for_apartment = State()
    temp_address_data=State()
    confirm_address = State()
    zone_id=State()
    delivery_address=State()
    zone_name = State()
    confirm_components=State()
    confirm_cooridnates=State()
    confirm_full_address = State()



def get_city_keyboard() -> types.ReplyKeyboardMarkup:
    """Создает клавиатуру с выбором города"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.InlineKeyboardButton("Екатеринбург"))
    return markup


def get_apartment_keyboard() -> types.InlineKeyboardMarkup:
    """Создает инлайн клавиатуру для выбора квартиры"""
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("Пропустить", callback_data="skip_apartment"),
        types.InlineKeyboardButton("Указать квартиру", callback_data="add_apartment")
    )
    return markup

@bot.callback_query_handler(state=DeliveryAddressStates.waiting_for_city,func=lambda call: True )
def handle_main_city(call:CallbackQuery,state:StateContext):
    if not is_valid_command(call.message.text, state): return

    try:
        city = call.data.strip()
        if not city:
            bot.reply_to(call.message, "Пожалуйста, введите название города.")
            return

        state.add_data(city=city)
        bot.send_message(
            call.message.chat.id,
            "Введите улицу:",
        )
        state.set(DeliveryAddressStates.waiting_for_street)
    except Exception as e:
        bot.reply_to(call.message, "Произошла ошибка при обработке города. Попробуйте еще раз.")
        print(f"Error in handle_city: {e}")


@bot.message_handler(state=DeliveryAddressStates.waiting_for_city)
def handle_city(message: Message, state: StateContext):
    """Обработчик ввода города"""
    if not is_valid_command(message.text, state): return

    try:
        city = message.text.strip()
        if not city:
            bot.reply_to(message, "Пожалуйста, введите название города.")
            return

        state.add_data(city=city)
        bot.send_message(
            message.chat.id,
            "Введите улицу:",
        )
        state.set(DeliveryAddressStates.waiting_for_street)
    except Exception as e:
        bot.reply_to(message, "Произошла ошибка при обработке города. Попробуйте еще раз.")
        print(f"Error in handle_city: {e}")


@bot.message_handler(state=DeliveryAddressStates.waiting_for_street)
def handle_street(message: Message, state: StateContext):
    """Обработчик ввода улицы"""
    if not is_valid_command(message.text, state): return

    try:
        street = message.text.strip()
        if not street:
            bot.reply_to(message, "Пожалуйста, введите название улицы.")
            return

        state.add_data(street=street)
        bot.reply_to(message, "Введите номер дома:")
        state.set(DeliveryAddressStates.waiting_for_house)
    except Exception as e:
        bot.reply_to(message, "Произошла ошибка при обработке улицы. Попробуйте еще раз.")
        print(f"Error in handle_street: {e}")


@bot.message_handler(state=DeliveryAddressStates.waiting_for_house)
def handle_house(message: Message, state: StateContext):
    """Обработчик ввода номера дома"""
    if not is_valid_command(message.text, state): return

    try:
        house = message.text.strip()
        if not house:
            bot.reply_to(message, "Пожалуйста, введите номер дома.")
            return

        state.add_data(house=house)
        markup = get_apartment_keyboard()
        bot.reply_to(
            message,
            "Нужно указать номер квартиры/офиса?",
            reply_markup=markup
        )
    except Exception as e:
        bot.reply_to(message, "Произошла ошибка при обработке номера дома. Попробуйте еще раз.")
        print(f"Error in handle_house: {e}")


@bot.callback_query_handler(func=lambda call: call.data == "skip_apartment")
def handle_skip_apartment(call: CallbackQuery, state: StateContext):
    """Обработчик пропуска ввода квартиры"""
    if not is_valid_command(call.message.text, state):
        return
    try:
        bot.edit_message_reply_markup(
            call.message.chat.id,
            call.message.message_id,
            reply_markup=None
        )
        process_full_address(call.message, state)
    except Exception as e:
        bot.answer_callback_query(
            call.id,
            "Произошла ошибка. Попробуйте еще раз."
        )
        print(f"Error in handle_skip_apartment: {e}")


@bot.callback_query_handler(func=lambda call: call.data == "add_apartment")
def handle_add_apartment(call: CallbackQuery, state: StateContext):
    """Обработчик запроса на ввод квартиры"""
    if not is_valid_command(call.message.text, state):
        return
    try:
        bot.edit_message_text(
            "Введите номер квартиры/офиса:",
            call.message.chat.id,
            call.message.message_id
        )
        state.set(DeliveryAddressStates.waiting_for_apartment)
    except Exception as e:
        bot.answer_callback_query(
            call.id,
            "Произошла ошибка. Попробуйте еще раз."
        )
        print(f"Error in handle_add_apartment: {e}")


@bot.message_handler(state=DeliveryAddressStates.waiting_for_apartment)
def handle_apartment(message: Message, state: StateContext):
    """Обработчик ввода номера квартиры"""
    if not is_valid_command(message.text, state):
        return
    try:
        apartment = message.text.strip()
        if not apartment:
            bot.reply_to(message, "Пожалуйста, введите номер квартиры/офиса.")
            return

        state.add_data(apartment=apartment)
        process_full_address(message, state)
    except Exception as e:
        bot.reply_to(message, "Произошла ошибка при обработке номера квартиры. Попробуйте еще раз.")
        print(f"Error in handle_apartment: {e}")


def process_full_address(message: Message, state: StateContext):
    """Обработка полного адреса"""
    try:
        with state.data() as data:
            components = AddressComponents(
                city=data.get('city'),
                street=data.get('street'),
                house=data.get('house'),
                apartment=data.get('apartment')
            )

        address_parts = [
            components.city,
            components.street,
            f"дом {components.house}"
        ]
        if components.apartment:
            address_parts.append(f"квартира {components.apartment}")

        full_address = ", ".join(address_parts)
        coordinates = zone_manager.geocode_address(full_address)

        if coordinates:
            lat, lon = coordinates
            zone = zone_manager.get_zone_by_coordinates(lat, lon)
            if zone and zone.color == 'white':
                # Если определена белая зона, показываем выбор зоны
                show_zone_confirmation(message.chat.id, zone, full_address, components, coordinates, state)
            elif zone:
                # Если определена любая другая зона, сразу сохраняем её
                state.add_data(zone_name=zone.name)
                state.add_data(zone_id=zone.id)

                # Создаем и сохраняем данные об адресе
                delivery_address = zone_manager.prepare_delivery_address(
                    components,
                    coordinates
                )

                if delivery_address:
                    delivery_address['zone_id'] = zone.id
                    state.add_data(delivery_address=delivery_address)

                    # Записываем временные данные для полноты информации
                    temp_address_data = {
                        'full_address': full_address,
                        'components': {
                            'city': components.city,
                            'street': components.street,
                            'house': components.house,
                            'apartment': components.apartment
                        },
                        'coordinates': coordinates,
                        'selected_zone_id': zone.id
                    }
                    state.add_data(temp_address_data=temp_address_data)

                    # Отправляем сообщение о подтверждении
                    bot.send_message(
                        message.chat.id,
                        f"✅ Определена {zone.name} зона!\n"
                        f"📍 {full_address}"
                    )

                    # Переходим к следующему шагу
                    bot.send_message(message.chat.id, "Введите контактный телефон:")
                    state.set(DeliveryStates.contact_phone)
            else:
                bot.send_message(
                    message.chat.id,
                    "Не удалось определить зону доставки. Пожалуйста, попробуйте другой адрес."
                )
                state.set(DeliveryAddressStates.waiting_for_city)
        else:
            bot.send_message(
                message.chat.id,
                "Не удалось определить координаты адреса. Пожалуйста, проверьте правильность ввода."
            )
            state.set(DeliveryAddressStates.waiting_for_city)

    except Exception as e:
        bot.send_message(
            message.chat.id,
            "Произошла ошибка при обработке адреса. Пожалуйста, попробуйте еще раз."
        )
        print(f"Error in process_full_address: {e}")

def show_zone_confirmation(chat_id: int, zone: DeliveryZone, full_address: str,
                           components: AddressComponents, coordinates: tuple, state: StateContext):
    """Показывает сообщение с подтверждением зоны доставки и возможностью её изменения"""
    components_dict = {
        'city': components.city,
        'street': components.street,
        'house': components.house,
        'apartment': components.apartment
    }
    markup = types.InlineKeyboardMarkup(row_width=2)
    state.add_data(confirm_components = components_dict)
    state.add_data(confirm_coordinates = coordinates)
    state.add_data(confirm_full_address = full_address)
    # Получаем все зоны для возможности выбора
    all_zones = zone_manager.get_all_zones()
    # Добавляем белую зону
    print(all_zones,'zones')
    cursor = zone_manager.db_connection.cursor()
    cursor.execute("""
        SELECT id, name, color, base_price, additional_item_price
        FROM delivery_zones 
        WHERE color = 'white' 
        LIMIT 1
    """)
    white_zone = cursor.fetchone()
    if white_zone:
        all_zones.append(DeliveryZone(
            id=white_zone[0],
            name=white_zone[1],
            color=white_zone[2],
            base_price=float(white_zone[3]),
            additional_item_price=float(white_zone[4])
        ))

    # Создаем кнопки для каждой зоны
    for available_zone in all_zones:
        # Добавляем индикатор текущей зоны
        zone_name = f"✅ {available_zone.name}" if zone and zone.id == available_zone.id else available_zone.name
        markup.add(types.InlineKeyboardButton(
            zone_name,
            callback_data=f"confirm_zone_{available_zone.id}_{available_zone.name}"
        ))

    # Добавляем кнопку подтверждения
    # Сохраняем данные в state
    # tmp = {
    #         'full_address': full_address,
    #         'components': {
    #             'city': components.city,
    #             'street': components.street,
    #             'house': components.house,
    #             'apartment': components.apartment
    #         },
    #         'coordinates': coordinates,
    #         'selected_zone_id': zone.id if zone else None
    #     }
    #
    # state.add_data(
    #     temp_address_data=tmp
    # )
    # state.set(DeliveryAddressStates.temp_address_data)

    message_text = (
        f"📍 Адрес: {full_address}\n"
        f"🎯 Определена зона: {zone.name if zone else 'Не определена'}\n\n"
        f"Выберите зону доставки или подтвердите определенную:"
    )

    bot.send_message(chat_id, message_text, reply_markup=markup)



@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_zone'))
def handle_zone_confirmation(call: CallbackQuery, state: StateContext):
    """Обработчик подтверждения зоны доставки"""
    zone_id = int(call.data.split('_')[2])
    zone_name = call.data.split('_')[3]

    with state.data() as data:
        components = data.get('confirm_components',{})
        cooridnates = data.get('confirm_coordinates',{})
        full_address = data.get('confirm_full_address','')
    state.add_data(zone_name=zone_name)
    state.add_data(zone_id=zone_id)
    # Создаем полные данные об адресе для сохранения в state

    delivery_address = zone_manager.prepare_delivery_address(AddressComponents(**components),cooridnates)
    if delivery_address:
        # Обновляем zone_id на выбранный пользователем
        delivery_address['zone_id'] = zone_id

        # Сохраняем данные в state для последующего использования
        state.add_data(delivery_address=delivery_address)

        temp_address_data = {
            'full_address': full_address,
            'components': {
                'city': components['city'],
                'street': components['street'],
                'house': components['house'],
                'apartment': components['apartment']
            },
            'coordinates': cooridnates,
            'selected_zone_id': delivery_address['zone_id']
        }
        state.add_data(temp_address_data=temp_address_data)

        # Редактируем сообщение, убирая клавиатуру
        bot.edit_message_text(
            f"✅ Выбрана {zone_name} зона!\n"
            f"📍 {full_address}\n",
            call.message.chat.id,
            call.message.message_id
        )

        # Переходим к следующему шагу
        bot.send_message(call.message.chat.id, "Введите контактный телефон:")
        state.set(DeliveryStates.contact_phone)
        delete_multiple_states(state, ['confirm_components', 'confirm_coordinates', 'confirm_full_address'])


@bot.callback_query_handler(func=lambda call: call.data == "retry_address")
def handle_retry_address(call: CallbackQuery, state: StateContext):
    """Обработчик повторного ввода адреса"""
    try:
        bot.edit_message_reply_markup(
            call.message.chat.id,
            call.message.message_id,
            reply_markup=None
        )
        bot.send_message(
            call.message.chat.id,
            "Введите город:",
            reply_markup=get_city_keyboard()
        )
        state.set(DeliveryAddressStates.waiting_for_city)

    except Exception as e:
        bot.answer_callback_query(
            call.id,
            "Произошла ошибка. Попробуйте еще раз."
        )
        print(f"Error in handle_retry_address: {e}")


# @bot.callback_query_handler(func=lambda call: call.data == "cancel_order")
# def handle_cancel_order(call: CallbackQuery, state: StateContext):
#     """Обработчик отмены заказа"""
#     try:
#         bot.edit_message_reply_markup(
#             call.message.chat.id,
#             call.message.message_id,
#             reply_markup=None
#         )
#         bot.send_message(
#             call.message.chat.id,
#             "❌ Заказ отменен из-за недоступности адреса доставки."
#         )
#         state.delete()
#     except Exception as e:
#         bot.answer_callback_query(
#             call.id,
#             "Произошла ошибка. Попробуйте еще раз."
#         )
#         print(f"Error in handle_cancel_order: {e}")