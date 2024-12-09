import telebot
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

from handlers.manager.avito import finalize_avito_order
from handlers.manager.sale import finalize_order

from utils import create_media_group

from database import get_avito_photos

from handlers.manager.delivery import finalize_delivery_order

from app_types import OrderTypeRu
import handlers.transfer

from database import check_order_packing

from database import get_connection

from database import handle_pack_tracking

from database import get_order_packing_status

from database import update_order_packing_stats

from database import get_showroom_visit

from utils import is_valid_command

from database import get_active_showroom_visits

from handlers.handlers import delete_multiple_states
from states import DirectStates

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
        a = bot.delete_my_commands(scope=types.BotCommandScopeChat(message.chat.id))

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
        set_admin_commands(bot,message)
    else:
        general_command = [types.BotCommand("/restart", "Перезапустить бота"),types.BotCommand("/transfer", "Передать заказ")]
        bot.set_my_commands(general_command,scope=types.BotCommandScopeChat(message.chat.id))
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(*available_buttons)
    bot.send_message(message.chat.id, f"Добро пожаловать, {user_access['name']}!", reply_markup=markup)
    manager_markdown = '\n\n*\#Продажа* отвечает за создание заказа' if "Manager" in user_access['roles'] else ''
    courier_markdown = '\n\n*\#Доставка* отвечает за работу с доставкой товара, построение маршрутов и истории поездок' if "Courier" in user_access['roles'] else ''
    bot.send_message(message.chat.id, f"По значку *слева* от микрофона вам откроется панель действий\!{manager_markdown}{courier_markdown}\n\n*\#Заказы* для просмотра истории и работой с упаковкой товаров", parse_mode='MarkdownV2')
    bot.send_message(message.chat.id, f"Также слева вы найдете кнопку *Меню*, через нее вы можете _перезагрузить бота_ или _передать заказ или доставку_ другому пользователю", parse_mode='MarkdownV2')
    bot.send_message(message.chat.id, f"Если вдруг у вас случилась ошибка, вот ваши действия\n1\. Перезагрузить бота\(кнопка в меню\)\. Для корректной работы может потребоваться *нажать 2 раза*\n2\. Если ошибка не ушла, написать команду *\/start* в чат с ботом\.\n3\. Обратиться ко мне за помощью, @ni3omi\(Леша\)", parse_mode='MarkdownV2')

@bot.message_handler(func=lambda message: message.text == '#Заказы')

def handle_orders(message: types.Message, state: StateContext):

    user_info = get_user_by_username(message.from_user.username, state)  # Получаем информацию о пользователе

    markup = types.InlineKeyboardMarkup()
    # Общие кнопки для всех ролей
    markup.add(types.InlineKeyboardButton("История заказов", callback_data='orders_show_history'))
    # markup.add(types.InlineKeyboardButton("Взять в упаковку", callback_data='orders_pack_goods'))
    markup.add(types.InlineKeyboardButton("Упаковка товара", callback_data='orders_pack'))
    markup.add(types.InlineKeyboardButton("Продажи в шоуруме", callback_data='orders_show_showroom'))

    # Дополнительные кнопки для курьеров

    state.set(AppStates.picked_action)
    bot.send_message(message.chat.id, "Вы попали в меню *заказов\!*\n\nЕсли вы хотите посмотреть _историю продаж или упаковки_, нажмите *История заказов*\n\nЕсли вы хотите упаковать товар, нажмите *Упаковка товара*", parse_mode="MarkdownV2", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == 'orders_pack')
def handle_orders_pack(call: types.CallbackQuery,state: StateContext):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Взять в упаковку", callback_data='orders_pack_goods'))
    markup.add(types.InlineKeyboardButton("Мои заказы(в упаковке)", callback_data='orders_in_packing'))
    state.set(AppStates.picked_action)
    bot.send_message(call.message.chat.id, "Если вы хотите взять заказ в упаковку, нажмите *Взять в упаковку*\n\nЕсли хотите посмотреть ваши заказы, которые находятся на упаковке \- *Мои заказы\(в упаковке\)*\n\nОбратите внимание: Если вы считаете, что упаковали товар, вы должны нажать кнопку *Упаковать товар*\(появится после нажатия на *Взять в упаковку*\)", parse_mode="MarkdownV2", reply_markup=markup)

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
    state.add_data(start_date=start_date.strftime("%Y-%m-%d"), end_date=end_date.strftime("%Y-%m-%d"))

    # Показываем кнопки для истории заказов
    markup = types.InlineKeyboardMarkup()
    user_info = get_user_by_username(message.from_user.username, state)
    markup.add(
        types.InlineKeyboardButton("Упакованные заказы", callback_data='orders_packed'),
        types.InlineKeyboardButton("Оформленные заказы", callback_data='orders_created')
    )

    bot.send_message(message.chat.id, "Выберите тип истории заказов:", reply_markup=markup)
    state.set(AppStates.start_date)


