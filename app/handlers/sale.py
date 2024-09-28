from telebot import types
from bot import get_bot_instance, get_user_state
from config import CHANNEL_CHAT_ID
from database import check_user_access, get_products, get_product_params, create_order, get_manager_info, get_product_info
from utils import UserRole, format_order_message
from redis_client import save_user_state, load_user_state, delete_user_state

bot = get_bot_instance()

@bot.message_handler(func=lambda message: message.text == '#Продажа')
def handle_sale(message):

    user_access = check_user_access(message.from_user.username)
    if not user_access or UserRole.MANAGER.value not in user_access[2]:
        bot.reply_to(message, "У вас нет доступа к этой функции.")
        return
    chat_id = message.chat.id
    if chat_id in user_state:
        delete_user_state(chat_id)
        
    bot.clear_step_handler_by_chat_id(chat_id=chat_id)
    products = get_products()
    markup = types.InlineKeyboardMarkup()
    for product in products:
        markup.add(types.InlineKeyboardButton(product[1], callback_data=f"product_{product[0]}"))
    bot.send_message(chat_id, "Выберите продукт:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('product_'))
def product_callback(call):
    chat_id = call.message.chat.id
    product_id = call.data.split('_')[1]

    save_param_to_redis(chat_id,'product_id', product_id)

    params = get_product_params(product_id)
    markup = types.InlineKeyboardMarkup()
    for param in params:
        markup.add(types.InlineKeyboardButton(param[1], callback_data=f"param_{param[0]}"))
    bot.edit_message_text("Выберите размер:", chat_id, call.message.message_id, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('param_'))
def param_callback(call):
    chat_id = call.message.chat.id
    param_id = call.data.split('_')[1]
    markup = types.InlineKeyboardMarkup()
    save_param_to_redis(chat_id, 'param_id', param_id)
    markup.add(types.InlineKeyboardButton("Пропустить", callback_data="skip_gift"))
    bot.edit_message_text("Введите текст подарка или нажмите 'Пропустить':", chat_id,
                          call.message.message_id, reply_markup=markup)
    bot.register_next_step_handler(call.message, process_gift)

@bot.callback_query_handler(func=lambda call: call.data == "skip_gift")
def skip_gift(call):
    chat_id = call.message.chat.id
    save_param_to_redis(chat_id, 'gift', None)
    ask_for_note(call.message)

def process_gift(message):
    chat_id = message.chat.id
    if message.text.startswith('#Продажа'):
        delete_user_state(chat_id)
        bot.clear_step_handler_by_chat_id(chat_id=chat_id)
        handle_sale(message)
        return
    if message.text and not message.text.startswith('#'):
        save_param_to_redis(chat_id, 'gift', message.text.strip())

    ask_for_note(message)

def ask_for_note(message):
    chat_id = message.chat.id
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Пропустить", callback_data="skip_note"))
    bot.send_message(chat_id, "Введите примечание для заказа или нажмите 'Пропустить':", reply_markup=markup)
    bot.register_next_step_handler(message, process_note)

@bot.callback_query_handler(func=lambda call: call.data == "skip_note")
def skip_note(call):
    chat_id = call.message.chat.id
    save_param_to_redis(chat_id, 'note', None)
    ask_for_sale_type(call.message)

def process_note(message):
    chat_id = message.chat.id
    if message.text.startswith('#Продажа'):
        delete_user_state(chat_id)
        bot.clear_step_handler_by_chat_id(chat_id=chat_id)
        handle_sale(message)
        return
    if message.text and not message.text.startswith('#'):
        save_param_to_redis(chat_id, 'note', message.text.strip())
    ask_for_sale_type(message)

def ask_for_sale_type(message):
    chat_id = message.chat.id
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Прямая", callback_data="sale_direct"))
    markup.add(types.InlineKeyboardButton("Доставка", callback_data="sale_delivery"))
    markup.add(types.InlineKeyboardButton("Авито", callback_data="sale_avito"))
    bot.send_message(chat_id, "Выберите тип продажи:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('sale_'))
def sale_type_callback(call):
    chat_id = call.message.chat.id
    sale_type = call.data.split('_')[1]
    user_id=call.from_user.username
    save_param_to_redis(chat_id, 'sale_type', sale_type)
    finalize_order(chat_id,user_id)


def finalize_order(chat_id, username):
    # Загружаем состояние пользователя из Redis
    order_data = load_user_state(chat_id)
    print('------------------------')
    print(order_data)
    if order_data:
        param_id = order_data.get("param_id")
        product_id = order_data.get("product_id")
        gift = order_data.get("gift")
        note = order_data.get("note")
        sale_type = order_data.get("sale_type")

        if not all([param_id, product_id, sale_type]):
            bot.send_message(chat_id, "Не хватает данных для оформления заказа. Пожалуйста, начните процесс заново.")
            return

        try:
            manager_info = get_manager_info(username)
            if not manager_info:
                bot.send_message(chat_id, "Не удалось получить информацию о менеджере.")
                return

            manager_id, manager_name, manager_username = manager_info

            order_id = create_order(product_id, param_id, gift, note, sale_type, manager_id)

            product_name, product_param = get_product_info(product_id, param_id)

            order_message = format_order_message(order_id, product_name, product_param, gift, note, sale_type,
                                                 manager_name, manager_username)

            bot.send_message(chat_id, order_message)
            bot.send_message(CHANNEL_CHAT_ID, order_message)

            # Удаляем состояние после завершения заказа
            delete_user_state(chat_id)
        except Exception as e:
            bot.send_message(chat_id, f"Произошла ошибка при оформлении заказа: {str(e)}")
    else:
        bot.send_message(chat_id, "Произошла ошибка при оформлении заказа. Пожалуйста, попробуйте снова.")

def save_param_to_redis(chat_id, param_name,param_value):
    user_state = load_user_state(chat_id)
    user_state[param_name] = param_value
    save_user_state(chat_id, user_state)