import uuid
from telebot import types
from bot import get_bot_instance
from states import AvitoStates as SaleStates,DirectStates,CourierStates
from utils import format_order_message, save_photo_and_resize
from database import check_user_access, get_products, get_product_params, create_order, get_user_info, get_product_info,get_couriers,update_order_message_id
from redis_client import save_user_state, load_user_state, delete_user_state
from telebot.states.sync.context import StateContext
from config import CHANNEL_CHAT_ID
from handlers.courier.courier import notify_couriers


bot = get_bot_instance()

# @bot.message_handler(func=lambda message: message.text == 'Авито')
# def handle_avito_sale(message):
#     chat_id = message.chat.id
#     bot.send_message(chat_id, "Загрузите фото из личного кабинета Авито.")
#     bot.register_next_step_handler(message, handle_avito_photo)

@bot.message_handler(state=SaleStates.avito_photo, content_types=['photo'])
def handle_avito_photo(message: types.Message,state:StateContext):
    chat_id = message.chat.id
    message_id = message.message_id
    if message.photo:
        photo = message.photo[-1]  # Берем последнее фото, оно будет самого высокого качества
        file_info = bot.get_file(photo.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        order_guid = str(uuid.uuid4())
        # Сохраняем фото и уменьшаем его размер
        photo_path = save_photo_and_resize(downloaded_file, order_guid)

        # Сохраняем путь к фото в базе данных
        state.add_data(avito_photo=photo_path)

        finalize_avito_order(chat_id,message_id,state)
    else:
        bot.send_message(chat_id, "Пожалуйста, загрузите страницу заказа с Авито")


def finalize_avito_order(chat_id, message_id, state: StateContext):
    """Финализируем заказ для Авито, включая фото и ответ на сообщение в канале."""
    with state.data() as order_data:
        if order_data:
            param_id = order_data.get("param_id")
            product_id = order_data.get("product_id")
            gift = order_data.get("gift")
            note = order_data.get("note")
            sale_type = "avito"
            avito_photo = order_data.get("avito_photo")

            if not all([param_id, product_id, sale_type, avito_photo]):
                bot.send_message(chat_id,
                                 "Не хватает данных для оформления заказа. Пожалуйста, начните процесс заново.")
                return

            try:
                manager_info = get_user_info('ni3omi')
                if not manager_info:
                    bot.send_message(chat_id, "Не удалось получить информацию о менеджере.")
                    return

                manager_id, manager_name, manager_username = manager_info.get('id'), manager_info.get('name'), manager_info.get('username')

                # Создаем заказ в БД и получаем order_id
                order_id = create_order(product_id, param_id, gift, note, sale_type, manager_id, message_id,
                                        avito_photo)

                product_name, product_param = get_product_info(product_id, param_id)

                order_message = format_order_message(
                    order_id, product_name, product_param, gift, note, sale_type, manager_name, manager_username
                )

                # Отправляем сообщение с фото в основной канал и сохраняем message_id для ответа
                sent_message = bot.send_photo(CHANNEL_CHAT_ID, open(avito_photo, 'rb'), caption=order_message)

                reply_message_id = sent_message.message_id

                update_order_message_id(order_id, reply_message_id)

                # Обновляем состояние с сообщением и фото для курьеров
                state.set(SaleStates.avito_message)
                state.add_data(avito_photo=avito_photo)
                state.add_data(order_id=order_id)
                state.add_data(avito_message=order_message)
                state.add_data(reply_message_id=reply_message_id)

                # Отправляем сообщение в личный чат
                bot.send_message(chat_id, order_message)

                # Уведомляем курьеров сразу после обновления состояния
                notify_couriers(message=None, state=state)

            except Exception as e:
                bot.send_message(chat_id, f"Произошла ошибка при оформлении заказа: {str(e)}")
        else:
            bot.send_message(chat_id, "Произошла ошибка при оформлении заказа. Пожалуйста, попробуйте снова.")


def notify_order_completion(order_id, courier_name, courier_username, photo_path):
    """Уведомляем канал о завершении заказа, отвечая на сообщение с заказом."""
    # Загружаем reply_to_message_id из базы данных или Redis
    chat_id = CHANNEL_CHAT_ID
    reply_to_message_id = load_user_state(order_id).get('reply_to_message_id')

    if reply_to_message_id:
        # Отправляем ответ на сообщение о заказе в канал с прикрепленной накладной
        completion_message = f"Заказ #{order_id}\nАвито продажа реализована\nНакладная:"
        bot.send_photo(chat_id, open(photo_path, 'rb'), caption=completion_message, reply_to_message_id=reply_to_message_id)
    else:
        bot.send_message(chat_id, f"Не удалось найти сообщение о заказе #{order_id} для ответа.")


# def notify_couriers(order_message, avito_photo):
#     couriers = get_couriers()  # Получаем список пользователей с ролью Courier
#     print(couriers)
#     print('couriers')
#     for courier in couriers:
#         markup = types.InlineKeyboardMarkup()
#         markup.add(types.InlineKeyboardButton("Принять заказ", callback_data=f"accept_order_{courier['telegram_id']}"))
#
#         # bot.send_photo(courier['telegram_id'], open(avito_photo, 'rb'), caption=order_message, reply_markup=markup)