@bot.callback_query_handler(func=lambda call: call.data == 'orders_created', state=AppStates.start_date)
def show_created_orders(call: types.CallbackQuery, state: StateContext):
    with state.data() as data:
        start_date = data['start_date']
        end_date = data['end_date']

    user_info = get_user_by_username(call.from_user.username, state)

    # Получаем все заказы пользователя за период
    orders = get_orders(
        order_type=['avito', 'delivery', 'direct'],
        username=call.message.json['chat']['username'],
        start_date=start_date,
        end_date=end_date,
        status=['active','closed','in_delivery','in_packing','ready_to_delivery','refund','partly_delivered'],
        role='manager'  # Указываем роль manager для получения созданных заказов
    )

    if not orders:
        bot.send_message(call.message.chat.id, "За данный период не найдено оформленных заказов")
        return

    for order in orders:
        try:
            order_message = format_order_message(
                order_id=order['id'],
                product_list=order['products'].get('no_track', []).get('products') if order['order_type'] != 'avito' else order['products'],
                gift=order['gift'],
                note=order['note'],
                hide_track_prices=True,
                sale_type=order['order_type'],
                manager_name=order['manager_name'],
                manager_username=order['manager_username'],
                delivery_date=order.get('delivery_date'),
                delivery_time=order.get('delivery_time'),
                delivery_address=order.get('delivery_address'),
                contact_phone=order.get('contact_phone'),
                contact_name=order.get('contact_name'),
                total_price=order.get('total_price'),
                avito_boxes=order.get('avito_boxes')
            )
            bot.send_message(call.message.chat.id,
                             f"{order_message}\nСтатус: {OrderTypeRu[order['status'].upper()].value}")

        except Exception as e:
            print(f"Error processing order {order['id']}: {str(e)}")
            continue

# Обработчик упакованных заказов
@bot.callback_query_handler(func=lambda call: call.data == 'orders_packed', state=AppStates.start_date)
def show_packed_orders(call: types.CallbackQuery, state: StateContext):
    with state.data() as data:
        start_date = data['start_date']
        end_date = data['end_date']
    user_info = get_user_by_username(call.from_user.username, state)
    orders = get_orders(username=call.from_user.username, order_type=[SaleType.DIRECT.value,SaleType.DELIVERY.value,SaleType.AVITO.value],
                        role='packer',
                        status=['active', 'closed', 'in_delivery', 'in_packing', 'ready_to_delivery', 'refund',
                                'partly_delivered'], start_date=start_date,
                        end_date=end_date)
    if not orders:
        bot.send_message(call.message.chat.id, "За данный период не найдено упакованных заказов")

    for order in orders:
        try:
            order_message = format_order_message(
                order_id=order['id'],
                product_list=order['products'].get('no_track', []).get('products') if order[
                                                                                          'order_type'] != 'avito' else
                order['products'],
                gift=order['gift'],
                note=order['note'],
                hide_track_prices=True,
                sale_type=order['order_type'],
                manager_name=order['manager_name'],
                manager_username=order['manager_username'],
                packer_name=order['packer_name'],
                packer_username=order['packer_username'],
                delivery_date=order.get('delivery_date'),
                delivery_time=order.get('delivery_time'),
                delivery_address=order.get('delivery_address'),
                contact_phone=order.get('contact_phone'),
                contact_name=order.get('contact_name'),
                total_price=order.get('total_price'),
                avito_boxes=order.get('avito_boxes')
            )
            bot.send_message(call.message.chat.id,
                             f"{order_message}\nСтатус: {OrderTypeRu[order['status'].upper()].value}")
        except Exception as e:
            print(f"Error processing order {order['id']}: {str(e)}")
            continue


@bot.callback_query_handler(func=lambda call: call.data == 'orders_pack_goods')
def show_active_orders_without_packer(call: types.CallbackQuery, state: StateContext):
    orders = get_active_orders_without_packer()

    if not orders:
        bot.send_message(call.message.chat.id, "Нет активных заказов без упаковщика.")
        return

    for order in orders:
        try:
            # Проверяем необходимость упаковки
            # needs_packing, reason = check_order_packing(order['id'])

            order_message = format_order_message(
                order_id=order['id'],
                product_list=order['products'].get('no_track', []).get('products')
                if order['order_type'] != 'avito' else order['products'],
                gift=order['gift'],
                note=order['note'],
                sale_type=order['order_type'],
                manager_name=order['manager_name'],
                manager_username=order['manager_username'],
                total_price=order['total_price'],
                avito_boxes=order['avito_boxes'] if order['order_type'] == 'avito' else None
            )

            # Добавляем информацию об упаковке
            # if needs_packing:
            #     packing_info = "⚠️ Обязательная упаковка всех трек-номеров"
            # else:
            #     packing_info = "📦 Необходима проверка упаковки трек-номеров"
            #
            # order_message += f"\n\n{packing_info}\n{reason}"

            # Получаем статус упаковки
            all_processed, stats = get_order_packing_status(order['id'])
            if stats:
                order_message += f"\n\nСтатус упаковки:\n" \
                                 f"Обработано трек-номеров: {stats['packed'] + stats['skipped']}/{stats['total']}"

            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton(
                "📦 Взять в упаковку",
                callback_data=f"pack_order_{order['id']}_{order['message_id']}"
            ))

            bot.send_message(
                call.message.chat.id,
                order_message,
                reply_markup=markup
            )

        except Exception as e:
            print(f"Error processing order {order['id']}: {str(e)}")
            continue


