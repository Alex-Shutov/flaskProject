import concurrent.futures
import re
import threading
import uuid
from io import BytesIO

from telebot import types
from bot import get_bot_instance
from states import AvitoStates as SaleStates,DirectStates,CourierStates
from telebot.types import ReplyParameters, InputMediaPhoto
from utils import format_order_message, save_photo_and_resize
from database import check_user_access, get_products, get_product_params, create_order, get_user_info, get_product_info,get_couriers,update_order_message_id
from redis_client import save_user_state, load_user_state, delete_user_state
from telebot.states.sync.context import StateContext
from config import CHANNEL_CHAT_ID
from handlers.courier.courier import notify_couriers
import pytesseract
from PIL import Image
from database import get_all_users

from database import update_order_status

from app_types import OrderType
from database import update_order_packer

from app_types import UserRole

from database import get_product_info_with_params

from states import AvitoStates
from utils import is_valid_command

from handlers.handlers import review_order_data

from utils import create_media_group

from handlers.handlers import process_product_stock

from handlers.handlers import delete_multiple_states

bot = get_bot_instance()

# @bot.message_handler(func=lambda message: message.text == 'Авито')
# def handle_avito_sale(message):
#     chat_id = message.chat.id
#     bot.send_message(chat_id, "Загрузите фото из личного кабинета Авито.")
#     bot.register_next_step_handler(message, handle_avito_photo)
@bot.message_handler(state=AvitoStates.avito_photo, content_types=['photo'])
def handle_avito_photo(message: types.Message, state: StateContext):
    chat_id = message.chat.id
    order_guid = str(uuid.uuid4())
    print(message)
    try:
        with state.data() as data:
            in_avito_photo=data.get('in_avito_photo',False)
        if in_avito_photo:
            # bot.send_message(chat_id, "Пожалуйста, загружайте только одну фотографию за раз.")
            raise Exception('Пожалуйста, загружайте только одну фотографию за раз.\nБудет обработано только первое фото')
        state.add_data(in_avito_photo=True)

        # if len(message.photo) > 1:
        #     bot.send_message(chat_id, "Пожалуйста, загружайте только одну фотографию за раз.")
        #     return  # Прерываем выполнение функции
        if message.photo:
            photo = message.photo[-1]
            file_info = bot.get_file(photo.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            photo_path = save_photo_and_resize(downloaded_file, order_guid)  # сохраняем фото
            state.add_data(avito_photo=photo_path)

            # Применяем OCR для извлечения текста с фотографии
            img = Image.open(photo_path)
            img_russian = img.copy()
            img_english = img.copy()

            # Результаты OCR для русского и английского текстов
            ocr_result_russian = [None]
            ocr_result_english = [None]

            # Функция для обработки OCR на русском
            def ocr_russian():
                ocr_result_russian[0] = pytesseract.image_to_string(img_russian, lang='rus')

            # Функция для обработки OCR на английском
            def ocr_english():
                ocr_result_english[0] = pytesseract.image_to_string(img_english, lang='eng')

            # Создаём два потока для параллельной работы
            russian_thread = threading.Thread(target=ocr_russian)
            english_thread = threading.Thread(target=ocr_english)

            # Запускаем потоки
            russian_thread.start()
            english_thread.start()

            # Ждём завершения обоих потоков
            russian_thread.join()
            english_thread.join()

            # Получаем результаты OCR
            russian_lines = ocr_result_russian[0].splitlines() if ocr_result_russian[0] else []
            english_lines = ocr_result_english[0].splitlines() if ocr_result_english[0] else []

            # Шаг 1: Найти ключевую строку в русском варианте
            keyword = "назовите этот номер"
            track_number = None
            second_colon_index = None

            # Поиск ключевой строки в русском тексте
            for i, line in enumerate(russian_lines):
                if keyword.lower() in line.lower():
                    second_colon_index = i
                    break

            if second_colon_index is not None:
                # Шаг 2: После нахождения ключевой строки в русском варианте,
                # извлекаем трекномер из английских строк, начиная с i+1 до i+4
                for offset in range(1, 5):
                    if second_colon_index + offset < len(english_lines):
                        track_number_line = english_lines[second_colon_index + offset].strip()

                        # Пытаемся извлечь трекномер из строки (включая латинские буквы и цифры, с пробелами или без)
                        track_number_match = re.search(r'[A-Za-z0-9\s]{5,20}', track_number_line.replace(' ', ''))
                        if track_number_match:
                            track_number = track_number_match.group(0)
                            break

            if track_number:
                state.add_data(track_number=track_number)
                state.set(track_number)
                # Предлагаем менеджеру подтвердить трекномер
                markup = types.InlineKeyboardMarkup(row_width=2)
                markup.add(
                    types.InlineKeyboardButton("Да", callback_data="confirm_track_number"),
                    types.InlineKeyboardButton("Нет", callback_data="edit_track_number")
                )
                bot.send_message(chat_id, f"Трекномер: {track_number}. Подтвердить?", reply_markup=markup)
            else:
                bot.send_message(chat_id, "Не удалось распознать трекномер. Пожалуйста, введите его вручную.")
                state.set(AvitoStates.track_number_manual)
        state.add_data(in_avito_photo=False)
    except Exception as e:
        bot.send_message(chat_id,e)


@bot.callback_query_handler(func=lambda call: call.data == 'confirm_track_number')
def confirm_track_number(call: types.CallbackQuery, state: StateContext):
    if not is_valid_command(call.message.text, state): return
    with state.data() as data:
        track_number = data.get('track_number')
        photo_path = data.get('avito_photo')

        # Сохраняем информацию о фото и трек-номере
        avito_photos_tracks = data.get('avito_photos_tracks', {})
        avito_photos_tracks[photo_path] = track_number

        # Сохраняем продукты для этого трек-номера
        product_dict = data.get("product_dict")
        avito_products = data.get("avito_products", {})
        avito_products[track_number] = {
            'products': product_dict,
            'price': 0  # Добавляем поле для цены
        }

    state.add_data(avito_photos_tracks=avito_photos_tracks)
    state.add_data(avito_products=avito_products)

    # Запрашиваем цену для этого трек-номера
    bot.send_message(call.message.chat.id, f"Введите сумму для трек-номера {track_number}:")
    state.set(AvitoStates.track_price)


@bot.message_handler(state=AvitoStates.track_price)
def handle_track_price(message: types.Message, state: StateContext):
    if not is_valid_command(message.text, state): return
    try:
        track_price = float(message.text)

        with state.data() as data:
            track_number = data.get('track_number')
            avito_products = data.get('avito_products', {})
            # Сохраняем цену для текущего трек-номера
        if track_number in avito_products:
            avito_products[track_number]['price'] = track_price
            state.add_data(avito_products=avito_products)
        print(avito_products,'avitoProudcts')

        # Спрашиваем про добавление следующего трек-номера
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("Да", callback_data="add_more_photos"),
            types.InlineKeyboardButton("Нет", callback_data="no_more_photos")
        )
        bot.send_message(message.chat.id, "Добавить ещё трекномер Авито?", reply_markup=markup)
        state.set(AvitoStates.next_step)

    except ValueError:
        bot.send_message(message.chat.id, "Некорректный формат суммы. Пожалуйста, введите число.")


