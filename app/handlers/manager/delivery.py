from bot import bot
from telebot import types
from telebot.states.sync.context import StateContext

from states import DeliveryStates

from app_types import OrderType
from config import CHANNEL_CHAT_ID
from database import update_order_status, get_product_info, create_order, get_user_info
from utils import format_order_message

from states import DirectStates

from utils import  is_valid_command

from app_types import SaleType, SaleTypeRu

from handlers.courier.courier import notify_couriers
from handlers.manager.avito import notify_all_users

from database import get_product_info_with_params

from database import update_order_message_id


# @bot.callback_query_handler(func=lambda call: call.data == 'sale_delivery', state=DirectStates.sale_type)
def handle_sale_delivery(call: types.CallbackQuery, state: StateContext):
    if not is_valid_command(call.message.text, state): return
    state.add_data(sale_type="delivery")
    bot.send_message(call.message.chat.id, "Введите дату доставки (в формате: YYYY-MM-DD):")
    state.set(DeliveryStates.delivery_date)

@bot.message_handler(state=DeliveryStates.delivery_date, func=lambda message: True)
def handle_delivery_date(message: types.Message, state: StateContext):
    if not is_valid_command(message.text, state): return
    state.add_data(delivery_date=message.text)
    bot.send_message(message.chat.id, "Введите время доставки (например: 9:00 - 12:00):")
    state.set(DeliveryStates.delivery_time)

@bot.message_handler(state=DeliveryStates.delivery_time, func=lambda message: True)
def handle_delivery_time(message: types.Message, state: StateContext):
    if not is_valid_command(message.text, state): return
    state.add_data(delivery_time=message.text)
    bot.send_message(message.chat.id, "Введите адрес доставки:")
    state.set(DeliveryStates.delivery_address)

# @bot.message_handler(state=DeliveryStates.delivery_address, func=lambda message: True)
# def handle_delivery_address(message: types.Message, state: StateContext):
#     state.add_data(delivery_address=message.text)
#     # bot.send_message(message.chat.id, "Введите заметку (или нажмите 'Пропустить'):")
#     # markup = types.InlineKeyboardMarkup()
#     # markup.add(types.InlineKeyboardButton("Пропустить", callback_data="skip_note"))
#     # bot.send_message(message.chat.id, "Заметка:", reply_markup=markup)
#     state.set(DeliveryStates.delivery_note)

# @bot.callback_query_handler(func=lambda call: call.data == 'skip_note', state=DeliveryStates.delivery_note)
# def skip_delivery_note(call: types.CallbackQuery, state: StateContext):
#     state.add_data(delivery_note=None)
#     ask_for_contact_info(call.message.chat.id, state)

@bot.message_handler(state=DeliveryStates.delivery_address, func=lambda message: True)
def handle_delivery_note(message: types.Message, state: StateContext):
    if not is_valid_command(message.text, state): return
    state.add_data(delivery_address=message.text)
    ask_for_contact_info(message, state)

def ask_for_contact_info(message, state):
    if not is_valid_command(message.text, state): return
    bot.send_message(message.chat.id, "Введите контактный телефон:")
    state.set(DeliveryStates.contact_phone)

@bot.message_handler(state=DeliveryStates.contact_phone, func=lambda message: True)
def handle_contact_phone(message: types.Message, state: StateContext):
    if not is_valid_command(message.text, state): return
    state.add_data(contact_phone=message.text)
    bot.send_message(message.chat.id, "Введите имя контактного лица:")
    state.set(DeliveryStates.contact_name)

@bot.message_handler(state=DeliveryStates.contact_name, func=lambda message: True)
def handle_contact_name(message: types.Message, state: StateContext):
    if not is_valid_command(message.text, state): return
    state.add_data(contact_name=message.text)
    bot.send_message(message.chat.id, "Введите сумму для оплаты:")
    state.set(DeliveryStates.total_amount)

