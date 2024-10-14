from telebot import types
from bot import get_bot_instance
from database import check_user_access
from telebot.states.sync.context import StateContext
from telebot.types import ReplyParameters
from utils import get_available_buttons
import handlers.manager
import handlers.courier
import handlers.admin

from database import get_user_info

from app_types import UserRole

from states import AppStates

from handlers.handlers import get_user_by_username

from database import get_orders
from utils import format_order_message

from utils import validate_date_range

from app_types import OrderType

from app_types import SaleType

from database import get_active_orders_without_packer

from database import get_product_info

from config import CHANNEL_CHAT_ID
from database import update_order_status
from handlers.courier.courier import notify_couriers


from utils import set_admin_commands

from database import get_order_by_id
from utils import format_order_message_for_courier

bot = get_bot_instance()

@bot.message_handler(commands=['restart'])
def restart_bot(message: types.Message, state: StateContext):
    # Сбрасываем состояние пользователя
    state.delete()
    bot.send_message(message.chat.id, "Бот был перезапущен")


@bot.message_handler(commands=['start'])
def start(message,state:StateContext):
    user_access = get_user_info(message.from_user.username)

    if not user_access:
        bot.reply_to(message, "У вас нет доступа к боту. Обратитесь к администратору для получения доступа.")
        return


    available_buttons = get_available_buttons(user_access['roles'])
    username = message.from_user.username

    # Проверка в Redis
    with state.data() as data:
        user = data.get('user_info')
    if not user:
        # Допустим, получаем user_id из базы данных
        user_info = get_user_info(username)  # Это твоя функция
        if user_info:
            state.add_data(user_info=user_info)  # Сохраняем user_id в Redis

    if not available_buttons:
        bot.reply_to(message,
                     "У вас нет доступа к функциям бота. Обратитесь к администратору для получения необходимых прав.")
        return
    if 'Admin' in user_access['roles']:
        set_admin_commands(bot)
    else:
        general_command = [types.BotCommand("/restart", "Перезапустить бота")]
        bot.set_my_commands(general_command)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(*available_buttons)
    bot.send_message(message.chat.id, f"Добро пожаловать, {user_access['name']}! Выберите действие:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == '#Заказы')
def handle_orders(message: types.Message, state: StateContext):
    print(state)
    user_info = get_user_by_username(message.from_user.username, state)  # Получаем информацию о пользователе

    markup = types.InlineKeyboardMarkup()
    # Общие кнопки для всех ролей
    markup.add(types.InlineKeyboardButton("История заказов", callback_data='orders_show_history'))
    # markup.add(types.InlineKeyboardButton("Взять в упаковку", callback_data='orders_pack_goods'))
    markup.add(types.InlineKeyboardButton("Упаковка товара", callback_data='orders_pack'))

    # Дополнительные кнопки для курьеров
    if UserRole.COURIER.value in user_info['roles'] or  UserRole.ADMIN.value in user_info['roles']:
        markup.add(types.InlineKeyboardButton("Доставка товара", callback_data='orders_delivery'))

    # Все кнопки доступны админам

    state.set(AppStates.picked_action)
    bot.send_message(message.chat.id, "Выберите действие:", reply_markup=markup)
@bot.callback_query_handler(func=lambda call: call.data == 'orders_pack')
def handle_orders_pack(call: types.CallbackQuery,state: StateContext):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Взять в упаковку", callback_data='orders_pack_goods'))
    markup.add(types.InlineKeyboardButton("Мои заказы(в упаковке)", callback_data='orders_in_packing'))
    state.set(AppStates.picked_action)
    bot.send_message(call.message.chat.id, "Выберите действие:", reply_markup=markup)

# Обработчик истории заказов
@bot.callback_query_handler(func=lambda call: call.data == 'orders_show_history', state=AppStates.picked_action)
def handle_order_history(call: types.CallbackQuery, state: StateContext):
    bot.send_message(call.message.chat.id, "Введите диапазон дат в формате день.месяц.год(01.01.2000)-день.месяц.год(10.10.2000):")
    state.set(AppStates.enter_date_range)


@bot.message_handler(state=AppStates.enter_date_range)
def process_date_range(message: types.Message, state: StateContext):
    date_range = message.text
    dates = validate_date_range(date_range)

    if not dates:
        bot.send_message(message.chat.id, "Неверный формат даты. Попробуйте снова.")
        return

    start_date, end_date = dates
    state.set(AppStates.start_date)
    state.add_data(start_date=start_date.strftime("%Y-%m-%d"), end_date=end_date.strftime("%Y-%m-%d"))

    # Показываем кнопки для истории заказов
    markup = types.InlineKeyboardMarkup()
    user_info = get_user_by_username(message.from_user.username, state)
    markup.add(types.InlineKeyboardButton("Упакованные заказы", callback_data='orders_packed'))

    # Кнопки для менеджеров
    if UserRole.MANAGER.value or UserRole.ADMIN.value in user_info['roles'] :
        markup.add(types.InlineKeyboardButton("Проданные товары", callback_data='orders_sold'))

    # Кнопки для курьеров
    if UserRole.COURIER.value or UserRole.ADMIN.value in user_info['roles']:
        markup.add(types.InlineKeyboardButton("Доставленные товары", callback_data='orders_delivered'))

    bot.send_message(message.chat.id, "Выберите тип истории заказов:", reply_markup=markup)


# Обработчик упакованных заказов
@bot.callback_query_handler(func=lambda call: call.data == 'orders_packed', state=AppStates.start_date)
def show_packed_orders(call: types.CallbackQuery, state: StateContext):
    with state.data() as data:
        start_date = data['start_date']
        end_date = data['end_date']
    user_info = get_user_by_username(call.from_user.username, state)
    orders = get_orders(username=call.from_user.username, order_type=[SaleType.DIRECT.value,SaleType.DELIVERY.value,SaleType.AVITO.value],
                        status=[OrderType.CLOSED.value, OrderType.REFUND.value, OrderType.READY_TO_DELIVERY.value, OrderType.IN_DELIVERY.value], start_date=start_date,
                        end_date=end_date)
    if not orders:
        bot.send_message(call.message.chat.id, "За данный период не найдено упакованных заказов")

    for order in orders:
        order_message = format_order_message(order['id'], order['product_id'], order['product_param_id'], order['gift'],
                                             order['note'], order['order_type'], user_info['name'],
                                             user_info['username'])
        bot.send_message(call.message.chat.id, order_message)


@bot.callback_query_handler(func=lambda call: call.data == 'orders_pack_goods', state=AppStates.picked_action)
def show_active_orders_without_packer(call: types.CallbackQuery, state: StateContext):
    orders = get_active_orders_without_packer()
    user_info = get_user_by_username(call.from_user.username, state)
    if not orders:
        bot.send_message(call.message.chat.id, "Нет активных заказов без упаковщика.")
        return

    for order in orders:
        product_name, product_param = get_product_info(order['product_id'], order['product_param_id'])
        order_message = format_order_message(order['id'],product_name ,product_param,
                                             order['gift'], order['note'], order['order_type'],
                                             user_info['name'], user_info['username'])
        order_message += '\n\n Без упаковщика'
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Взять в упаковку", callback_data=f"pack_order_{order['id']}_{order['message_id']}"))

        if order['avito_photo']:
             bot.send_photo(call.message.chat.id, open(order['avito_photo'], 'rb'), caption=order_message,
                           reply_markup=markup)
        else:
             bot.send_message(call.message.chat.id, order_message, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == 'orders_in_packing')
def show_packing_orders(call: types.CallbackQuery, state: StateContext):
    user_info = get_user_by_username(call.from_user.username, state)
    print(123444)
    # Получаем все заказы со статусом in_packing, где текущий пользователь является packer_id
    orders = get_orders(status=[OrderType.IN_PACKING.value], order_type=[SaleType.DELIVERY.value,SaleType.AVITO.value], username=user_info['username'], role='packer')

    if not orders:
        bot.send_message(call.message.chat.id, "У вас нет заказов в упаковке.")
        return

    for order in orders:
        product_name, product_param = get_product_info(order['product_id'], order['product_param_id'])
        order_message = format_order_message(order['id'], product_name, product_param, order['gift'], order['note'], order['order_type'], user_info['name'], user_info['username'])
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Упаковать товар", callback_data=f"pack_goods_{order['id']}_{order['message_id']}"))
        if order['avito_photo']:
            # Если есть фото, прикрепляем его
            bot.send_photo(call.message.chat.id, open(order['avito_photo'], 'rb'), caption=order_message,reply_markup=markup)
        else:
            bot.send_message(call.message.chat.id, order_message, reply_markup=markup)

    state.set(AppStates.picked_action)

@bot.callback_query_handler(func=lambda call: call.data.startswith('pack_goods_'))
def handle_pack_goods(call: types.CallbackQuery):
    order_id = call.data.split('_')[2]
    message_to_reply = call.data.split('_')[3]

    # Сообщение с проверкой комплектации
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Упаковал", callback_data=f"packed_{order_id}_{message_to_reply}"))

    bot.send_message(call.message.chat.id, "Проверьте, что вы положили:\n1. Подставка с 3 болтами\n2. Ярусы елки\n3. Подарок", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('packed_'))
def handle_packed_order(call: types.CallbackQuery, state: StateContext):
    order_id = call.data.split('_')[1]
    message_to_reply = call.data.split('_')[2]
    user_info = get_user_by_username(call.from_user.username, state)
    order_data = get_order_by_id(int(order_id))
    order_message = format_order_message_for_courier(order_data)
    # Обновляем статус заказа на ready_to_delivery
    update_order_status(order_id, 'ready_to_delivery')
    reply_params = ReplyParameters(message_id=int(message_to_reply))
    # Отправляем уведомление в основной чат
    bot.send_message(CHANNEL_CHAT_ID, f"Заказ #{str(order_id).zfill(4)}ㅤ упакован. Упаковал: {user_info['name']} (@{user_info['username']})", reply_parameters=reply_params)

    # Меняем сообщение в чате
    bot.edit_message_text(f"Вы упаковали заказ #{str(order_id).zfill(4)}ㅤ", message_id=call.message.message_id, chat_id=call.message.chat.id)

    # Уведомляем всех курьеров
    notify_couriers(order_message, open(order_data['avito_photo']),message_to_reply, state)

    bot.answer_callback_query(call.id, "Заказ успешно упакован.")