@bot.callback_query_handler(func=lambda call: call.data == 'edit_track_number')
def edit_track_number(call: types.CallbackQuery, state: StateContext):
    if not is_valid_command(call.message.text, state): return
    bot.send_message(call.message.chat.id, "Пожалуйста, введите трекномер вручную без пробелов:")
    state.set(AvitoStates.track_number_manual)

@bot.message_handler(state=AvitoStates.track_number_manual)
def handle_track_number_manual(message: types.Message, state: StateContext):
    if not is_valid_command(message.text, state): return
    state.add_data(in_avito_photo=False)
    track_number = message.text.strip().replace(' ', '')
    with state.data() as data:
        photo_path = data.get('avito_photo')

        # Достаем словарь с фото и трекномерами
        avito_photos_tracks = data.get('avito_photos_tracks', {})

        # Добавляем пару фото-трекномер
        avito_photos_tracks[photo_path] = track_number

        product_dict = data.get("product_dict")
        avito_products = data.get("avito_products", {})
        track_number = data.get("track_number")

        avito_products[track_number] = product_dict
    state.add_data(avito_products=avito_products)
        # Обновляем словарь в состоянии
    state.add_data(avito_photos_tracks=avito_photos_tracks)

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("Да", callback_data="add_more_photos"),
        types.InlineKeyboardButton("Нет", callback_data="no_more_photos")
    )
    bot.send_message(message.chat.id, "Добавить ещё фото для Авито?", reply_markup=markup)
    state.set(AvitoStates.next_step)
    # Переходим в состояние для ожидания ответа