@bot.message_handler(state=DeliveryStates.total_amount, func=lambda message: True)
def handle_total_amount(message: types.Message, state: StateContext):
    if not is_valid_command(message.text,state): return
    try:
        total_amount = float(message.text)
        state.add_data(total_amount=total_amount)
        # Завершаем процесс оформления заказа
        finalize_order(message.chat.id, message.from_user.username, message.message_id, state)
    except ValueError:
        bot.send_message(message.chat.id, "Некорректный формат суммы. Пожалуйста, введите число.")


def finalize_order(chat_id, username, message_id, state: StateContext):
    with state.data() as order_data:
        if order_data:
            param_id = order_data.get("param_id")
            product_id = order_data.get("product_id")
            gift = order_data.get("gift")
            note = order_data.get("note")
            sale_type = order_data.get("sale_type")
            delivery_date = order_data.get("delivery_date")
            delivery_time = order_data.get("delivery_time")
            delivery_address = order_data.get("delivery_address")
            delivery_note = order_data.get("delivery_note")
            contact_phone = order_data.get("contact_phone")
            contact_name = order_data.get("contact_name")
            total_amount = order_data.get("total_amount")
            packer_id = order_data.get("pack_id")

            if not all([param_id, product_id, sale_type]):
                bot.send_message(chat_id,
                                 "Не хватает данных для оформления заказа. Пожалуйста, начните процесс заново.")
                return

            try:
                manager_info = get_user_info(username)
                if not manager_info:
                    bot.send_message(chat_id, "Не удалось получить информацию о менеджере.")
                    return

                manager_id = manager_info['id']

                product_info = get_product_info_with_params(product_id)
                param_type = product_info.get("param_parameters", {}).get("Тип", None)

                need_to_pack = param_type and param_type.lower() == 'Китай'.lower()

                # if packer_id == manager_id:
                #     order_status = OrderType.IN_PACKING.value
                # elif not packer_id and need_to_pack == True:
                #     order_status = OrderType.ACTIVE.value
                # else:
                #     order_status = OrderType.READY_TO_DELIVERY.value
                order_status = OrderType.READY_TO_DELIVERY.value

                order_id = create_order(
                    product_id, param_id, gift, note, sale_type, manager_id, message_id,None,None,order_status,
                    delivery_date, delivery_time, delivery_address, delivery_note,
                    contact_phone, contact_name, total_amount
                )


                # update_order_status(order_id, OrderType.CLOSED.value)
                product_name, product_param = get_product_info(product_id=product_id, param_id=param_id)
                order_message = format_order_message(
                    order_id, product_name, product_param, gift, note, SaleTypeRu.DELIVERY.value,
                    manager_info['name'], manager_info['username'],
                    delivery_date=delivery_date, delivery_time=delivery_time, delivery_address=delivery_address, contact_phone=contact_phone, contact_name=contact_name, total_price=total_amount
                )

                # # Формируем сообщение с информацией о заказе
                # if packer_id == manager_id and order_status == OrderType.ACTIVE.value:
                #     pack_message = f"Упакует {manager_info['name']} ({manager_info['username']})"
                #     update_order_status(order_id, OrderType.IN_PACKING.value)
                # elif order_status == OrderType.ACTIVE.value:
                #     pack_message = "Упаковщик еще не выбран"
                # else:
                #     pack_message = "Не требует упаковки"

                # order_message += f"\n\n{pack_message}"

                bot.send_message(chat_id, order_message)
                sent_message = bot.send_message(CHANNEL_CHAT_ID, order_message)
                reply_message_id = sent_message.message_id
                update_order_message_id(order_id, reply_message_id)


                if not packer_id and  order_status==OrderType.ACTIVE.value:
                    # Если упаковщик не выбран, оповещаем всех пользователей
                    notify_all_users(order_message, order_id,reply_message_id,state)
                else:
                    # Уведомляем курьеров сразу после обновления состояния
                    notify_couriers(order_message,None,reply_message_id, state=state)


                # decrement_stock(product_id=product_id, product_param_id=param_id, order_id=order_id)
                state.delete()
            except Exception as e:
                bot.send_message(chat_id, f"Произошла ошибка при оформлении заказа: {str(e)}")
        else:
            bot.send_message(chat_id, "Произошла ошибка при оформлении заказа. Пожалуйста, попробуйте снова.")
