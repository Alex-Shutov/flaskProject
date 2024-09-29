import uuid

from bot import get_bot_instance
from utils import UserRole, format_order_message, save_photo_and_resize
from database import check_user_access, get_products, get_product_params, create_order, get_manager_info, get_product_info,get_couriers
from handlers.sale import save_param_to_redis
from redis_client import save_user_state, load_user_state, delete_user_state

from config import CHANNEL_CHAT_ID

bot = get_bot_instance()

@bot.message_handler(func=lambda message: message.text == 'Авито')
def handle_avito_sale(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "Загрузите фото из личного кабинета Авито.")
    bot.register_next_step_handler(message, handle_avito_photo)


def handle_avito_photo(message):

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
        save_param_to_redis(chat_id, 'avito_photo', photo_path)

        finalize_avito_order(chat_id,message_id)
    else:
        bot.send_message(chat_id, "Пожалуйста, загрузите страницу заказа с Авито")
        bot.register_next_step_handler(message, handle_avito_photo)


def finalize_avito_order(chat_id,message_id):
    """Финализируем заказ для Авито, включая фото и ответ на сообщение в канале."""

    order_data = load_user_state(chat_id)
    if order_data:
        param_id = order_data.get("param_id")
        product_id = order_data.get("product_id")
        gift = order_data.get("gift")
        note = order_data.get("note")
        sale_type = "avito"
        avito_photo = order_data.get("avito_photo")

        if not all([param_id, product_id, sale_type, avito_photo]):
            bot.send_message(chat_id, "Не хватает данных для оформления заказа. Пожалуйста, начните процесс заново.")
            return

        try:
            manager_info = get_manager_info('ni3omi')
            if not manager_info:
                bot.send_message(chat_id, "Не удалось получить информацию о менеджере.")
                return

            manager_id, manager_name, manager_username = manager_info

            # Создаем заказ в БД и получаем order_id
            order_id = create_order(product_id, param_id, gift, note, sale_type, manager_id,message_id,avito_photo)

            product_name, product_param = get_product_info(product_id, param_id)

            order_message = format_order_message(order_id, product_name, product_param, gift, note, sale_type, manager_name, manager_username)

            # Отправляем сообщение в основной канал и сохраняем message_id для ответа
            sent_message = bot.send_photo(CHANNEL_CHAT_ID, open(avito_photo, 'rb'), caption=order_message)

            # Сохраняем reply_to_message_id (ID сообщения)
            reply_to_message_id = sent_message.message_id

            # Сохраняем reply_to_message_id в базе данных или Redis для использования в будущем
            save_param_to_redis(chat_id, 'reply_to_message_id', reply_to_message_id)

            # Отправляем сообщение в личный чат
            bot.send_message(chat_id, order_message)

            # Удаляем состояние после завершения заказа
            delete_user_state(chat_id)
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
def notify_couriers(order_message, avito_photo):
    couriers = get_couriers()  # Получаем список пользователей с ролью Courier
    for courier in couriers:
        bot.send_photo(courier['telegram_id'], open(avito_photo, 'rb'), caption=order_message)
        bot.send_message(courier['telegram_id'], "Нажмите 'Принять заказ', чтобы взять заказ.")