@bot.callback_query_handler(func=lambda call: call.data.startswith('pack_goods_'))
def handle_pack_goods(call: types.CallbackQuery, state: StateContext,reply_message=None):
    order_id = call.data.split('_')[2]
    message_to_reply = reply_message if reply_message!='None' else call.data.split('_')[3]

    # Получаем заказ
    order = get_order_by_id(order_id)
    if not order:
        bot.answer_callback_query(call.id, "Заказ не найден")
        return

    # Получаем информацию о текущем пользователе
    user_info = get_user_by_username(call.from_user.username, state)
    if not user_info:
        bot.answer_callback_query(call.id, "Ошибка: не удалось получить информацию о пользователе")
        return

    # Проверяем, не назначен ли уже упаковщик
    if not order['packer_id']:
        # Обновляем packer_id только если он еще не установлен
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE orders 
                    SET packer_id = %s,
                        status = 'in_packing'::status_order
                    WHERE id = %s AND packer_id IS NULL
                    RETURNING id
                """, [user_info['id'], order_id])
            try:
                if cursor.fetchone():
                    # Отправляем уведомление в канал только при первом назначении упаковщика
                    reply_params = ReplyParameters(message_id=int(order.get('message_id')))
                    bot.send_message(
                        CHANNEL_CHAT_ID,
                        f"Заказ #{str(order_id).zfill(4)}ㅤ взят в упаковку\n"
                        f"Упаковщик: {user_info['name']} (@{user_info['username']})",
                        reply_parameters=reply_params
                    )
            except telebot.apihelper.ApiTelegramException as e:
                if e.error_code == 400 and "message to be replied not found" in e.description:
                    # Если сообщение не найдено, отправляем без reply
                    bot.send_message(
                        CHANNEL_CHAT_ID,
                        f"Заказ #{str(order_id).zfill(4)}ㅤ взят в упаковку\n"
                        f"Упаковщик: {user_info['name']} (@{user_info['username']})",
                    )
            

    # Создаем клавиатуру для каждого трек-номера
    markup = types.InlineKeyboardMarkup(row_width=1)

    with get_connection() as conn:
        with conn.cursor() as cursor:
            for tracking_number in order['products'].keys():
                cursor.execute("""
                    SELECT packing_status, 
                           CASE 
                               WHEN EXISTS (
                                   SELECT 1 
                                   FROM order_items oi 
                                   JOIN products p ON oi.product_id = p.id 
                                   JOIN suppliers s ON p.supplier_id = s.id
                                   WHERE oi.order_id = %s 
                                   AND oi.tracking_number = %s 
                                   AND s.country = 'russia'
                               ) THEN true 
                               ELSE false 
                           END as needs_packing
                    FROM avito_photos
                    WHERE order_id = %s AND tracking_number = %s
                """, [order_id, tracking_number, order_id, tracking_number])

                result = cursor.fetchone()

                if result:
                    packing_status, needs_packing = result
                    # Показываем кнопку если статус pending или in_packing
                    if packing_status in ('pending', 'in_packing'):
                        btn_text = f"{'⚠️' if needs_packing else '📦'} {tracking_number}"
                        products_info = []
                        # Добавляем информацию о продуктах в трек-номере
                        for product in order['products'][tracking_number]['products']:
                            products_info.append(f"[{product['name']}] [{product['param']}]")
                        products_str = "\n".join(products_info)

                        markup.add(types.InlineKeyboardButton(
                            btn_text,
                            callback_data=f"pack_tracking_{order_id}_{tracking_number}_{int(order.get('message_id'))}"
                        ))

            # Получаем статистику обработки
            cursor.execute("""
                   SELECT 
                       COUNT(*) as total,
                       COUNT(*) FILTER (WHERE packing_status = 'closed') as packed,
                       COUNT(*) FILTER (WHERE packing_status = 'skipped') as skipped
                   FROM avito_photos
                   WHERE order_id = %s
               """, [order_id])
            stats = cursor.fetchone()
    if len(markup.keyboard) > 0:

        status_text = (
            f"📊 Статистика обработки:\n"
            f"Всего трек-номеров: {stats[0]}\n"
            f"Упаковано: {stats[1]}\n"
            f"Пропущено: {stats[2]}\n\n"
            f"Выберите трек-номер для проверки:\n"
            f"⚠️ - российский товар (обязательная упаковка)\n"
            f"📦 - китайский товар (требует проверки)"
        )

        bot.edit_message_text(
            status_text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
    else:
        bot.edit_message_text(
            "Все трек-номера обработаны\n\n",
            call.message.chat.id,
            call.message.message_id
        )


@bot.callback_query_handler(func=lambda call: call.data == 'orders_in_packing')
def show_packing_orders(call: types.CallbackQuery, state: StateContext):
    user_info = get_user_by_username(call.from_user.username, state)
    # Получаем все заказы со статусом in_packing, где текущий пользователь является packer_id
    orders = get_orders(
        status=[OrderType.IN_PACKING.value],
        order_type=[SaleType.DELIVERY.value, SaleType.AVITO.value],
        username=user_info['username'],
        role='packer'
    )

    if not orders:
        bot.send_message(call.message.chat.id, "У вас нет заказов в упаковке.")
        return
    for order in orders:
        try:
            if order['order_type'] == 'delivery':
                print('delivery')
            print(order,1)
            order_message = format_order_message(
                order_id=order['id'],
                product_list=order['products'].get('no_track', []).get('products') if order[
                                                                                          'order_type'] != 'avito' else
                order['products'],
                gift=order['gift'],
                note=order['note'],
                sale_type=order['order_type'],
                manager_name=order['manager_name'],
                manager_username=order['manager_username'],
                total_price=order['total_price'],
                avito_boxes=order['avito_boxes'] if order['order_type'] == 'avito' else None,
                delivery_date=order.get('delivery_date'),
                delivery_time=order.get('delivery_time'),
                delivery_address=order.get('delivery_address'),
                contact_phone=order.get('contact_phone'),
                contact_name=order.get('contact_name'),
                hide_track_prices=True

            )
            print(order,2)
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton(
                "📦 Упаковать товар !!!",
                callback_data=f"pack_goods_{order['id']}_{order['message_id']}"
            ))

            if order['order_type'] == 'avito':
                # Получаем фотографии для Авито заказа
                print('photos',1)
                photos = get_avito_photos(order['id'])
                print('photos',photos,2)

                if photos:
                    media = create_media_group(photos, order_message)
                    bot.send_media_group(call.message.chat.id, media)
                    print('photos', 3)

                    bot.send_message(call.message.chat.id, "Если вы хотите упаковать этот заказ, нажмите на кнопку ниже:", reply_markup=markup)
                else:
                    bot.send_message(call.message.chat.id, order_message, reply_markup=markup)
            else:
                bot.send_message(call.message.chat.id, order_message, reply_markup=markup)

        except Exception as e:
            print(f"Error processing order {order['id']}: {str(e)}")
            continue

    state.set(AppStates.picked_action)

# @bot.callback_query_handler(func=lambda call: call.data.startswith('pack_goods_'))
# def handle_pack_goods(call: types.CallbackQuery):
#     # order_id = call.data.split('_')[2]
#     # message_to_reply = call.data.split('_')[3]
#     #
#     # # Сообщение с проверкой комплектации
#     # markup = types.InlineKeyboardMarkup()
#     # markup.add(types.InlineKeyboardButton("Упаковал", callback_data=f"packed_{order_id}_{message_to_reply}"))
#     #
#     # bot.edit_message_text( "Проверьте, что вы положили:\n1. Подставка с 3 болтами\n2. Ярусы елки\n3. Подарок\n4. Допники", call.message.chat.id, call.message.message_id, reply_markup=markup)
#     @bot.callback_query_handler(func=lambda call: call.data.startswith('pack_goods_'))
# def handle_pack_goods(call: types.CallbackQuery, state: StateContext):
#     order_id = call.data.split('_')[2]
#
#     # Получаем заказ
#     order = get_order_by_id(order_id)
#     if not order:
#         bot.answer_callback_query(call.id, "Заказ не найден")
#         return
#
#     # Создаем клавиатуру для каждого трек-номера
#     markup = types.InlineKeyboardMarkup(row_width=1)
#
#     for tracking_number in order['products'].keys():
#         # Проверяем статус упаковки
#         with get_connection() as conn:
#             with conn.cursor() as cursor:
#                 cursor.execute("""
#                     SELECT needs_packing, is_packed
#                     FROM tracking_package_status
#                     WHERE order_id = %s AND tracking_number = %s
#                 """, [order_id, tracking_number])
#                 status = cursor.fetchone()
#
#                 if status:
#                     needs_packing, is_packed = status
#                     if not is_packed:  # Показываем только неупакованные трек-номера
#                         btn_text = f"{'⚠️' if needs_packing else '📦'} Трек-номер: {tracking_number}"
#                         markup.add(types.InlineKeyboardButton(
#                             btn_text,
#                             callback_data=f"pack_tracking_{order_id}_{tracking_number}"
#                         ))
#     #
#     # if len(markup.keyboard) > 0:
#     #     markup.add(types.InlineKeyboardButton(
#     #         "✅ Завершить упаковку",
#     #         callback_data=f"finish_packing_{order_id}"
#     #     ))
#
#         bot.edit_message_text(
#             "Выберите трек-номер для упаковки:\n"
#             "⚠️ - обязательная упаковка\n"
#             "📦 - требует проверки",
#             call.message.chat.id,
#             call.message.message_id,
#             reply_markup=markup
#         )
#     else:
#         bot.edit_message_text(
#             "Все трек-номера обработаны",
#             call.message.chat.id,
#             call.message.message_id
#         )
#         # handle_packing_completion(order_id, message_to_reply, call.message.chat.id)


