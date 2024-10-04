from telebot import types
from bot import get_bot_instance, get_user_state
from states import DirectStates as SaleStates, AvitoStates
from config import CHANNEL_CHAT_ID
from telebot.states.sync.context import StateContext
from database import check_user_access, get_products, get_product_params, create_order, get_user_info, get_product_info,get_product_type
from app_types import UserRole
from redis_client import save_user_state, load_user_state, delete_user_state
from utils import format_order_message

# Инициализация хранилища состояний
bot = get_bot_instance()



@bot.message_handler(func=lambda message: message.text == '#Продажа')
def handle_sale(message,state:StateContext):
    chat_id = message.chat.id
    with state.data() as data:
        user_info = data.get('user_info')
    if not user_info or UserRole.MANAGER.value not in user_info['roles']:
        bot.reply_to(message, "У вас нет доступа к этой функции.")
        return
    # user_state = load_user_state(chat_id)
    # if chat_id in user_state:
    #     state.delete()

    # state = bot.get_state(message.chat.id)
    state.set(SaleStates.type_product)

    product_types = get_product_type()
    print(product_types)
    print('product_types')
    markup = types.InlineKeyboardMarkup()
    for product_type in product_types:
        markup.add(types.InlineKeyboardButton(product_type[1], callback_data=f"type_product_{product_type[0]}"))
    bot.send_message(chat_id, "Выберите тип:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('type_product_'), state=SaleStates.type_product)
def handle_product_sale(call: types.CallbackQuery,state:StateContext):
    # user_state = load_user_state(chat_id)
    # if chat_id in user_state:
    #     state.delete()
    type_id = call.data.split('_')[2]
    # state = bot.get_state(message.chat.id)
    state.set(SaleStates.product_id)

    products = get_products(type_id)
    print(products)
    print('products')
    markup = types.InlineKeyboardMarkup()
    for product in products:
        markup.add(types.InlineKeyboardButton(product[1], callback_data=f"product_{product[0]}"))
    bot.send_message(call.message.chat.id, "Выберите продукт:", reply_markup=markup)

@bot.callback_query_handler(state=SaleStates.product_id, func=lambda call: call.data.startswith('product_'))
def handle_product_selection(call: types.CallbackQuery,state:StateContext):
    product_id = call.data.split('_')[1]
    print(1234)
    # Сохраняем выбранный продукт в состоянии
    state.add_data(product_id=product_id)

    # Переходим в состояние выбора параметра продукта
    state.set(SaleStates.param_id)
    # save_param_to_redis(chat_id,'product_id', product_id)

    # Отправляем параметры продукта
    params = get_product_params(product_id)
    markup = types.InlineKeyboardMarkup()
    for param in params:
        markup.add(types.InlineKeyboardButton(param[1], callback_data=f"param_{param[0]}"))
    bot.edit_message_text("Выберите параметр продукта:", chat_id=call.message.chat.id,
                          message_id=call.message.message_id, reply_markup=markup)


@bot.callback_query_handler(state=SaleStates.param_id, func=lambda call: call.data.startswith('param_'))
def handle_param_selection(call: types.CallbackQuery,state:StateContext):
    param_id = call.data.split('_')[1]
    # Сохраняем параметр
    # state = bot.get_state(call.message.chat.id)
    state.add_data(param_id=param_id)
    # save_param_to_redis(chat_id, 'param_id', param_id)


    # Переход в состояние ввода подарка
    state.set(SaleStates.gift)


    # Спрашиваем текст подарка
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Пропустить", callback_data="skip"))
    bot.edit_message_text("Введите текст подарка или нажмите 'Пропустить':", chat_id=call.message.chat.id,
                          message_id=call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(state=SaleStates.gift, func=lambda call: call.data == 'skip')
def skip_gift(call: types.CallbackQuery, state: StateContext):
    # Пропускаем ввод подарка
    state.add_data(gift=None)
    # Переходим к состоянию примечания
    state.set(SaleStates.note)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Пропустить", callback_data='skip'))
    bot.edit_message_text("Введите примечание или нажмите 'Пропустить'", chat_id=call.message.chat.id,
                          message_id=call.message.message_id, reply_markup=markup)

@bot.message_handler(state=SaleStates.gift, func=lambda message: True)
def process_gift(message: types.Message, state: StateContext):
    # Сохраняем текст подарка
    gift = message.text.strip()
    state.add_data(gift=gift)
    # Переходим к состоянию примечания
    state.set(SaleStates.note)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Пропустить", callback_data='skip'))
    bot.send_message(message.chat.id, "Введите примечание или нажмите 'Пропустить'", reply_markup=markup)





@bot.callback_query_handler(state=SaleStates.note, func=lambda call: call.data == 'skip')
def skip_note(call: types.CallbackQuery, state: StateContext):
    # Пропускаем ввод примечания
    state.add_data(note=None)
    # Переходим к выбору типа продажи
    state.set(SaleStates.sale_type)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Прямая", callback_data="sale_direct"))
    markup.add(types.InlineKeyboardButton("Доставка", callback_data="sale_delivery"))
    markup.add(types.InlineKeyboardButton("Авито", callback_data="sale_avito"))
    bot.send_message(call.message.chat.id, "Выберите тип продажи:", reply_markup=markup)

@bot.message_handler(state=SaleStates.note, func=lambda message: True)
def process_note(message: types.Message, state: StateContext):
    # Сохраняем текст примечания
    note = message.text.strip()
    state.add_data(note=note)
    # Переходим к выбору типа продажи
    state.set(SaleStates.sale_type)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Прямая", callback_data="sale_direct"))
    markup.add(types.InlineKeyboardButton("Доставка", callback_data="sale_delivery"))
    markup.add(types.InlineKeyboardButton("Авито", callback_data="sale_avito"))
    bot.send_message(message.chat.id, "Выберите тип продажи:", reply_markup=markup)



@bot.callback_query_handler(state=SaleStates.sale_type, func=lambda call: True)
def handle_sale_type(call: types.CallbackQuery,state:StateContext):
    sale_type = call.data.split('_')[1]
    # Сохраняем тип продажи
    state.add_data(sale_type=sale_type)

    if sale_type == "avito":
        # Переход к состоянию загрузки фото для Авито
        state.set(AvitoStates.avito_photo)
        bot.send_message(call.message.chat.id, "Пожалуйста, загрузите фотографию для Авито.")
    elif sale_type == "direct":
        # Завершение заказа
        finalize_order(call.message.chat.id,call.from_user.username,call.message.message_id,state)

def finalize_order(chat_id, username, message_id, state: StateContext):
    # Загружаем состояние пользователя через контекстный менеджер

    # Работаем с данными через контекстный менеджер
    with state.data() as order_data:
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
                manager_info = get_user_info(username)
                if not manager_info:
                    bot.send_message(chat_id, "Не удалось получить информацию о менеджере.")
                    return

                manager_id, manager_name, manager_username = manager_info

                order_id = create_order(product_id, param_id, gift, note, sale_type, manager_id, message_id)

                product_name, product_param = get_product_info(product_id, param_id)

                order_message = format_order_message(
                    order_id, product_name, product_param, gift, note, sale_type, manager_name, manager_username
                )
                bot.send_message(chat_id, order_message)
                bot.send_message(CHANNEL_CHAT_ID, order_message)

                # Удаляем состояние после завершения заказа
                state.delete()
            except Exception as e:
                bot.send_message(chat_id, f"Произошла ошибка при оформлении заказа: {str(e)}")
        else:
            bot.send_message(chat_id, "Произошла ошибка при оформлении заказа. Пожалуйста, попробуйте снова.")


def save_param_to_redis(chat_id, param_name,param_value):
    user_state = load_user_state(chat_id)
    user_state[param_name] = param_value
    save_user_state(chat_id, user_state)