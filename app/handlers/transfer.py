from telebot import types
from telebot.states.sync.context import StateContext
from telebot.types import ReplyParameters, CallbackQuery
from bot import bot

from app_types import UserRole
from config import CHANNEL_CHAT_ID
from database import get_orders, get_users_by_role, get_order_by_id, get_user_info_by_id, get_user_info, \
    transfer_order_to_user, get_avito_photos
from handlers.handlers import get_user_by_username
from utils import format_order_message, create_media_group




@bot.message_handler(commands=['transfer'])
def start_transfer(message: types.Message, state: StateContext):
    """Начинает процесс передачи заказа"""
    user_info = get_user_by_username(message.from_user.username, state)
    if not user_info:
        return

    markup = types.InlineKeyboardMarkup()
    if UserRole.COURIER.value in user_info['roles']:
        markup.add(types.InlineKeyboardButton("Передать доставку", callback_data="transfer_delivery"))
    markup.add(types.InlineKeyboardButton("Передать упаковку", callback_data="transfer_packing"))

    bot.reply_to(message, "Выберите тип передачи:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "transfer_delivery")
def handle_transfer_delivery(call: CallbackQuery, state: StateContext):
    """Обработка передачи доставки"""
    # Получаем активные заказы курьера
    orders = get_orders(
        username=call.from_user.username,
        status=['ready_to_delivery'],
        role='courier'
    )

    if not orders:
        bot.answer_callback_query(call.id, "У вас нет активных заказов для передачи")
        return

    markup = types.InlineKeyboardMarkup()
    for order in orders:
        markup.add(types.InlineKeyboardButton(
            f"Заказ #{order['id']}",
            callback_data=f"transfer_delivery_order_{order['id']}"
        ))

    bot.edit_message_text(
        "Выберите заказ для передачи:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("transfer_delivery_order_"))
def select_courier_for_transfer(call: CallbackQuery, state: StateContext):
    """Выбор курьера для передачи"""
    order_id = call.data.split('_')[-1]
    state.add_data(transfer_order_id=order_id)
    state.add_data(transfer_type='courier')

    couriers = get_users_by_role(UserRole.COURIER.value)
    markup = types.InlineKeyboardMarkup(row_width=2)

    # Группируем курьеров по 2 в ряд
    buttons = []
    for courier in couriers:
        if courier['username'] != call.from_user.username:  # Исключаем текущего курьера
            buttons.append(types.InlineKeyboardButton(
                courier['name'],
                callback_data=f"transfer_to_user_{courier['id']}"
            ))

    markup.add(*buttons)

    bot.edit_message_text(
        "Выберите курьера для передачи заказа:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data == "transfer_packing")
def handle_transfer_packing(call: CallbackQuery, state: StateContext):
    """Обработка передачи упаковки"""
    orders = get_orders(
        username=call.from_user.username,
        status=['in_packing'],
        role='packer'
    )

    if not orders:
        bot.answer_callback_query(call.id, "У вас нет активных заказов для передачи")
        return

    markup = types.InlineKeyboardMarkup()
    for order in orders:
        markup.add(types.InlineKeyboardButton(
            f"Заказ #{order['id']}",
            callback_data=f"transfer_packing_order_{order['id']}"
        ))

    bot.edit_message_text(
        "Выберите заказ для передачи:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("transfer_packing_order_"))
def select_packer_for_transfer(call: CallbackQuery, state: StateContext):
    """Выбор упаковщика для передачи"""
    order_id = call.data.split('_')[-1]
    state.add_data(transfer_order_id=order_id)
    state.add_data(transfer_type='packer')

    users = get_users_by_role([UserRole.MANAGER.value,UserRole.ADMIN.value,UserRole.COURIER.value])  # Все могут упаковывать
    markup = types.InlineKeyboardMarkup(row_width=2)

    buttons = []
    for user in users:

        buttons.append(types.InlineKeyboardButton(
            user['name'],
            callback_data=f"transfer_to_user_{user['id']}"
        ))

    markup.add(*buttons)

    bot.edit_message_text(
        "Выберите пользователя для передачи заказа:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("transfer_to_user_"))
def complete_transfer(call: CallbackQuery, state: StateContext):
    """Завершение передачи заказа"""
    try:
        new_user_id = int(call.data.split('_')[-1])

        with state.data() as data:
            order_id = data['transfer_order_id']
            transfer_type = data['transfer_type']

        # Получаем информацию о заказе и новом пользователе
        order = get_order_by_id(order_id)
        new_user = get_user_info_by_id(new_user_id)
        old_user = get_user_info(call.from_user.username)

        if not all([order, new_user, old_user]):
            raise ValueError("Не удалось получить необходимую информацию")

        # Выполняем передачу
        if transfer_order_to_user(order_id, new_user_id, transfer_type):
            # Формируем сообщение для нового пользователя
            order_message = format_order_message(
                order_id=order['id'],
                product_list=order['products'],
                gift=order['gift'],
                note=order['note'],
                sale_type=order['order_type'],
                manager_name=order['manager_name'],
                manager_username=order['manager_username'],
                delivery_date=order.get('delivery_date'),
                delivery_time=order.get('delivery_time'),
                delivery_address=order.get('delivery_address'),
                contact_phone=order.get('contact_phone'),
                contact_name=order.get('contact_name'),
                total_price=order.get('total_price'),
                avito_boxes=order.get('avito_boxes'),
                hide_track_prices=True
            )
            transfer_type_ru = "Курьерский заказ" if transfer_type == 'courier' else "Заказ в упаковку"
            # Отправляем уведомление новому пользователю
            if transfer_type == 'courier':
                # Для Авито отправляем фотографии
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton(
                    "🚗 Создать поездку",
                    callback_data=f"create_trip"
                ))
                photos = get_avito_photos(order_id)
                if photos:
                    media = create_media_group(photos, f"Вам был передан заказ от {old_user['name']} ({old_user['username']})\n{transfer_type_ru}\n\n{order_message}")
                    bot.send_media_group(new_user['telegram_id'], media)

                else:
                    bot.send_message(new_user['telegram_id'], f"Вам был передан заказ от {old_user['name']} ({old_user['username']})\n{transfer_type_ru}\n\n{order_message}", reply_markup=markup)
                bot.send_message(new_user['telegram_id'], "Если вы хотите упаковать этот заказ, нажмите на кнопку ниже:",
                                 reply_markup=markup)
            else:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton(
                    "📦 Упаковать товар !!!",
                    callback_data=f"pack_goods_{order['id']}_{order['message_id']}"
                ))
                bot.send_message(new_user['telegram_id'],
                                 f"Вам передан заказ от {old_user['name']} ({old_user['username']})\n{transfer_type_ru}\n\n{order_message}")
                bot.send_message(new_user['telegram_id'], "Если вы хотите упаковать этот заказ, нажмите на кнопку ниже:",
                                 reply_markup=markup)
            # Отправляем сообщение в общий чат
            bot.send_message(
                CHANNEL_CHAT_ID,
                f"{'Курьер' if transfer_type == 'courier' else 'Упаковщик'} для заказа #{order['id']} изменен\n"
                f"Был: {old_user['name']} ({old_user['username']})\n"
                f"Стал: {new_user['name']} ({new_user['username']})",
                reply_parameters=ReplyParameters(message_id=order['message_id'])
            )

            # Сообщение об успешной передаче
            bot.edit_message_text(
                "Заказ успешно передан",
                call.message.chat.id,
                call.message.message_id
            )
        else:
            bot.answer_callback_query(call.id, "Не удалось передать заказ")

    except Exception as e:
        bot.answer_callback_query(call.id, "Произошла ошибка при передаче заказа")
        print(f"Error in complete_transfer: {e}")
    finally:
        state.delete()