def handle_packing_completion(order_id: int, message_to_reply: str, chat_id: int):
    """Обработка завершения упаковки всего заказа"""
    try:
        order = get_order_by_id(order_id)
        if not order:
            raise ValueError("Заказ не найден")

        # Проверяем все ли трек-номера обработаны
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT COUNT(*) as total_boxes,
                           COUNT(*) FILTER (WHERE is_packed = true) as packed_boxes
                    FROM tracking_package_status
                    WHERE order_id = %s
                """, [order_id])
                counts = cursor.fetchone()
                if not counts or counts[0] != counts[1]:
                    raise ValueError("Не все трек-номера обработаны")

                # Обновляем статус заказа
                cursor.execute("""
                    UPDATE orders 
                    SET status = 'ready_to_delivery'::status_order,
                        packed_boxes_count = %s
                    WHERE id = %s
                """, [counts[1], order_id])

        # Формируем сообщение
        order_message = format_order_message(
            order_id=order['id'],
            product_list=order['products'],
            gift=order['gift'],
            note=order['note'],
            sale_type=order['order_type'],
            manager_name=order['manager_name'],
            manager_username=order['manager_username'],
            total_price=order['total_price'],
            avito_boxes=counts[1],  # Используем фактическое количество упакованных коробок
            hide_track_prices=True
        )

        # Получаем фотографии для Авито
        photos = get_avito_photos(order_id) if order['order_type'] == 'avito' else None

        # Уведомляем курьеров
        notify_couriers(order_message, None, avito_photos=photos, reply_message_id=message_to_reply)

        bot.send_message(
            chat_id,
            f"✅ Заказ #{str(order_id).zfill(4)} успешно упакован\n"
            f"Упаковано коробок: {counts[1]}"
        )

    except Exception as e:
        bot.send_message(chat_id, f"❌ Ошибка при завершении упаковки: {str(e)}")
@bot.callback_query_handler(func=lambda call: call.data.startswith('packed_'))
def handle_packed_order(call: types.CallbackQuery, state: StateContext):
   """
   Обработчик завершения упаковки заказа
   """
   order_id = call.data.split('_')[1]
   message_to_reply = call.data.split('_')[2]
   user_info = get_user_by_username(call.from_user.username, state)
   order_data = get_order_by_id(int(order_id))

   if not order_data:
       bot.answer_callback_query(call.id, "Ошибка: заказ не найден")
       return

   try:
       # Обновляем статус заказа
       update_order_status(order_id, 'ready_to_delivery')

       # Формируем сообщение для курьеров
       order_message = format_order_message(
           order_id=order_data['id'],
           product_list=order_data['products'],
           gift=order_data['gift'],
           note=order_data['note'],
           sale_type=order_data['order_type'],
           manager_name=order_data.get('manager_name', ''),
           manager_username=order_data.get('manager_username', ''),
           total_price=order_data['total_price'],
           avito_boxes=order_data.get('avito_boxes'),
           delivery_date=order_data.get('delivery_date'),
           delivery_time=order_data.get('delivery_time'),
           delivery_address=order_data.get('delivery_address'),
           delivery_note=order_data.get('delivery_note'),
           contact_phone=order_data.get('contact_phone'),
           contact_name=order_data.get('contact_name'),
           hide_track_prices=True  # Скрываем цены для курьеров
       )

       # Отправляем уведомление в основной чат
       try:
           reply_params = ReplyParameters(message_id=int(message_to_reply))
           bot.send_message(
               CHANNEL_CHAT_ID,
               f"Заказ #{str(order_id).zfill(4)}ㅤ \nУпакован\n"
               f"Упаковал: {user_info['name']} ({user_info['username']})",
               reply_parameters=reply_params)
       except telebot.apihelper.ApiTelegramException as e:
           if e.error_code == 400 and "message to be replied not found" in e.description:
               bot.send_message(
                   CHANNEL_CHAT_ID,
                   f"Заказ #{str(order_id).zfill(4)}ㅤ \nУпакован\n"
                   f"Упаковал: {user_info['name']} ({user_info['username']})",
               )

       # Обновляем сообщение упаковщику
       bot.edit_message_text(
           f"✅ Вы упаковали заказ #{str(order_id).zfill(4)}ㅤ",
           message_id=call.message.message_id,
           chat_id=call.message.chat.id
       )

       # Получаем фотографии для заказа Авито
       photos = None
       if order_data['order_type'] == 'avito':
           photos = get_avito_photos(order_id)

       # Уведомляем курьеров
       notify_couriers(
           order_message,
           state,
           avito_photos=photos if photos else None,
           reply_message_id=message_to_reply
       )

       bot.answer_callback_query(call.id, "✅ Заказ успешно упакован")

   except Exception as e:
       print(f"Error in handle_packed_order: {str(e)}")
       bot.answer_callback_query(call.id, "❌ Произошла ошибка при обработке заказа")


@bot.callback_query_handler(func=lambda call: call.data.startswith('pack_tracking_'))
def handle_tracking_packing(call: types.CallbackQuery):
    """Обработчик выбора трек-номера для упаковки"""
    _,_, order_id, tracking_number,message_to_reply = call.data.split('_')

    order = get_order_by_id(order_id)
    if not order or tracking_number not in order['products']:
        bot.answer_callback_query(call.id, "Ошибка: заказ или трек-номер не найден")
        return

    track_products = []
    for product in order['products'][tracking_number]['products']:
        track_products.append(f"{product['name']} {product['param']}")
    products_info = "\n".join(track_products)

    # Проверяем статус трек-номера
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                    UPDATE avito_photos 
                    SET packing_status = 'in_packing'
                    WHERE order_id = %s AND tracking_number = %s
                    RETURNING 1
                """, [order_id, tracking_number])

            # Проверяем наличие обязательной упаковки
            needs_packing, _ = check_order_packing(order_id,tracking_number=tracking_number)

    markup = types.InlineKeyboardMarkup(row_width=2)
    if needs_packing:
        # Если упаковка обязательна, показываем только кнопку подтверждения
        markup.add(types.InlineKeyboardButton(
            "✅ Подтвердить упаковку",
            callback_data=f"confirm_pack_{order_id}_{tracking_number}_{int(order.get('message_id'))}"
        ))
        message = "⚠️ Требуется обязательная упаковка"
    else:
        # Если упаковка необязательна, даем выбор
        markup.add(
            types.InlineKeyboardButton(
                "🔄 Переупаковать",
                callback_data=f"repack_pack_{order_id}_{tracking_number}_{int(order.get('message_id'))}"
            ),
            types.InlineKeyboardButton(
                "✅ Пропустить упаковку",
                callback_data=f"skip_pack_{order_id}_{tracking_number}_{int(order.get('message_id'))}"
            )
        )
        message = "📦 Проверьте необходимость упаковки"

    full_message = (
        f"Трек-номер: {tracking_number}\n"
        f"Продукты в трекномере:\n{products_info}\n\n"
        f"{message}"
    )

    markup.add(types.InlineKeyboardButton(
        "🔙 Вернуться к списку",
        callback_data=f"pack_goods_{order_id}_{message_to_reply}"
    ))

    bot.edit_message_text(
        full_message,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_pack_'))
def confirm_tracking_packing(call: types.CallbackQuery, state: StateContext):
    """Обработчик подтверждения упаковки трек-номера"""
    _,_, order_id, tracking_number,message_reply = call.data.split('_')

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                  UPDATE avito_photos 
                  SET packing_status = 'closed'
                  WHERE order_id = %s AND tracking_number = %s
              """, [order_id, tracking_number])

    # Обновляем статистику упаковки
    update_order_packing_stats(order_id)

    # Проверяем, все ли трек-номера обработаны
    all_processed, stats = get_order_packing_status(order_id)

    if all_processed:
        # Если все обработано, обновляем статус заказа
        update_order_status(order_id, 'ready_to_delivery')

        order_data = get_order_by_id(order_id)

        # Формируем сообщение для курьеров
        order_message = format_order_message(
            order_id=order_data['id'],
            product_list=order_data['products'],
            gift=order_data['gift'],
            note=order_data['note'],
            sale_type=order_data['order_type'],
            manager_name=order_data.get('manager_name', ''),
            manager_username=order_data.get('manager_username', ''),
            total_price=order_data['total_price'],
            avito_boxes=stats['packed'],  # Используем количество реально упакованных коробок
            hide_track_prices=True
        )

        # Получаем фотографии для Авито
        photos = get_avito_photos(order_id) if order_data['order_type'] == 'avito' else None

        # Уведомляем курьеров
        notify_couriers(
            order_message,
            state,
            avito_photos=photos,
            reply_message_id=order_data['message_id']
        )

        message = (
            f"✅ Трек-номер {tracking_number} упакован\n\n"
            f"📊 Статистика заказа:\n"
            f"Всего трек-номеров: {stats['total']}\n"
            f"Упаковано: {stats['packed']}\n"
            f"Пропущено: {stats['skipped']}\n\n"
            f"Заказ передан в доставку!"
        )
        try:
            reply_params = ReplyParameters(message_id=int(message_reply))
            bot.send_message(
                CHANNEL_CHAT_ID,
                f"Заказ #{str(order_id).zfill(4)}ㅤ готов к доставке!\n",
                reply_parameters=reply_params)
        except telebot.apihelper.ApiTelegramException as e:
            if e.error_code == 400 and "message to be replied not found" in e.description:
                # Если сообщение не найдено, отправляем без reply
                bot.send_message(
                    CHANNEL_CHAT_ID,
                    f"Заказ #{str(order_id).zfill(4)}ㅤ готов к доставке!\n",
                )
        # Если сообщение не найдено, отправляем без reply

        bot.edit_message_text(
            message,
            call.message.chat.id,
            call.message.message_id
        )
    else:
        message = f"✅ Трек-номер {tracking_number} упакован"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
            "🔙 Вернуться к списку",
            callback_data=f"pack_goods_{order_id}_{message_reply}"
        ))

    bot.edit_message_text(
        message,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup if not all_processed else None
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('skip_pack_'))
def skip_tracking_packing(call: types.CallbackQuery, state: StateContext):
    """Обработчик пропуска упаковки трек-номера"""
    _, _, order_id, tracking_number, reply_message = call.data.split('_')

    handle_pack_tracking(order_id, tracking_number, False, None)

    # Проверяем, все ли трек-номера обработаны
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                    SELECT 
                        COUNT(*) as total,
                        COUNT(*) FILTER (WHERE packing_status = 'pending' OR packing_status = 'in_packing') as pending,
                        COUNT(*) FILTER (WHERE packing_status = 'closed') as packed,
                        COUNT(*) FILTER (WHERE packing_status = 'skipped') as skipped
                    FROM avito_photos
                    WHERE order_id = %s
                """, [order_id])
            stats = cursor.fetchone()

            if stats[1] == 0:  # Если нет pending трек-номеров
                # Заказ полностью обработан
                update_order_status(order_id, 'ready_to_delivery')

                # Отправляем сообщение о завершении
                markup = None
                message_text = (
                    f"⏭️ Упаковка пропущена\n\n"
                    f"📊 Статистика заказа:\n"
                    f"Всего трек-номеров: {stats[0]}\n"
                    f"Упаковано: {stats[2]}\n"
                    f"Пропущено: {stats[3]}\n\n"
                    f"Заказ готов к доставке!"
                )

                bot.edit_message_text(
                    message_text,
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=markup
                )

                # Уведомляем курьеров
                order_data = get_order_by_id(order_id)
                if order_data:
                    order_message = format_order_message(
                        order_id=order_id,
                        product_list=order_data['products'],
                        gift=order_data['gift'],
                        note=order_data['note'],
                        sale_type=order_data['order_type'],
                        manager_name=order_data.get('manager_name', ''),
                        manager_username=order_data.get('manager_username', ''),
                        total_price=order_data['total_price'],
                        avito_boxes=stats[2],  # Используем количество упакованных коробок
                        hide_track_prices=True
                    )

                    photos = get_avito_photos(order_id)
                    notify_couriers(
                        order_message,
                        state,
                        avito_photos=photos,
                        reply_message_id=reply_message
                    )
            else:
                # Еще есть необработанные трек-номера
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton(
                    "🔙 Вернуться к списку",
                    callback_data=f"pack_goods_{order_id}_{reply_message}"
                ))
                message_text = f"Трек-номер {tracking_number} пропущен"

                bot.edit_message_text(
                    message_text,
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=markup
                )

    state.delete()