@bot.callback_query_handler(func=lambda call: call.data in ['add_more_photos', 'no_more_photos'])
def handle_add_more_photos(call: types.CallbackQuery, state: StateContext):
    if call.data == 'add_more_photos':
        # Остаёмся в состоянии avito_photo и ожидаем ещё фото
        state.set(DirectStates.type_product)
        bot.edit_message_text("Оформите новые позиции для трекномера Авито", chat_id=call.message.chat.id,
                          message_id=call.message.message_id)

        delete_multiple_states(state,['product_dict'])
        from handlers.manager.sale import handle_product_type
        handle_product_type(call,state)
    elif call.data == 'no_more_photos':
        # Переходим к следующему шагу (ввод общей суммы)
        with state.data() as data:
            avito_photos_tracks = data.get('avito_photos_tracks', {})
            avito_products = data.get("avito_products", {})
            # Вычисляем общую сумму заказа на основе цен трек-номеров
            print(avito_products.values())
            total_price = sum(product_info['price'] for product_info in avito_products.values())
        state.add_data(total_price=total_price)
        state.set(DirectStates.gift)
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Пропустить", callback_data="skip"))
        bot.send_message(call.message.chat.id, "Введите текст подарка или нажмите 'Пропустить':",
                         reply_markup=markup)
    bot.answer_callback_query(call.id)

# @bot.message_handler(state=AvitoStates.total_price)
# def handle_total_price(message:types.Message,state:StateContext):
#     print(message.text)
#     if not is_valid_command(message.text, state): return
#     try:
#         total_amount = float(message.text)
#         state.add_data(total_price=total_amount)
#         # Завершаем процесс оформления заказа
#         review_order_data(message.chat.id,state)
#         # finalize_avito_order(message.chat.id, message.message_id,message.from_user.username, state)
#     except ValueError:
#         bot.send_message(message.chat.id, "Некорректный формат суммы. Пожалуйста, введите число.")

