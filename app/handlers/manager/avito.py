import uuid
from telebot import types
from bot import get_bot_instance
from states import AvitoStates as SaleStates,DirectStates,CourierStates
from telebot.types import ReplyParameters
from utils import format_order_message, save_photo_and_resize
from database import check_user_access, get_products, get_product_params, create_order, get_user_info, get_product_info,get_couriers,update_order_message_id
from redis_client import save_user_state, load_user_state, delete_user_state
from telebot.states.sync.context import StateContext
from config import CHANNEL_CHAT_ID
from handlers.courier.courier import notify_couriers

from database import get_all_users

from database import update_order_status

from app_types import OrderType
from database import update_order_packer

from app_types import UserRole

from database import get_product_info_with_params

from states import AvitoStates
from utils import is_valid_command

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
        state.set(AvitoStates.total_price)
        # finalize_avito_order(chat_id,message_id,state)
    else:
        bot.send_message(chat_id, "Пожалуйста, загрузите страницу заказа с Авито")

@bot.message_handler(state=AvitoStates.total_price)
def handle_total_price(message:types.Message,state:StateContext):
    if not is_valid_command(message.text, state): return
    try:
        total_amount = float(message.text)
        state.add_data(total_price=total_amount)
        # Завершаем процесс оформления заказа
        finalize_avito_order(message.chat.id, message.message_id, state)
    except ValueError:
        bot.send_message(message.chat.id, "Некорректный формат суммы. Пожалуйста, введите число.")


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
            packer_id = order_data.get("pack_id")
            total_price = order_data.get("total_price")

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

                product_info = get_product_info_with_params(product_id)
                param_type = product_info.get("param_parameters", {}).get("Тип", None)

                need_to_pack = param_type and param_type.lower() == 'Китай'.lower()

                if packer_id==manager_id:
                    order_status = OrderType.IN_PACKING.value
                elif not packer_id and need_to_pack==True:
                    order_status = OrderType.ACTIVE.value
                else:
                    order_status = OrderType.READY_TO_DELIVERY.value

                # Создаем заказ в БД и получаем order_id
                order_id = create_order(product_id, param_id, gift, note, sale_type, manager_id, message_id,
                                        avito_photo, packer_id, order_status)



                product_name, product_param = get_product_info(product_id, param_id)

                # Формируем сообщение с информацией о заказе
                if packer_id == manager_id:
                    pack_message = f"Упакует {manager_name} ({manager_username})"
                elif order_status==OrderType.ACTIVE.value:
                    pack_message = "Упаковщик еще не выбран"
                else: pack_message="Не требует упаковки"

                order_message = format_order_message(
                    order_id, product_name, product_param, gift, note, sale_type, manager_name, manager_username
                ) + f"\n\n{pack_message}"

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
                if not packer_id and order_status==OrderType.ACTIVE.value:
                    # Если упаковщик не выбран, оповещаем всех пользователей
                    notify_all_users(order_message, order_id,reply_message_id,state)
                else:
                    # Уведомляем курьеров сразу после обновления состояния
                    notify_couriers(order_message,avito_photo,reply_message_id, state=state)
                state.delete()
            except Exception as e:
                bot.send_message(chat_id, f"Произошла ошибка при оформлении заказа: {str(e)}")
        else:
            bot.send_message(chat_id, "Произошла ошибка при оформлении заказа. Пожалуйста, попробуйте снова.")


def notify_all_users(order_message, order_id,message_to_reply,state):
    state.delete()
    users = get_all_users([UserRole.MANAGER.value,UserRole.COURIER.value,UserRole.ADMIN.value])
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Взять в упаковку", callback_data=f"pack_order_{order_id}_{message_to_reply}"))

    for user in users:
        bot.send_message(user['telegram_id'], order_message, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('pack_order_'))
def handle_pack_order(call: types.CallbackQuery):
    order_id = call.data.split('_')[2]
    message_to_reply = call.data.split('_')[3]
    user_info = get_user_info(call.from_user.username)

    if user_info:
        update_order_packer(order_id, user_info['id'])
        update_order_status(order_id, OrderType.IN_PACKING.value)

        # Проверяем, есть ли в сообщении фото (caption)
        if call.message.photo:
            # Меняем описание под фото
            bot.edit_message_caption(
                f"Вы выбрали упаковать заказ #{str(order_id).zfill(4)}ㅤ\nДанный заказ вы сможете найти по кнопке \"Упаковать товар\"",
                message_id=call.message.message_id,
                chat_id=call.message.chat.id
            )
        else:
            # Меняем текст сообщения
            bot.edit_message_text(
                f"Вы выбрали упаковать заказ #{str(order_id).zfill(4)}ㅤ\nДанный заказ вы сможете найти по кнопке \"Упаковать товар\"",
                message_id=call.message.message_id,
                chat_id=call.message.chat.id
            )
        reply_params = ReplyParameters(message_id=int(message_to_reply))
        # Отправляем сообщение в канал
        bot.send_message(
            CHANNEL_CHAT_ID,
            f"Заказ #{str(order_id).zfill(4)}ㅤ принят в упаковку \nУпакует {user_info['name']} ({user_info['username']})",
            reply_parameters=reply_params,
        )