@bot.callback_query_handler(func=lambda call: call.data.startswith('repack_pack_'))
def repack_tracking_packing(call: types.CallbackQuery, state: StateContext):
    """Обработчик переупаковки трек-номера"""
    _, _, order_id, tracking_number, reply_message = call.data.split('_')

    # Сохраняем данные для последующей обработки
    state.add_data(
        pending_repack_order_id=order_id,
        pending_repack_tracking=tracking_number,
        pending_repack_reply_message=reply_message
    )

    bot.edit_message_text(
        f"Укажите причину переупаковки для трек-номера {tracking_number}:",
        call.message.chat.id,
        call.message.message_id
    )

    state.set(AppStates.enter_repack_reason)

@bot.message_handler(state=AppStates.enter_repack_reason)
def handle_repack_reason(message: types.Message, state: StateContext):
    """Обработчик ввода причины переупаковки"""
    with state.data() as data:
        order_id = data['pending_repack_order_id']
        tracking_number = data['pending_repack_tracking']
        reply_message = data.get('pending_repack_reply_message')

    # Обновляем статус и причину в базе
    handle_pack_tracking(order_id, tracking_number, True, message.text.strip())

    # Проверяем, все ли трек-номера обработаны
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE packing_status = 'pending' OR packing_status = 'in_packing') as pending,
                    COUNT(*) FILTER (WHERE packing_status = 'closed') as packed,
                    COUNT(*) FILTER (WHERE packing_status = 'skipped') as skipped
                FROM avito_photos
                WHERE order_id = %s
            """, [order_id])
            stats = cursor.fetchone()

            if stats[1] == 0:  # Если нет pending трек-номеров
                # Заказ полностью обработан
                update_order_status(order_id, 'ready_to_delivery')

                # Отправляем сообщение о завершении
                markup = None
                message_text = (
                    f"✅ Переупаковка выполнена\n\n"
                    f"📊 Статистика заказа:\n"
                    f"Всего трек-номеров: {stats[0]}\n"
                    f"Упаковано: {stats[2]}\n"
                    f"Пропущено: {stats[3]}\n\n"
                    f"Заказ готов к доставке!"
                )

                bot.send_message(
                    message.chat.id,
                    message_text,
                    reply_markup=markup
                )

                # Уведомляем курьеров
                order_data = get_order_by_id(order_id)
                if order_data:
                    order_message = format_order_message(
                        order_id=order_id,
                        product_list=order_data['products'],
                        gift=order_data['gift'],
                        note=order_data['note'],
                        sale_type=order_data['order_type'],
                        manager_name=order_data.get('manager_name', ''),
                        manager_username=order_data.get('manager_username', ''),
                        total_price=order_data['total_price'],
                        avito_boxes=stats[2],  # Используем количество упакованных коробок
                        hide_track_prices=True
                    )

                    photos = get_avito_photos(order_id)
                    notify_couriers(
                        order_message,
                        state,
                        avito_photos=photos,
                        reply_message_id=reply_message
                    )
            else:
                # Еще есть необработанные трек-номера
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton(
                    "🔙 Вернуться к списку",
                    callback_data=f"pack_goods_{order_id}_{reply_message}"
                ))
                message_text = f"Трек-номер {tracking_number} переупакован"

                bot.send_message(
                    message.chat.id,
                    message_text,
                    reply_markup=markup
                )

    state.delete()

@bot.message_handler(state=AppStates.enter_skip_reason)
def handle_skip_reason(message: types.Message, state: StateContext):
    """Обработчик ввода причины пропуска упаковки"""
    with state.data() as data:
        order_id = data['pending_skip_order_id']
        tracking_number = data['pending_skip_tracking']
        reply_message = data.get('pending_skip_reply_message')

    # Обновляем статус и причину в базе
    handle_pack_tracking(order_id, tracking_number, False, message.text.strip())

    # Проверяем, все ли трек-номера обработаны
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE packing_status = 'pending' OR packing_status = 'in_packing') as pending,
                    COUNT(*) FILTER (WHERE packing_status = 'closed') as packed,
                    COUNT(*) FILTER (WHERE packing_status = 'skipped') as skipped
                FROM avito_photos
                WHERE order_id = %s
            """, [order_id])
            stats = cursor.fetchone()

            if stats[1] == 0:  # Если нет pending трек-номеров
                # Заказ полностью обработан
                update_order_status(order_id, 'ready_to_delivery')

                # Отправляем сообщение о завершении
                markup = None
                message_text = (
                    f"⏭️ Упаковка пропущена\n\n"
                    f"📊 Статистика заказа:\n"
                    f"Всего трек-номеров: {stats[0]}\n"
                    f"Упаковано: {stats[2]}\n"
                    f"Пропущено: {stats[3]}\n\n"
                    f"Заказ готов к доставке!"
                )

                bot.send_message(
                    message.chat.id,
                    message_text,
                    reply_markup=markup
                )

                # Уведомляем курьеров
                order_data = get_order_by_id(order_id)
                if order_data:
                    order_message = format_order_message(
                        order_id=order_id,
                        product_list=order_data['products'],
                        gift=order_data['gift'],
                        note=order_data['note'],
                        sale_type=order_data['order_type'],
                        manager_name=order_data.get('manager_name', ''),
                        manager_username=order_data.get('manager_username', ''),
                        total_price=order_data['total_price'],
                        avito_boxes=stats[2],  # Используем количество упакованных коробок
                        hide_track_prices=True
                    )

                    photos = get_avito_photos(order_id)
                    notify_couriers(
                        order_message,
                        state,
                        avito_photos=photos,
                        reply_message_id=reply_message
                    )
            else:
                # Еще есть необработанные трек-номера
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton(
                    "🔙 Вернуться к списку",
                    callback_data=f"pack_goods_{order_id}_{reply_message}"
                ))
                message_text = f"Трек-номер {tracking_number} пропущен"

                bot.send_message(
                    message.chat.id,
                    message_text,
                    reply_markup=markup
                )

    state.delete()