def finalize_avito_order(chat_id, message_id, manager_username, state: StateContext):
    """Финализируем заказ для Авито, включая фото и ответ на сообщение в канале."""
    with state.data() as order_data:
        if order_data:
            print(order_data)
            # Используем avito_products вместо product_dict
            avito_products = order_data.get("avito_products", {})
            gift = order_data.get("gift")
            note = order_data.get("note")
            is_need_packing = order_data.get("is_need_packing")
            sale_type = "avito"
            avito_photos_tracks = order_data.get("avito_photos_tracks", {})
            packer_id = order_data.get("pack_id")
            total_price = order_data.get("total_price")
            if not all([avito_products, sale_type, avito_photos_tracks]):
                bot.send_message(chat_id,
                                 "Не хватает данных для оформления заказа. Пожалуйста, начните процесс заново.")
                return

            try:
                print(is_need_packing,packer_id,'999')

                manager_info = get_user_info(username=manager_username)
                if not manager_info:
                    bot.send_message(chat_id, "Не удалось получить информацию о менеджере.")
                    return

                manager_id = manager_info['id']
                manager_name = manager_info['name']
                manager_username = manager_info['username']

                # Передаем avito_products вместо product_dict
                order = create_order(
                    avito_products, gift, note, sale_type, manager_id, message_id,
                    avito_photos_tracks=avito_photos_tracks,
                    packer_id=packer_id,
                    status_order=OrderType.ACTIVE.value,
                    total_price=total_price
                )

                order_id = order['id']
                product_list = order['values']

                # Обновляем process_product_stock для работы с avito_products
                for track_info in avito_products.values():
                    process_product_stock(track_info['products'])


                # Формируем сообщение с информацией о заказе
                if packer_id == manager_id:
                    pack_message = f"Упакует {manager_name} ({manager_username})"
                elif not packer_id and is_need_packing:
                    pack_message = "Упаковщик ещё не выбран"
                else:
                    pack_message = "Не требует упаковки"

                order_message = format_order_message(
                    order_id, product_list, gift, note, sale_type, manager_name, manager_username,
                    total_price=total_price, avito_boxes=len(avito_photos_tracks.keys())
                ) + f"\n\n{pack_message}"

                # Отправляем сообщения с фото в основной канал
                # for photo_path in avito_photos_tracks:
                #     with open(photo_path, 'rb') as photo_file:
                #         sent_message = bot.send_photo(CHANNEL_CHAT_ID, photo_file, caption=order_message)
                #         reply_message_id = sent_message.message_id
                #         reply_message_ids.append(reply_message_id)
                #         update_order_message_id(order_id, reply_message_id)
                # Отправляем фотографии в основной канал без сообщения о заказе
                media_group = create_media_group(avito_photos_tracks.keys(),order_message)
                reply_message_id = bot.send_media_group(chat_id=CHANNEL_CHAT_ID, media=media_group)
                bot.send_message(chat_id, order_message)
                update_order_message_id(order['id'],reply_message_id[0].message_id)
                # state.set(SaleStates.avito_message)
                state.add_data(order_id=order_id)
                state.add_data(avito_message=order_message)
                state.add_data(reply_message_id=reply_message_id[0].message_id)
                print(123)
                # Уведомляем соответствующих пользователей
                if not packer_id and is_need_packing:
                    # Если упаковщик не выбран, оповещаем всех пользователей
                    notify_all_users(order_message, order_id, reply_message_id[0].message_id, state)
                else:
                    # Уведомляем курьеров сразу после обновления состояния
                    notify_couriers(order_message, state,  avito_photos = avito_photos_tracks.keys(), reply_message_id=reply_message_id[0].message_id,)

                # Уменьшаем сток для всех продуктов
                # for product_id, param_ids in product_dict.items():
                #     for param_id in set(param_ids):
                #         quantity = param_ids.count(param_id)
                #         decrement_stock(product_id=product_id, product_param_id=param_id, quantity=quantity)

                # Удаляем состояние после завершения заказа
                state.delete()
            except Exception as e:
                bot.send_message(chat_id, f"Произошла ошибка при оформлении заказа: {str(e)}")
        else:
            bot.send_message(chat_id, "Произошла ошибка при оформлении заказа. Пожалуйста, попробуйте снова.")



def notify_all_users(order_message, order_id,message_to_reply,state):
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
        print(order_id)
        print('order_id')
        bot.send_message(
            CHANNEL_CHAT_ID,
            f"Заказ #{str(order_id).zfill(4)}ㅤ принят в упаковку \nУпакует {user_info['name']} ({user_info['username']})",
            reply_parameters=reply_params,
        )
    else:
        bot.send_message(call.message.chat.id, "Не удалось получить информацию о пользователе.")
    bot.answer_callback_query(call.id)