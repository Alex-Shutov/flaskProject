from telebot import types
from telebot.states.sync.context import StateContext
from database import get_user_info

from bot import bot

from database import get_product_info_with_params, get_product_params

from database import decrement_stock

from app_types import OrderType, SaleType

from app_types import SaleTypeRu

from database import get_user_info_by_id


def get_user_by_username(username, state, user_id=None):
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
        user_info = get_user_info(username) # Это функция запроса к базе данных

        if user_info:
            # Сохраняем данные в state
             state.add_data(user_info=user_info)
        else:
            return None  # Если пользователь не найден в БД

    return user_info




def review_order_data(chat_id, state: StateContext,prev_message=None):
    """
    Формирует и отображает сводку заказа перед финальным подтверждением
    """
    with state.data() as data:
        # Получаем базовые данные заказа
        original_manager_id = data.get('original_manager_id',None)
        original_manager_name = data.get('original_manager_name',None)
        original_manager_username = data.get('original_manager_username',None)
        sale_type = data.get('sale_type')
        product_dict = data.get('product_dict', {})
        gift = data.get('gift', 'Без подарка')
        note = data.get('note', 'Без заметок')
        packer_id = data.get('pack_id')
        user_info = data.get('user_info')
        total_price = data.get('total_price', 'Не указана')
        delivery_sum = data.get('delivery_sum', None)
        print(data,'data')
        # Группируем продукты по трек-номерам для Авито

        products_by_tracking = {}
        if sale_type == "avito":
            avito_products = data.get("avito_products", {})
            print(avito_products)
            for track_number, track_info in avito_products.items():
                products_by_tracking[track_number] = {
                    'products': [],
                    'price': track_info['price']
                }
                products = track_info['products']
                for product_id, param_ids in products.items():
                    for param_id in param_ids:
                        product_info = get_product_info_with_params(product_id, param_id)
                        if product_info:
                            products_by_tracking[track_number]['products'].append({
                                'name': product_info['name'],
                                'param': product_info['param_title']
                            })
        # Формируем основной текст заказа
        order_summary = ["📦 Предпросмотр заказа:"]
        order_summary.append(f"\nТип продажи: {SaleTypeRu[sale_type.upper()].value}{'(Показ)' if sale_type == 'direct' and original_manager_id else ''}")
        # Добавляем информацию о продуктах

        if sale_type in ['sdek', 'pek', 'luch']:
            courier_photos = data.get('courier_photos', {})
            if courier_photos:
                order_summary.append(f"\n📸 Количество фото: {len(courier_photos)}")

        if sale_type == "avito":
            total = 0
            print(products_by_tracking)
            for track_number, track_info in products_by_tracking.items():
                total += track_info['price']
                order_summary.append(f"\n🔹 Трек-номер: {track_number}\n")
                for product in track_info['products']:
                    order_summary.append(f"  • {product['name']} - {product['param']}")
                    # order_summary.append(f"{track_info['price']} руб.")
            order_summary.append(f"\n💰 Общая сумма заказа: {total} руб.")
        else:
            order_summary.append("\n🛒 Продукты:")
            for product_id, param_ids in product_dict.items():
                # Перебираем все параметры для каждого продукта
                for param_id in param_ids:
                    product_info = get_product_info_with_params(product_id, param_id)
                    if product_info:
                        emoji = "📦" if product_info.get('is_main_product') else "➕"
                        order_summary.append(f"  {emoji} {product_info['name']} - {product_info['param_title']}")
        # Добавляем общую информацию
        packer_info = ''
        if packer_id is not None and sale_type in [SaleType.DELIVERY.value, SaleType.AVITO.value]:
            packer_info = f"🛍️ {get_packer_info(int(packer_id),state=state,username=user_info['username'])}"

        order_summary.extend([
            f"\n🎁 Подарок: {gift}",
            f"📝 Заметка: {note}",
            packer_info
        ])
        if sale_type == "direct" and original_manager_id is not None:
            order_summary.append(f"\n👤 Менеджер: {original_manager_name} {original_manager_username}\n")
        if sale_type != 'avito':
            order_summary.append(f'\n💰 Сумма заказа: {total_price} руб.')
            # Добавляем стоимость доставки для СДЭК, ПЭК, ЛУЧ
            if sale_type in ['sdek', 'pek', 'luch'] and delivery_sum is not None:
                order_summary.append(f'🚚 Стоимость доставки: {delivery_sum} руб.')
        # Добавляем специфичную информацию по типу заказа
        if sale_type == "avito":
            avito_photos_tracks = data.get('avito_photos_tracks', {})
            order_summary.append(f"\n📦 Количество мешков: {len(avito_photos_tracks)}")
        elif sale_type == "delivery":
            full_address = data.get('delivery_address', '')['full_address']
            zone_name = data.get('zone_name')
            delivery_info = [
                f"\n📍 Информация о доставке:",
                f"🏠 Адрес: {full_address}",
                f"🎯 Зона доставки: {zone_name}",
                f"📅 Дата доставки: {data.get('delivery_date')}",
                f"⏰ Время доставки: {data.get('delivery_time')}",
                f"👤 Получатель: {data.get('contact_name')}",
                f"📞 Телефон: {data.get('contact_phone')}"
            ]
            order_summary.extend(delivery_info)


        # Формируем клавиатуру для подтверждения
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_final_order"),
            types.InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")
        )

        # Отправляем сообщение
        bot.send_message(
            chat_id,
            '\n'.join(filter(None, order_summary)),  # Фильтруем пустые строки
            reply_markup=markup,
            parse_mode='HTML'
        )




def get_packer_info(packer_id,state=None,username=None):
    """Возвращает информацию об упаковщике"""
    if not packer_id:
        return "Упаковщик: Не назначен"
    packer = get_user_info(packer_id) if not state and not username else get_user_by_username(username,state)
    return f"Упаковщик: {packer['name']} ({packer['username']})"


def get_delivery_info(data):
    """Формирует информацию о доставке"""
    return [
        f"\n📅 Дата доставки: {data.get('delivery_date', 'Не указана')}",
        f"🕒 Время: {data.get('delivery_time', 'Не указано')}",
        f"📍 Адрес: {data.get('delivery_address', 'Не указан')}",
        f"👤 Получатель: {data.get('contact_name', 'Не указан')}",
        f"📞 Телефон: {data.get('contact_phone', 'Не указан')}"
    ]
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

def delete_multiple_states(state: StateContext,states_to_delete_array:[]):
    with state.data() as data:
        # Список состояний для удаления
        states_to_delete = states_to_delete_array
        for state_name in states_to_delete:
            data.pop(state_name, None)