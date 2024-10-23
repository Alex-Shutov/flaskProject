from telebot import types
from telebot.states.sync.context import StateContext
from database import get_user_info

from main import bot

from database import get_product_info_with_params, get_product_params

from database import decrement_stock


def get_user_by_username(username, state):
    """
    Получает информацию о пользователе из state. Если информации нет, запрашивает её из БД и сохраняет в state.

    :param username: Имя пользователя
    :param state: Контекст состояния для хранения данных
    :return: Словарь с информацией о пользователе (id, имя, username, роли) или None, если не найден
    """
    # Проверяем данные в state
    with state.data() as user_data:
        user_info = user_data.get('user_info')

    if not user_info:
        # Если нет в state, получаем из базы данных
        user_info = get_user_info(username)  # Это функция запроса к базе данных

        if user_info:
            # Сохраняем данные в state
             state.add_data(user_info=user_info)
        else:
            return None  # Если пользователь не найден в БД

    return user_info


def review_order_data(chat_id, state: StateContext):
    with state.data() as data:
        product_dict = data.get('product_dict', {})
        gift = data.get('gift', 'Без подарка')
        note = data.get('note', 'Без заметок')
        packer_id = data.get('pack_id', None)
        total_price = data.get('total_price', 'Не указана')
        sale_type = data.get('sale_type')
        # Собираем текст для вывода продуктов
        product_details = []
        print(product_dict)
        for product_id, param_ids in product_dict.items():
            product_info = get_product_info_with_params(product_id, param_ids[0])  # Получаем информацию о продукте
            print(product_info)
            print('product_info')
            product_name = product_info['name']
            product_param = product_info['param_title']
            # product_params = ', '.join(
            #     [get_product_params(param_id)[1] for param_id in param_ids])  # Название параметров
            product_details.append(f"{product_name} {product_param}")
        product_text = '\n'.join(product_details)
        # Упаковщик или сообщение о его отсутствии
        print(product_text)
        packer_text = "Упаковщик: Без упаковщика" if not packer_id else f"Упаковщик: {get_user_info(packer_id)['name']}"

        # Собираем текст общего сообщения
        order_summary = f"""
        Продукты:
        
{product_text}

    Подарок: {gift}
    Заметка: {note}
    {packer_text}
    Цена продажи: {total_price}
    """
        # Если это Авито, добавляем трек-коды
        if sale_type == "avito":
            avito_photos_tracks = data.get('avito_photos_tracks', {})
            tracks_text = '\n'.join([f"{track}" for photo, track in avito_photos_tracks.items()])
            order_summary += f"\nТрекинг-коды:\n{tracks_text}"
            order_summary+=f"\nКол-во мешков для упаковки: {len(avito_photos_tracks.keys())}\n"

        # Если это доставка, добавляем данные доставки
        elif sale_type == "delivery":
            delivery_date = data.get('delivery_date')
            delivery_address = data.get('delivery_address')
            contact_phone = data.get('contact_phone')
            contact_name = data.get('contact_name')
            order_summary += f"""
            Дата доставки: {delivery_date}
            Адрес доставки: {delivery_address}
            Контактное лицо: {contact_name}
            Телефон: {contact_phone}
            """
        # Отправляем собранное сообщение

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Да", callback_data="confirm_final_order"))
        markup.add(types.InlineKeyboardButton("Нет", callback_data="cancel_order"))

        bot.send_message(chat_id, order_summary, reply_markup=markup)


def process_product_stock(product_dict):
    """
    Обрабатывает изменения на складе для продуктов в заказе.

    Args:
        product_dict (dict): Словарь, где ключ — это product_id, а значение — список param_ids.
    """
    for product_id, param_ids in product_dict.items():
        for param_id in set(param_ids):
            quantity = param_ids.count(param_id)
            decrement_stock(product_id=product_id, product_param_id=param_id, quantity=quantity)