@bot.callback_query_handler(func=lambda call: call.data == 'confirm_final_order')
def confirm_final_order(call: types.CallbackQuery, state: StateContext):
    with state.data() as data:
        sale_type = data.get('sale_type')
    bot.delete_message(call.message.chat.id, call.message.message_id)
    # В зависимости от типа заказа вызываем соответствующую финализирующую функцию
    if sale_type == "avito":
        finalize_avito_order(call.message.chat.id,call.message.message_id ,call.message.json['chat']['username'], state)
    elif sale_type == "delivery":
        finalize_delivery_order(call.message.chat.id,call.message.message_id ,call.message.json['chat']['username'],state)
    else:
        finalize_order(call.message.chat.id, call.from_user.username, call.message.message_id, state)

    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == 'orders_show_showroom')
def show_showroom_orders(call: types.CallbackQuery, state: StateContext):
    """Shows active showroom visits for user"""
    visits = get_active_showroom_visits(call.from_user.username)

    if not visits:
        bot.answer_callback_query(call.id, "Нет активных заявок на показ")
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    for visit in visits:
        button_text = f"⏳ {visit['created_at'].strftime('%d.%m.%Y')} - {visit['manager_name']}"
        markup.add(types.InlineKeyboardButton(
            button_text,
            callback_data=f"show_visit_{visit['id']}"
        ))

    bot.edit_message_text(
        "Активные заявки на показ:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('show_visit_'))
def handle_visit_selection(call: types.CallbackQuery, state: StateContext):
    """Handles showroom visit selection"""
    with state.data() as data:
        origin_visit_id = data.get('visit_id',None)
    visit_id = int(call.data.split('_')[2]) if not origin_visit_id else origin_visit_id
    visit_info = get_showroom_visit(visit_id)

    if not visit_info:
        bot.answer_callback_query(call.id, "Заявка не найдена")
        return
    state.add_data(visit_id=visit_id)
    viewer_markup = types.InlineKeyboardMarkup(row_width=1)
    viewer_markup.add(
        types.InlineKeyboardButton("Оформить продажу", callback_data=f"complete_visit_{visit_id}"),
        types.InlineKeyboardButton("Отказались от покупки", callback_data=f"cancel_visit_{visit_id}"),
        types.InlineKeyboardButton("« Назад", callback_data="orders_show_showroom")
    )

    message_text = (
        f"📅 Дата создания: {visit_info['created_at'].strftime('%d.%m.%Y')}\n"
        f"👤 Менеджер: {visit_info['manager_name']} ({visit_info['manager_username']})\n"
        f"👥 Покажет: {visit_info['viewer_name']} ({visit_info['viewer_username']})\n\n"
        f"📝 Заметка от менеджера:\n{visit_info['note']}"
    )

    bot.edit_message_text(
        message_text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=viewer_markup
    )

@bot.callback_query_handler(func=lambda call: call.data == "cancel_order")
def handle_cancel_order(call: types.CallbackQuery, state: StateContext):
    """
    Обработчик отмены заказа.
    Полностью сбрасывает состояние и начинает процесс оформления заново.
    """
    with state.data() as data:
        origin_manager_id = data.get('original_manager_id',None)
        visit_id = data.get('visit_id',None)
    # Удаляем текущее состояние

    # Начинаем процесс заново
    message_id = call.message.message_id
    chat_id = call.message.chat.id

    # Удаляем сообщение с подтверждением заказа
    if origin_manager_id and visit_id:
        handle_visit_selection(call,state)
        delete_multiple_states(state,['product_dict','original_manager_id','original_manager_name','original_manager_username'])
        return
    bot.delete_message(chat_id, message_id)

    # Начинаем с выбора типа продажи
    state.delete()

    state.set(DirectStates.sale_type)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Прямая", callback_data="sale_direct"))
    markup.add(types.InlineKeyboardButton("Доставка", callback_data="sale_delivery"))
    markup.add(types.InlineKeyboardButton("Авито", callback_data="sale_avito"))

    bot.send_message(chat_id, "Выберите тип продажи:\n\n", reply_markup=markup)

