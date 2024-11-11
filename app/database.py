import datetime
import json
from typing import List, Dict, Optional

import psycopg2

from app_types import OrderType
from psycopg2 import pool
from config import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DATABASE_CONFIG

db_pool = psycopg2.pool.SimpleConnectionPool(
    minconn=1,
    maxconn=20,
    **DATABASE_CONFIG
)

def get_connection():
    return db_pool.getconn()



def return_connection(conn):
    db_pool.putconn(conn)

# def get_connection():
#     return psycopg2.connect(
#         database=DB_NAME,
#         user=DB_USER,
#         password=DB_PASSWORD,
#         host=DB_HOST,
#         port=DB_PORT
#     )

def check_user_access(username):
    # Добавляем "@" и приводим к нижнему регистру
    formatted_username = f"@{username.lower()}"

    with get_connection() as conn:
        with conn.cursor() as cursor:
            # Выполняем запрос с форматированным username
            cursor.execute("SELECT id, name, role FROM users WHERE username = %s", (formatted_username,))
            result = cursor.fetchone()
            if result:
                user_id, name, roles = result
                return user_id, name, roles
            return None


def get_user_info(username):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, name, username,telegram_id,role FROM users WHERE username = %s", (f"@{username.lower()}",))
            user_info = cursor.fetchone()

            if not user_info:
                return None

            return {
                'id': user_info[0],
                'name': user_info[1],
                'username': user_info[2],
                'telegram_id': user_info[3],
                'roles':user_info[4]
            }
def get_product_type():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id,title from type_product WHERE is_available = True")
            return cursor.fetchall()


def get_products(type_id=None):
    """Возвращает список продуктов. Если передан тип, фильтрует по нему."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            if type_id:
                # Если type_id передан, фильтруем по нему
                query = "SELECT id, name FROM products WHERE type_id = %s and is_available = True"
                cursor.execute(query, (type_id,))
            else:
                # Если type_id не передан, выводим все продукты
                query = "SELECT id, name FROM products WHERE is_available = True"
                cursor.execute(query)

            return cursor.fetchall()


def get_product_params(product_id):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, title,stock FROM product_params WHERE product_id = %s and is_available = True", (product_id,))
            return cursor.fetchall()


def create_order(product_dict, gift, note, sale_type, manager_id, message_id,
                 avito_photos_tracks=None, packer_id=None, status_order=OrderType.ACTIVE.value,
                 delivery_date=None, delivery_time=None, delivery_address=None,
                 delivery_note=None, contact_phone=None, contact_name=None, total_price=None):
    """
    Создает новый заказ в базе данных

    Returns:
        dict: Словарь с id заказа и информацией о продуктах, сгруппированной по трек-номерам для Авито
    """
    print(0)
    with get_connection() as conn:
        with conn.cursor() as cursor:
            try:
                # Начинаем транзакцию
                cursor.execute("BEGIN")
                print(1)
                # Создаем основной заказ
                order_query = """
                    INSERT INTO orders (
                        gift, note, order_type, manager_id, message_id, packer_id,
                        status, delivery_date, delivery_time, delivery_address,
                        delivery_note, contact_phone, contact_name, total_price,
                        avito_boxes_count, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    RETURNING id;
                """
                cursor.execute(order_query, (
                    gift, note, sale_type, manager_id, message_id, packer_id,
                    status_order, delivery_date, delivery_time, delivery_address,
                    delivery_note, contact_phone, contact_name, total_price,
                    len(avito_photos_tracks) if avito_photos_tracks else 0
                ))
                order_id = cursor.fetchone()[0]
                print(2)

                # Инициализируем список информации о продуктах
                product_info_list = {}

                # Если это заказ Авито
                if sale_type == 'avito' and isinstance(product_dict, dict):
                    product_info_list = {}  # Для хранения информации по трек-номерам

                    for track_number, track_info in product_dict.items():
                        track_price = track_info['price']
                        products = track_info['products']

                        # Инициализируем список продуктов для этого трек-номера
                        product_info_list[track_number] = {
                            'products': [],
                            'price': track_price
                        }

                        # Сохраняем фото и трек-номер
                        for photo_path, photo_track in avito_photos_tracks.items():
                            if photo_track == track_number:
                                cursor.execute("""
                                    INSERT INTO avito_photos (order_id, photo_path, tracking_number)
                                    VALUES (%s, %s, %s)
                                """, (order_id, photo_path, track_number))

                        # Сохраняем продукты для данного трек-номера
                        for product_id, param_ids in products.items():
                            for param_id in param_ids:
                                product_info = get_product_info_with_params(product_id, param_id)
                                if product_info:
                                    # Добавляем в список продуктов для возврата
                                    product_info_list[track_number]['products'].append({
                                        'name': product_info['name'],
                                        'param': product_info['param_title'],
                                        'is_main_product': product_info['is_main_product']
                                    })

                                    # Сохраняем в базу
                                    cursor.execute("""
                                        INSERT INTO order_items (
                                            order_id, product_id, product_param_id,
                                            product_name, product_param_title,
                                            product_values, is_main_product,
                                            status, tracking_number, track_price
                                        )
                                        VALUES (
                                            %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s
                                        )
                                    """, (
                                        order_id, product_id, param_id,
                                        product_info['name'], product_info['param_title'],
                                        json.dumps(product_info['product_values']),
                                        product_info['is_main_product'],
                                        status_order, track_number, track_price
                                    ))
                else:
                    # Для обычных заказов сохраняем все продукты в общий список
                    product_info_list['general'] = []
                    print(3)

                    for product_id, param_ids in product_dict.items():
                        for param_id in param_ids:
                            product_info = get_product_info_with_params(product_id, param_id)
                            if product_info:
                                # Добавляем информацию о продукте в список
                                product_info_item = {
                                    'product_id': product_id,
                                    'product_name': product_info['name'],
                                    'is_main_product': product_info['is_main_product'],
                                    'param_title': product_info['param_title'],
                                    'param_id': param_id,
                                }
                                product_info_list['general'].append(product_info_item)
                                print(4)

                                # Сохраняем в базу
                                cursor.execute("""
                                    INSERT INTO order_items (
                                        order_id, product_id, product_param_id,
                                        product_name, product_param_title,
                                        product_values, is_main_product,
                                        status
                                    )
                                    VALUES (
                                        %s, %s, %s, %s, %s, %s::jsonb, %s, %s
                                    )
                                """, (
                                    order_id, product_id, param_id,
                                    product_info['name'], product_info['param_title'],
                                    json.dumps(product_info['product_values']),
                                    product_info['is_main_product'],
                                    status_order
                                ))
                print(5)

                # Завершаем транзакцию
                cursor.execute("COMMIT")
                return {'id': order_id, 'values': product_info_list}

            except Exception as e:
                cursor.execute("ROLLBACK")
                raise e


def create_order_items(order_id, product_id, product_name, product_values, is_main_product):
    """
    Создает записи в таблице order_items для каждого товара в заказе.

    :param order_id: ID заказа
    :param product_id: ID продукта
    :param product_name: Название продукта
    :param product_values: Значения параметров продукта (JSON)
    :param is_main_product: Флаг, основной ли это продукт
    :return: None
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            query = """
                INSERT INTO order_items (order_id, product_id, product_name, product_values, is_main_product, status, created_at)
                VALUES (%s, %s, %s, %s::jsonb, %s, 'active', NOW());
            """
            cursor.execute(query, (order_id, product_id, product_name, json.dumps(product_values), is_main_product))
            conn.commit()


def update_order_message_id(order_id, message_id):
    """Обновляет message_id для заказа в базе данных."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            query = """
                UPDATE orders
                SET message_id = %s
                WHERE id = %s
            """
            cursor.execute(query, (message_id, order_id))
            conn.commit()


def get_product_info(product_id, param_id):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT name,is_main_product FROM products WHERE id = %s and is_available = True", (product_id,))
            product_name,is_main_product = cursor.fetchone()
            cursor.execute("SELECT title FROM product_params WHERE id = %s", (param_id,))
            product_param = cursor.fetchone()[0]
            return product_name, product_param,is_main_product

def get_couriers():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT id, name, username, telegram_id 
                FROM users 
                WHERE 'Courier' = ANY(role)  -- Проверяем, если роль 'Courier' присутствует в массиве ролей
            """)
            couriers = cursor.fetchall()

            # Преобразуем результат в список словарей
            columns = [desc[0] for desc in cursor.description]  # Получаем имена колонок
            couriers_dict = [dict(zip(columns, courier)) for courier in couriers]

            return couriers_dict


def get_orders(order_type=None, username=None, status=None, is_courier_null=False, start_date=None, end_date=None, role=None, item_status=None):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            query = """
                WITH products_grouped AS (
                    SELECT 
                        oi.order_id,
                        oi.tracking_number,
                        jsonb_agg(
                            jsonb_build_object(
                                'product_id', p.id,
                                'name', p.name,
                                'status', oi.status,
                                'is_main_product', oi.is_main_product,
                                'param', pp.title,
                                'param_id', pp.id
                            )
                        ) as product_list,
                        MAX(oi.track_price) as track_price
                    FROM order_items oi
                    JOIN products p ON oi.product_id = p.id
                    JOIN product_params pp ON oi.product_param_id = pp.id
                    WHERE 1=1
                    """

            params = []

            # Добавляем фильтрацию по статусу товаров в CTE с явным приведением типа
            if item_status and isinstance(item_status, list):
                query += " AND oi.status::text = ANY(%s)"  # Изменено здесь
                params.append(item_status)

            query += """
                    GROUP BY oi.order_id, oi.tracking_number
                ),
                final_products AS (
                    SELECT 
                        order_id,
                        jsonb_object_agg(
                            COALESCE(tracking_number, 'no_track'),
                            jsonb_build_object(
                                'products', product_list,
                                'price', track_price
                            )
                        ) as products
                    FROM products_grouped
                    GROUP BY order_id
                )
                SELECT o.id, o.gift, o.note, o.order_type, o.status, o.created_at,
                       o.manager_id, o.message_id, o.closed_date, o.packer_id, o.courier_id,
                       o.delivery_date, o.delivery_time, o.delivery_address, o.delivery_note, 
                       o.contact_phone, o.contact_name, o.total_price, o.avito_boxes_count,
                       fp.products,
                        m.name as manager_name, m.username as manager_username,
                       p.name as packer_name, p.username as packer_username,
                       c.name as courier_name, c.username as courier_username
                FROM orders o
                LEFT JOIN final_products fp ON o.id = fp.order_id
                LEFT JOIN users m ON o.manager_id = m.id
                LEFT JOIN users p ON o.packer_id = p.id
                LEFT JOIN users c ON o.courier_id = c.id
                WHERE 1=1
            """

            # Добавляем остальные условия фильтрации
            if order_type and isinstance(order_type, list):
                query += " AND o.order_type = ANY(%s)"
                params.append(order_type)

            if status and isinstance(status, list):
                query += " AND o.status::text = ANY(%s)"  # Изменено здесь тоже
                params.append(status)

            if username:
                formatted_username = username if username.startswith('@') else f"@{username.lower()}"
                cursor.execute("SELECT id FROM users WHERE username = %s", (formatted_username,))
                user_id = cursor.fetchone()
                if not user_id:
                    return []
                if role:
                    if role == 'courier':
                        query += " AND o.courier_id = %s"
                    elif role == 'packer':
                        query += " AND o.packer_id = %s"
                    elif role == 'manager':
                        query += " AND o.manager_id = %s"
                    params.append(user_id[0])

            if is_courier_null:
                query += " AND o.courier_id IS NULL"

            if start_date and end_date:
                query += " AND o.closed_date BETWEEN %s AND %s"
                params.append(start_date)
                params.append(end_date)

            query += " ORDER BY o.id DESC"

            cursor.execute(query, tuple(params) if params else None)
            orders = cursor.fetchall()

            # Форматируем результаты
            formatted_orders = []
            for order in orders:
                formatted_order = {
                    'id': order[0],
                    'gift': order[1],
                    'note': order[2] if order[2] else 'Не указано',
                    'order_type': order[3],
                    'status': order[4],
                    'created_at': order[5],
                    'manager_id': order[6],
                    'message_id': order[7],
                    'closed_date': order[8],
                    'packer_id': order[9],
                    'courier_id': order[10],
                    'delivery_date': order[11],
                    'delivery_time': order[12],
                    'delivery_address': order[13],
                    'delivery_note': order[14],
                    'contact_phone': order[15],
                    'contact_name': order[16],
                    'total_price': order[17],
                    'avito_boxes': order[18],
                    'products': order[19] if order[19] else {},  # Теперь это уже сгруппированный объект
                    'manager_name': order[20],
                    'manager_username': order[21],
                    'packer_name': order[22] or 'Не назначен',
                    'packer_username': order[23] or 'Не назначен',
                    'courier_name': order[24] or 'Не назначен',
                    'courier_username': order[25] or 'Не назначен'
                }

                # Преобразование products уже не требуется, так как группировка
                # выполнена в SQL-запросе
                formatted_orders.append(formatted_order)

            return formatted_orders

def get_avito_photos(order_id):
    """Получает фотографии для заказа Авито"""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT photo_path FROM avito_photos WHERE order_id = %s",
                (order_id,)
            )
            return [row[0] for row in cursor.fetchall()]

def update_order_status(order_id, status, with_order_items=True):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            # Обновляем статус заказа
            cursor.execute("UPDATE orders SET status = %s::public.status_order WHERE id = %s", (status, order_id))
            if with_order_items:
                if status == 'closed':
                    # Для статуса closed обновляем только те order_items,
                    # которые не имеют статус refund или declined
                    cursor.execute("""
                        UPDATE order_items 
                        SET status = %s::public.status_order 
                        WHERE order_id = %s 
                        AND status::text NOT IN ('refund', 'declined')
                    """, (status, order_id))
                else:
                    # Для остальных статусов обновляем все order_items
                    cursor.execute("""
                        UPDATE order_items 
                        SET status = %s::public.status_order 
                        WHERE order_id = %s
                    """, (status, order_id))

            # Сохраняем изменения
            conn.commit()
def get_product_by_id(product_id):
    """
       Получает всю информацию о продукте по его идентификатору.

       Аргумент:
       - product_id: идентификатор продукта.

       Возвращает:
       - Словарь с информацией о продукте.
       """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT *
                FROM products
                WHERE id = %s
            """, (product_id,))
            product_data = cursor.fetchone()

            if not product_data:
                return None

            # Получаем названия столбцов таблицы products
            product_columns = [desc[0] for desc in cursor.description]
            product_info = dict(zip(product_columns, product_data))

            return product_info

def get_product_param_by_id(param_id):
    """
    Получает всю информацию о параметре продукта по его идентификатору.

    Аргумент:
    - param_id: идентификатор параметра продукта.

    Возвращает:
    - Словарь с информацией о параметре продукта.
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT *
                FROM product_params
                WHERE id = %s
            """, (param_id,))
            param_data = cursor.fetchone()

            if not param_data:
                return None

            # Получаем названия столбцов таблицы product_params
            param_columns = [desc[0] for desc in cursor.description]
            param_info = dict(zip(param_columns, param_data))

            return param_info


def update_order_courier(order_id, courier_id):
    """
    Обновляет заказ, привязывая к нему курьера.

    Аргументы:
    - order_id: идентификатор заказа.
    - courier_id: идентификатор курьера.
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE orders
                SET courier_id = %s
                WHERE id = %s
            """, (courier_id, order_id))
            conn.commit()


def update_order_invoice_photo(order_id: int, tracking_number: str, photo_path: str) -> bool:
    """
    Обновляет путь к фотографии накладной в таблице avito_photos.

    Args:
        order_id: ID заказа
        tracking_number: Трек-номер Авито
        photo_path: Путь к сохраненной фотографии

    Returns:
        bool: True если обновление прошло успешно, False в случае ошибки
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            try:
                query = """
                    UPDATE avito_photos
                    SET invoice_photo = %s
                    WHERE order_id = %s AND tracking_number = %s
                    RETURNING id
                """
                cursor.execute(query, (photo_path, order_id, tracking_number))

                # Проверяем, была ли обновлена запись
                result = cursor.fetchone()
                conn.commit()

                return result is not None

            except Exception as e:
                print(f"Error updating avito invoice photo: {e}")
                conn.rollback()
                return False

def get_all_users(roles=None):
    """
    Возвращает список всех пользователей. Если указаны роли, возвращает пользователей с этими ролями.

    :param roles: Список ролей для фильтрации (если переданы)
    :return: Список пользователей
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            # Основной запрос на получение всех пользователей
            query = "SELECT * FROM users"
            params = []

            # Если указаны роли, добавляем фильтрацию
            if roles:
                print(roles)
                query += f" WHERE role && %s"
                params.append(roles)
                print(params)

            cursor.execute(query, tuple(params))
            users = cursor.fetchall()
            print(users)
            # Форматируем результат как список словарей для удобства
            formatted_users = [
                {
                    'id': user[0],
                    'telegram_id':user[1],
                    'name': user[3],
                    'username': user[2],
                    'role': user[4]
                }
                for user in users
            ]

            return formatted_users


def update_order_packer(order_id, packer_id):
    """
    Обновляет ID упаковщика для конкретного заказа.

    :param order_id: ID заказа
    :param packer_id: ID упаковщика (пользователя)
    :return: None
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE orders
                SET packer_id = %s
                WHERE id = %s
            """, (packer_id, order_id))
            conn.commit()


def get_active_orders_without_packer():
    """
    Возвращает список активных заказов без назначенного упаковщика
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            # Получаем заказы без упаковщика
            query = """
                WITH order_products AS (
                    SELECT 
                        oi.order_id,
                        jsonb_agg(
                            jsonb_build_object(
                                'product_id', p.id,
                                'product_name', p.name,
                                'is_main_product', oi.is_main_product,
                                'param_title', pp.title,
                                'param_id', pp.id,
                                'tracking_number', oi.tracking_number,
                                'track_price', oi.track_price
                            )
                        ) as products
                    FROM order_items oi
                    JOIN products p ON oi.product_id = p.id
                    JOIN product_params pp ON oi.product_param_id = pp.id
                    GROUP BY oi.order_id, oi.tracking_number
                )
                SELECT 
                    o.id, 
                    o.gift, 
                    o.note, 
                    o.order_type, 
                    o.status, 
                    o.created_at,
                    o.manager_id, 
                    o.message_id,
                    o.avito_boxes_count,
                    o.total_price,
                    op.products,
                    m.name as manager_name,
                    m.username as manager_username
                FROM orders o
                LEFT JOIN order_products op ON o.id = op.order_id
                LEFT JOIN users m ON o.manager_id = m.id
                WHERE o.status = 'active' 
                AND o.packer_id IS NULL
            """
            cursor.execute(query)
            orders = cursor.fetchall()

            formatted_orders = []
            for order in orders:
                formatted_order = {
                    'id': order[0],
                    'gift': order[1],
                    'note': order[2],
                    'order_type': order[3],
                    'status': order[4],
                    'created_at': order[5],
                    'manager_id': order[6],
                    'message_id': order[7],
                    'avito_boxes': order[8],
                    'total_price': order[9],
                    'products': order[10] if order[10] else [],
                    'manager_name': order[11],
                    'manager_username': order[12]
                }

                if formatted_order['order_type'] == 'avito':
                    # Группируем продукты по трек-номерам
                    products_by_track = {}
                    for product in formatted_order['products']:
                        track_num = product['tracking_number']
                        if track_num not in products_by_track:
                            products_by_track[track_num] = {
                                'products': [],
                                'price': product['track_price']
                            }
                        products_by_track[track_num]['products'].append({
                            'name': product['product_name'],
                            'param': product['param_title'],
                            'is_main_product': product['is_main_product']
                        })
                    formatted_order['products'] = products_by_track
                else:
                    # Для не-Авито заказов оставляем простой список
                    formatted_order['products'] = [{
                        'name': p['product_name'],
                        'param_title': p['param_title'],
                        'is_main_product': p['is_main_product']
                    } for p in formatted_order['products']]

                formatted_orders.append(formatted_order)

            return formatted_orders


def get_delivery_zone_for_order(order_id):
    """Получает информацию о зоне доставки для заказа"""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            query = """
                SELECT dz.name, dz.base_price, dz.additional_item_price
                FROM delivery_addresses da
                JOIN delivery_zones dz ON da.zone_id = dz.id
                WHERE da.order_id = %s
            """
            cursor.execute(query, (order_id,))
            result = cursor.fetchone()

            if result:
                return {
                    'name': result[0],
                    'base_price': result[1],
                    'additional_item_price': result[2]
                }
            return None

def get_order_by_id(order_id, item_statuses=None):
    """
    Возвращает заказ по его ID со всеми связанными данными.

    Args:
        order_id: ID заказа
        item_statuses: Список статусов для фильтрации товаров (опционально)
    Returns:
        dict: Словарь с данными заказа или None
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            query = """
                WITH products_grouped AS (
                    SELECT 
                        oi.order_id,
                        oi.tracking_number,
                        jsonb_agg(
                            jsonb_build_object(
                                'order_item_id', oi.id,
                                'product_id', p.id,
                                'name', p.name,
                                'is_main_product', oi.is_main_product,
                                'param', pp.title,
                                'param_id', pp.id,
                                'status', oi.status
                            )
                        ) as product_list,
                        MAX(oi.track_price) as track_price
                    FROM order_items oi
                    JOIN products p ON oi.product_id = p.id
                    JOIN product_params pp ON oi.product_param_id = pp.id
                    WHERE oi.order_id = %s
                """
            params = [order_id]

            # Добавляем фильтрацию по статусам, если они указаны
            if item_statuses and isinstance(item_statuses, list):
                query += " AND oi.status::text = ANY(%s)"
                params.append(item_statuses)

            query += """
                    GROUP BY oi.order_id, oi.tracking_number
                ),
                final_products AS (
                    SELECT 
                        order_id,
                        jsonb_object_agg(
                            COALESCE(tracking_number, 'no_track'),
                            jsonb_build_object(
                                'products', product_list,
                                'price', track_price
                            )
                        ) as products
                    FROM products_grouped
                    GROUP BY order_id
                )
                SELECT 
                    o.id, 
                    o.gift, 
                    o.note, 
                    o.order_type, 
                    o.status, 
                    o.created_at,
                    o.manager_id, 
                    o.message_id, 
                    o.closed_date, 
                    o.packer_id, 
                    o.courier_id,
                    o.delivery_date,
                    o.delivery_time,
                    o.delivery_address,
                    o.delivery_note,
                    o.contact_phone,
                    o.contact_name,
                    o.total_price,
                    o.avito_boxes_count,
                    fp.products,
                    m.name as manager_name,
                    m.username as manager_username
                FROM orders o
                LEFT JOIN final_products fp ON o.id = fp.order_id
                LEFT JOIN users m ON o.manager_id = m.id
                WHERE o.id = %s
            """
            params.append(order_id)  # Добавляем order_id второй раз для WHERE условия в основном запросе

            cursor.execute(query, params)
            order = cursor.fetchone()

            if order:
                formatted_order = {
                    'id': order[0],
                    'gift': order[1],
                    'note': order[2] if order[2] else "Не указано",
                    'order_type': order[3],
                    'status': order[4],
                    'created_at': order[5],
                    'manager_id': order[6],
                    'message_id': order[7],
                    'closed_date': order[8],
                    'packer_id': order[9],
                    'courier_id': order[10],
                    'delivery_date': order[11],
                    'delivery_time': order[12],
                    'delivery_address': order[13],
                    'delivery_note': order[14],
                    'contact_phone': order[15],
                    'contact_name': order[16],
                    'total_price': order[17],
                    'avito_boxes': order[18],
                    'products': order[19] if order[19] else {},
                    'manager_name': order[20],
                    'manager_username': order[21]
                }
                return formatted_order
            return None

def create_type_product(title, type_params):
    query = "INSERT INTO type_product (title, product_parameters, created_at) VALUES (%s, %s::jsonb, NOW()) RETURNING id"
    params = (title, json.dumps(type_params))
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchone()[0]

def create_product(name, type_id, is_main_product=False, product_values={}, param_parameters={}):
    query = """
        INSERT INTO products (name, type_id, created_at, product_values, param_parameters, is_main_product)
        VALUES (%s, %s, NOW(), %s::jsonb, %s::jsonb, %s)
        RETURNING id
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, (name, type_id, json.dumps(product_values), json.dumps(param_parameters), is_main_product))
            return cursor.fetchone()[0]

def create_product_param(product_id, title, stock, param_values):
    query = """
        INSERT INTO product_params (product_id, title, stock, created_at, param_values) 
        VALUES (%s, %s, %s, NOW(), %s::jsonb) 
        RETURNING id
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, (product_id, title, stock, json.dumps(param_values)))
            return cursor.fetchone()[0]

def get_type_product_params(type_product_id):
    query = "SELECT type_parameters FROM type_product WHERE id = %s"
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, (type_product_id,))
            result = cursor.fetchone()
            return result[0] if result else {}


def get_all_type_products():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            query = "SELECT id, title, product_parameters, created_at FROM type_product WHERE is_available = True"
            cursor.execute(query)
            result = cursor.fetchall()

            type_products = []
            for row in result:
                # Парсим параметры из JSON
                params = row[2] if isinstance(row[2], dict) else json.loads(row[2])
                print(row[3])
                # Форматируем дату в виде строки "день.месяц.год"
                # row[3] = datetime.datetime.strptime(row[3], '%Y-%m-%d %H:%M:%S.%f')
                formatted_date = row[3]

                # Формируем словарь типа продукта
                type_product = {
                    'id': row[0],
                    'name': row[1],
                    'params': params,
                    'created_at': "{:%d.%m.%Y}".format(formatted_date)
                }
                type_products.append(type_product)
            return type_products

def get_all_products(type_product_id):
    """
    Получает все продукты для указанного типа продукта.
    :param type_product_id: ID типа продукта
    :return: Список продуктов
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            # Запрос для получения продуктов с указанным типом
            query = """
                SELECT id, name,product_values, param_parameters, created_at 
                FROM products
                WHERE type_id = %s
            """
            cursor.execute(query, (type_product_id,))
            result = cursor.fetchall()

            products = []
            for row in result:
                print(row)
                # Декодируем JSON-параметры продукта
                params = row[2] if isinstance(row[2], dict) else json.loads(row[2])
                values = row[3] if isinstance(row[3], dict) else json.loads(row[3])

                # Формируем структуру данных для продукта
                product = {
                    'id': row[0],
                    'name': row[1],
                    'values':values,
                    'params': params,
                    'created_at': row[4]
                }
                products.append(product)

            return products

def get_all_product_params(product_id):
    """
    Получает все параметры для указанного продукта.
    :param product_id: ID продукта
    :return: Список параметров продукта
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            # Запрос для получения параметров продукта по product_id
            query = """
                SELECT id, title, param_values, created_at 
                FROM product_params
                WHERE product_id = %s
            """
            cursor.execute(query, (product_id,))
            result = cursor.fetchall()

            product_params = []
            for row in result:
                # Декодируем JSON-параметры
                params = row[2] if isinstance(row[2], dict) else json.loads(row[2])

                # Формируем структуру данных для параметров продукта
                product_param = {
                    'id': row[0],
                    'name': row[1],
                    'params': params,
                    'created_at': "{:%d.%m.%Y}".format(row[3])
                }
                product_params.append(product_param)

            return product_params

def get_product_info_with_params(product_id, param_id=None):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            # Получаем основную информацию о продукте
            query = "SELECT id, name, param_parameters, type_id, product_values,is_main_product FROM products WHERE id = %s and is_available = True"
            cursor.execute(query, (product_id,))
            result = cursor.fetchone()

            if result:
                product_info = {
                    'id': result[0],
                    'name': result[1],
                    'param_parameters': result[2] if isinstance(result[2], dict) else json.loads(result[2]),
                    'type_id': result[3],
                    'product_values': result[4] if isinstance(result[4], dict) else json.loads(result[4]),
                    'is_main_product': result[5]
                }

                # Если передан param_id, получаем title из product_params
                if param_id:
                    cursor.execute("SELECT title FROM product_params WHERE id = %s and is_available = True", (param_id,))
                    param_result = cursor.fetchone()
                    if param_result:
                        product_info['param_title'] = param_result[0]
                    else:
                        product_info['param_title'] = None  # Если не найдено, устанавливаем None

                return product_info

            return {}


def get_type_product_by_id(type_product_id):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            query = "SELECT id, title, product_parameters, created_at FROM type_product WHERE id = %s and is_available = True"
            cursor.execute(query, (type_product_id,))
            row = cursor.fetchone()

            if row:
                params = row[2] if isinstance(row[2], dict) else json.loads(row[2])
                formatted_date = "{:%d.%m.%Y}".format(row[3])

                return {
                    'id': row[0],
                    'name': row[1],
                    'params': params,
                    'created_at': formatted_date
                }
            return None

def get_product_by_id(product_id):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            query = """
                SELECT id, name, product_values, param_parameters, created_at
                FROM products
                WHERE id = %s
            """
            cursor.execute(query, (product_id,))
            row = cursor.fetchone()

            if row:
                params = row[2] if isinstance(row[2], dict) else json.loads(row[2])
                values = row[3] if isinstance(row[3], dict) else json.loads(row[3])

                return {
                    'id': row[0],
                    'name': row[1],
                    'values': values,
                    'params': params,
                    'created_at': "{:%d.%m.%Y}".format(row[4])
                }
            return None

def get_product_param_by_id(product_param_id):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            query = """
                SELECT id, title, param_values, created_at
                FROM product_params
                WHERE id = %s
            """
            cursor.execute(query, (product_param_id,))
            row = cursor.fetchone()

            if row:
                params = row[2] if isinstance(row[2], dict) else json.loads(row[2])

                return {
                    'id': row[0],
                    'name': row[1],
                    'params': params,
                    'created_at': "{:%d.%m.%Y}".format(row[3])
                }
            return None


def decrement_stock(order_id=None, product_id=None, product_param_id=None, quantity=1):
    """
    Уменьшает количество на складе для указанного параметра продукта.

    Args:
        order_id: ID заказа для получения product_id и product_param_id
        product_id: ID продукта (опционально, если указан order_id)
        product_param_id: ID параметра продукта (опционально, если указан order_id)
        quantity: Количество для вычитания из стока
    """
    if order_id is None and (product_id is None or product_param_id is None):
        raise ValueError("Необходимо указать либо order_id, либо product_id и product_param_id.")

    with get_connection() as conn:
        with conn.cursor() as cursor:
            try:
                # Если указан order_id, извлекаем все product_id и product_param_id из order_items
                if order_id is not None:
                    cursor.execute("""
                        SELECT product_id, product_param_id, COUNT(*) as item_count
                        FROM order_items 
                        WHERE order_id = %s
                        GROUP BY product_id, product_param_id
                    """, (order_id,))
                    items = cursor.fetchall()

                    if not items:
                        raise ValueError(f"Товары для заказа с ID {order_id} не найдены.")

                    # Обновляем сток для каждого товара
                    for item in items:
                        prod_id, param_id, item_quantity = item

                        # Проверка стока и блокировка строки
                        cursor.execute("""
                            SELECT stock 
                            FROM product_params 
                            WHERE product_id = %s AND id = %s 
                            FOR UPDATE
                        """, (prod_id, param_id))
                        current_stock = cursor.fetchone()

                        if current_stock is None:
                            raise ValueError(f"Продукт с ID {prod_id} и параметром {param_id} не найден.")

                        if current_stock[0] < item_quantity:
                            raise ValueError(
                                f"Недостаточно стока для товара {prod_id}. "
                                f"Требуется: {item_quantity}, доступно: {current_stock[0]}"
                            )

                        # Уменьшаем значение стока
                        new_stock = current_stock[0] - item_quantity
                        cursor.execute("""
                            UPDATE product_params 
                            SET stock = %s 
                            WHERE product_id = %s AND id = %s
                        """, (new_stock, prod_id, param_id))

                        print(f"Сток для товара {prod_id} уменьшен на {item_quantity}. Новый сток: {new_stock}")

                else:
                    # Если переданы конкретные product_id и product_param_id
                    cursor.execute("""
                        SELECT stock 
                        FROM product_params 
                        WHERE product_id = %s AND id = %s 
                        FOR UPDATE
                    """, (product_id, product_param_id))
                    current_stock = cursor.fetchone()

                    if current_stock is None:
                        raise ValueError(f"Продукт с ID {product_id} и параметром {product_param_id} не найден.")

                    if current_stock[0] < quantity:
                        raise ValueError("Недостаточно стока для выполнения операции.")

                    new_stock = current_stock[0] - quantity
                    cursor.execute("""
                        UPDATE product_params 
                        SET stock = %s 
                        WHERE product_id = %s AND id = %s
                    """, (new_stock, product_id, product_param_id))

                    print(f"Сток успешно уменьшен на {quantity}. Новый сток: {new_stock}")

                conn.commit()

            except Exception as e:
                conn.rollback()
                print(f"Произошла ошибка при обновлении стока: {e}")
                raise e


def get_user_info_by_id(user_id: int):
    """Получение информации о пользователе по ID"""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT id, telegram_id, name, username, role 
                FROM users 
                WHERE telegram_id = %s
            """, (user_id,))
            user_info = cursor.fetchone()

            if user_info:
                return {
                    'id': user_info[0],
                    'telegram_id': user_info[1],
                    'name': user_info[2],
                    'username': user_info[3],
                    'roles': user_info[4]
                }
            return None

def get_all_products_with_stock(type_id=None):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            query = """
                SELECT 
                    p.id, 
                    p.name, 
                    tp.title AS type_name, 
                    p.product_values, 
                    pp.title AS param_title,
                    pp.param_values, 
                    pp.stock, 
                    pp.title,
                    p.is_main_product,
                    p.sale_price,
                    p.avito_delivery_price
                FROM products p
                JOIN type_product tp ON p.type_id = tp.id
                LEFT JOIN product_params pp ON pp.product_id = p.id
            """
            if type_id is not None:
                query += " WHERE tp.id = %s"
                cursor.execute(query, (type_id,))
            else:
                cursor.execute(query)

            result = cursor.fetchall()

            # Форматируем данные в удобный для отчетов вид
            products_by_type = {}
            for row in result:
                product_id = row[0]
                product_name = row[1]
                product_type = row[2]
                product_values = row[3] if isinstance(row[3], dict) else (json.loads(row[3]) if row[3] else {})
                product_param_values = row[5] if isinstance(row[5], dict) else (json.loads(row[5]) if row[5] else {})
                stock = row[6]
                param_title = row[7]
                is_main_product = row[8]
                direct_price = row[9]
                delivery_price = row[10]

                # Добавляем цены в product_values
                product_values.update({
                    'direct_price': direct_price,
                    'delivery_price': delivery_price,
                })

                # Если тип продукта еще не был добавлен, инициализируем его
                if product_type not in products_by_type:
                    products_by_type[product_type] = []

                # Добавляем продукт в структуру
                products_by_type[product_type].append({
                    'id': product_id,
                    'name': product_name,
                    'product_values': product_values,
                    'product_param_values': product_param_values,
                    'stock': stock if stock else 0,
                    'param_title': param_title,
                    'is_main_product': is_main_product
                })

            return products_by_type




def get_user_info_by_id(user_id):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            query = "SELECT id, name, username FROM users WHERE id = %s"
            cursor.execute(query, (user_id,))
            result = cursor.fetchone()

            if result:
                return {
                    'id': result[0],
                    'name': result[1],
                    'username': result[2]
                }
            return None

def get_product_with_type(product_id):
    """
    Получение информации о продукте и его типе.
    :param product_id: ID продукта
    :return: Словарь с информацией о продукте и типе
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            # Запрос для получения информации о продукте и его типе
            query = """
                SELECT p.id, p.name, p.param_parameters, t.title as type_name, t.product_parameters
                FROM products p
                JOIN type_product t ON p.type_id = t.id
                WHERE p.id = %s
            """
            cursor.execute(query, (product_id,))
            result = cursor.fetchone()

            if result:
                # Формируем структуру данных для продукта и его типа
                product_info = {
                    'id': result[0],
                    'name': result[1],
                    'param_parameters': result[2] if isinstance(result[2], dict) else json.loads(result[2]),
                    'type_name': result[3],
                    'type_params': result[4] if isinstance(result[4], dict) else json.loads(result[4])
                }
                return product_info
            return {}


def get_detailed_orders(start_date, end_date, type_id=None):
    orders = get_orders(order_type=['avito', 'delivery', 'direct'], status=['closed'], start_date=start_date,
                        end_date=end_date)
    print(orders)
    detailed_orders = []

    for order in orders:
        product_id = order.get('product_id')
        product_info = get_product_info_with_params(product_id)

        # Фильтруем по type_id, если он указан

        if type_id is not None and int(product_info.get('type_id')) != int(type_id):
            continue

        order_id = order.get('id')
        product_param_id = order.get('product_param_id')
        product_name = product_info.get('name', 'N/A')
        type_product_id = product_info.get('type_id')
        type_info = get_type_info_by_product_id(product_id)
        type_name = type_info.get('name', 'N/A')
        type_params = type_info.get('params', {})
        product_values = product_info.get('product_values', {})
        product_param_info = get_product_param_info(product_param_id)
        product_param_title = product_param_info.get('title', 'N/A')
        product_param_values = product_param_info.get('param_values', {})

        manager_info = get_user_info_by_id(order.get('manager_id'))
        manager_name = manager_info.get('name', 'N/A') if manager_info else 'N/A'
        manager_username = manager_info.get('username', 'N/A') if manager_info else 'N/A'

        courier_info = get_user_info_by_id(order.get('courier_id'))
        courier_name = courier_info.get('name', 'Не указан') if courier_info else 'Не указан'
        courier_username = courier_info.get('username', 'Не указан') if courier_info else 'Не указан'

        packer_info = get_user_info_by_id(order.get('packer_id'))
        packer_name = packer_info.get('name', 'Не указан') if packer_info else 'Не указан'
        packer_username = packer_info.get('username', 'Не указан') if packer_info else 'Не указан'

        detailed_order = {
            'id': order_id,
            'product_name': product_name,
            'type_product': type_name,
            'type_product_params': type_params,
            'product_values': product_values,
            'product_param_title': product_param_title,
            'product_param_values': product_param_values,
            'manager_name': f"{manager_name} (@{manager_username})",
            'courier_name': f"{courier_name} (@{courier_username})",
            'packer_name': f"{packer_name} (@{packer_username})",
            'closed_date': order.get('closed_date'),
        }
        detailed_orders.append(detailed_order)

    return detailed_orders

def get_type_info_by_product_id(product_id):
    """
    Получает информацию о типе продукта, используя ID продукта.
    :param product_id: ID продукта
    :return: Словарь с информацией о типе продукта (название и параметры)
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            # Запрос для получения информации о типе продукта по ID продукта
            query = """
                SELECT tp.id, tp.title, tp.product_parameters 
                FROM type_product tp
                JOIN products p ON tp.id = p.type_id
                WHERE p.id = %s
            """
            cursor.execute(query, (product_id,))
            result = cursor.fetchone()

            if result:
                # Парсим параметры типа продукта
                params = result[2] if isinstance(result[2], dict) else json.loads(result[2])

                return {
                    'id': result[0],
                    'name': result[1],
                    'params': params
                }
            else:
                return None

def get_product_param_info(product_param_id):
    # Получаем информацию о параметрах продукта
    with get_connection() as conn:
        with conn.cursor() as cursor:
            query = """
                SELECT title, param_values
                FROM product_params
                WHERE id = %s
            """
            cursor.execute(query, (product_param_id,))
            result = cursor.fetchone()
            if result:
                return {
                    'title': result[0],
                    'param_values': result[1] if isinstance(result[1], dict) else json.loads(result[1])
                }
    return {}


def get_order_item_info(order_item_id: int):
    """
    Получает информацию о товаре заказа по его ID.

    Args:
        order_item_id: ID товара в заказе

    Returns:
        Dict с информацией о товаре или None
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            query = """
                SELECT 
                    oi.id,
                    oi.product_name,
                    oi.product_param_title,
                    oi.product_values,
                    o.order_type
                FROM order_items oi
                JOIN orders o ON oi.order_id = o.id
                WHERE oi.id = %s
            """
            cursor.execute(query, (order_item_id,))
            result = cursor.fetchone()

            if result:
                return {
                    'id': result[0],
                    'product_name': result[1],
                    'param_title': result[2],
                    'product_values': result[3],
                    'order_type': result[4]
                }
            return None


def update_order_item_status(item_id: int, status: str) -> bool:
    """
    Обновляет статус товара в заказе

    Args:
        item_id: ID товара
        status: Новый статус
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            try:
                query = """
                    UPDATE order_items 
                    SET status = %s::status_order
                    WHERE id = %s
                """
                cursor.execute(query, (status, item_id))
                conn.commit()
                return True
            except Exception as e:
                print(f"Error updating order item status: {e}")
                return False


def get_trip_items_for_order(order_id: int, status: str = None) -> List[Dict]:
    """
    Получает товары заказа в текущей поездке

    Args:
        order_id: ID заказа
        status: Опциональный фильтр по статусу
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            try:
                query = """
                    SELECT 
                        ti.id,
                        ti.status as trip_item_status,
                        oi.id as order_item_id,
                        oi.product_name,
                        oi.product_param_title as param_title,
                        oi.status as order_item_status,
                        o.order_type,
                        o.delivery_address
                    FROM trip_items ti
                    JOIN order_items oi ON ti.order_item_id = oi.id
                    JOIN orders o ON oi.order_id = o.id
                    WHERE oi.order_id = %s
                    AND oi.status = ANY(ARRAY['ready_to_delivery', 'in_delivery', 'partly_delivered']::status_order[])
                """
                params = [order_id]

                if status:
                    query += " AND oi.status = %s::status_order"
                    params.append(status)

                cursor.execute(query, params)
                items = cursor.fetchall()

                return [{
                    'id': item[0],
                    'trip_status': item[1],
                    'order_item_id': item[2],
                    'product_name': item[3],
                    'param_title': item[4],
                    'status': item[5],
                    'order_type': item[6],
                    'delivery_address': item[7]
                } for item in items]

            except Exception as e:
                print(f"Error getting trip items for order: {e}")
                return []


def check_order_completion(order_id: int) -> bool:
    """
    Проверяет, все ли товары заказа доставлены

    Args:
        order_id: ID заказа
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            try:
                query = """
                    SELECT COUNT(*) as total,
                           COUNT(CASE WHEN status = 'closed' THEN 1 END) as closed
                    FROM order_items
                    WHERE order_id = %s
                """
                cursor.execute(query, (order_id,))
                result = cursor.fetchone()
                return result[0] == result[1]  # True если все товары закрыты

            except Exception as e:
                print(f"Error checking order completion: {e}")
                return False

def update_order_delivery_sum(order_id: int, delivery_sum: float) -> bool:
    """Обновляет сумму доставки заказа"""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            try:
                query = """
                    UPDATE orders 
                    SET delivery_sum = %s 
                    WHERE id = %s
                """
                cursor.execute(query, (delivery_sum, order_id))
                conn.commit()
                return True
            except Exception as e:
                print(f"Error updating delivery sum: {e}")
                return False

def update_order_delivery_note(order_id: int, note: str) -> bool:
    """Обновляет заметку курьера к заказу"""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            try:
                query = """
                    UPDATE orders 
                    SET delivery_note = %s 
                    WHERE id = %s
                """
                cursor.execute(query, (note, order_id))
                conn.commit()
                return True
            except Exception as e:
                print(f"Error updating delivery note: {e}")
                return False

def get_trip_total_delivery_sum(trip_id: int) -> float:
    """
    Получает общую сумму доставки для поездки

    Args:
        trip_id: ID поездки
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            try:
                query = """
                    SELECT COALESCE(SUM(o.delivery_sum), 0) as total_delivery_sum
                    FROM trip_items ti
                    JOIN order_items oi ON ti.order_item_id = oi.id
                    JOIN orders o ON oi.order_id = o.id
                    WHERE ti.trip_id = %s
                """
                cursor.execute(query, (trip_id,))
                result = cursor.fetchone()
                return float(result[0]) if result else 0.0

            except Exception as e:
                print(f"Error getting trip delivery sum: {e}")
                return 0.0


def get_delivery_coordinates(order_id: int) -> Optional[Dict]:
    """
    Получает координаты адреса доставки из таблицы delivery_addresses

    Args:
        order_id: ID заказа
    Returns:
        Dict с координатами или None
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            query = """
                SELECT coordinates
                FROM delivery_addresses
                WHERE order_id = %s
            """
            cursor.execute(query, (order_id,))
            result = cursor.fetchone()
            print(result,'result')
            if result and result[0]:
                coordinates = result[0]
                if isinstance(coordinates, str):
                    coordinates = json.loads(coordinates)
                return coordinates
            return None

def increment_stock(product_param_id: int):
    """Увеличивает количество товара на складе на 1"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE product_params 
                    SET stock = stock + 1
                    WHERE id = %s
                """, (product_param_id,))
                conn.commit()
                return True
    except Exception as e:
        print(f"Error in increment_stock: {e}")
        return False

def update_trip_item(status:str,order_item_id):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE trip_items 
                SET status = %s, delivered_at = NOW()
                WHERE order_item_id = %s
            """, (status, order_item_id))


def update_product_stock(param_id: int, quantity: int, is_addition: bool = True) -> bool:
    """
    Обновляет количество товара на складе.

    Args:
        param_id: ID параметра продукта
        quantity: Количество для добавления/вычитания
        is_addition: True для добавления, False для вычитания

    Returns:
        bool: True если операция успешна, False если произошла ошибка
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            try:
                if not is_addition:
                    # Проверяем достаточно ли товара для списания
                    cursor.execute(
                        "SELECT stock FROM product_params WHERE id = %s and is_available = True",
                        (param_id,)
                    )
                    current_stock = cursor.fetchone()[0]
                    if current_stock < quantity:
                        return False

                # Обновляем сток
                cursor.execute("""
                    UPDATE product_params 
                    SET stock = stock {} %s 
                    WHERE id = %s
                    RETURNING stock
                """.format('+' if is_addition else '-'),
                               (quantity, param_id)
                               )

                new_stock = cursor.fetchone()[0]
                if new_stock < 0:
                    conn.rollback()
                    return False

                conn.commit()
                return True

            except Exception as e:
                print(f"Error updating stock: {e}")
                conn.rollback()
                return False


def update_product_prices(product_id: int, sale_price: float, avito_delivery_price: float) -> bool:
    """
    Обновляет цены продукта.

    Args:
        product_id: ID продукта
        sale_price: Цена продажи
        avito_delivery_price: Цена доставки Авито

    Returns:
        bool: True если операция успешна, False если произошла ошибка
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            try:
                cursor.execute("""
                    UPDATE products 
                    SET sale_price = %s, avito_delivery_price = %s
                    WHERE id = %s
                """, (sale_price, avito_delivery_price, product_id))

                conn.commit()
                return True

            except Exception as e:
                print(f"Error updating prices: {e}")
                conn.rollback()
                return False

def get_setting_value(key: str) -> float:
    """Получает значение настройки по ключу"""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT value FROM base_settings WHERE key = %s", (key,))
            result = cursor.fetchone()
            return float(result[0]) if result else 0

def update_setting_value(key: str, value: float) -> bool:
    """Обновляет значение настройки"""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            try:
                cursor.execute(
                    """
                    UPDATE base_settings 
                    SET value = %s, updated_at = now() 
                    WHERE key = %s
                    """,
                    (value, key)
                )
                conn.commit()
                return True
            except Exception as e:
                print(f"Error updating setting: {e}")
                return False

def get_all_settings():
    """Получает все настройки"""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT key, value, description FROM base_settings")
            return cursor.fetchall()


def get_courier_trips(courier_username: str, start_date: str, end_date: str):
    """
    Получает информацию о поездках курьера за указанный период.
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            query = """
                WITH courier_trips_info AS (
                    SELECT 
                        ct.id as trip_id,
                        ct.status as trip_status,
                        ct.created_at,
                        ct.courier_id
                    FROM courier_trips ct
                    JOIN users u ON ct.courier_id = u.id
                    WHERE u.username = %s
                    AND ct.created_at::date BETWEEN %s::date AND %s::date
                ),
                trip_items_info AS (
                    SELECT 
                        ti.trip_id,
                        ti.status as trip_item_status,
                        o.id as order_id,
                        o.order_type,
                        o.delivery_address,
                        o.status as order_status,
                        oi.id as order_item_id,
                        oi.status as order_item_status,
                        p.name as product_name,
                        pp.title as param_title,
                        oi.tracking_number
                    FROM courier_trips_info cti
                    JOIN trip_items ti ON cti.trip_id = ti.trip_id
                    JOIN order_items oi ON ti.order_item_id = oi.id
                    JOIN orders o ON oi.order_id = o.id
                    JOIN products p ON oi.product_id = p.id
                    JOIN product_params pp ON oi.product_param_id = pp.id
                )
                SELECT 
                    cti.trip_id as id,
                    cti.trip_status as status,
                    cti.created_at,
                    COALESCE(jsonb_agg(
                        CASE WHEN tii.order_id IS NOT NULL THEN
                            jsonb_build_object(
                                'order_id', tii.order_id,
                                'order_type', tii.order_type,
                                'delivery_address', tii.delivery_address,
                                'order_status', tii.order_status,
                                'item_status', tii.order_item_status,
                                'order_item_id', tii.order_item_id,
                                'product', jsonb_build_object(
                                    'name', tii.product_name,
                                    'param_title', tii.param_title,
                                    'tracking_number', tii.tracking_number
                                )
                            )
                        ELSE NULL END
                    ) FILTER (WHERE tii.order_id IS NOT NULL), '[]') as items
                FROM courier_trips_info cti
                LEFT JOIN trip_items_info tii ON cti.trip_id = tii.trip_id
                GROUP BY cti.trip_id, cti.trip_status, cti.created_at
                ORDER BY cti.created_at DESC
            """

            cursor.execute(query, (
                f"@{courier_username.lower()}" if not courier_username.startswith('@') else courier_username,
                start_date,
                end_date
            ))

            trips = []
            for row in cursor.fetchall():
                trip = {
                    'id': row[0],
                    'status': row[1],
                    'created_at': row[2],
                    'items': row[3] if row[3] else []
                }
                trips.append(trip)

            return trips


def soft_delete_type_product(type_id: int) -> bool:
    """
    Мягкое удаление типа продукта и всех связанных с ним продуктов
    Args:
        type_id: ID типа продукта
    Returns:
        bool: True если удаление прошло успешно
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            try:
                # Начинаем транзакцию
                cursor.execute("BEGIN")

                # Помечаем тип продукта как недоступный
                cursor.execute("""
                    UPDATE type_product 
                    SET is_available = FALSE 
                    WHERE id = %s
                    RETURNING id
                """, (type_id,))

                if not cursor.fetchone():
                    # Если тип не найден
                    raise Exception("Type product not found")

                # Помечаем все связанные продукты
                cursor.execute("""
                    UPDATE products
                    SET is_available = FALSE
                    WHERE type_id = %s
                """, (type_id,))

                # Помечаем все связанные параметры продуктов
                cursor.execute("""
                    UPDATE product_params pp
                    SET is_available = FALSE
                    FROM products p
                    WHERE p.type_id = %s AND pp.product_id = p.id
                """, (type_id,))

                conn.commit()
                return True

            except Exception as e:
                conn.rollback()
                print(f"Error in soft_delete_type_product: {e}")
                return False


def soft_delete_product(product_id: int) -> bool:
    """
    Мягкое удаление продукта и всех его параметров
    Args:
        product_id: ID продукта
    Returns:
        bool: True если удаление прошло успешно
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            try:
                # Начинаем транзакцию
                cursor.execute("BEGIN")

                # Помечаем продукт как недоступный
                cursor.execute("""
                    UPDATE products 
                    SET is_available = FALSE 
                    WHERE id = %s
                    RETURNING id
                """, (product_id,))

                if not cursor.fetchone():
                    # Если продукт не найден
                    raise Exception("Product not found")

                # Помечаем все параметры продукта
                cursor.execute("""
                    UPDATE product_params
                    SET is_available = FALSE
                    WHERE product_id = %s
                """, (product_id,))

                conn.commit()
                return True

            except Exception as e:
                conn.rollback()
                print(f"Error in soft_delete_product: {e}")
                return False


def soft_delete_product_param(param_id: int) -> bool:
    """
    Мягкое удаление параметра продукта
    Args:
        param_id: ID параметра
    Returns:
        bool: True если удаление прошло успешно
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            try:
                # Начинаем транзакцию
                cursor.execute("BEGIN")

                # Помечаем параметр как недоступный
                cursor.execute("""
                    UPDATE product_params
                    SET is_available = FALSE
                    WHERE id = %s
                    RETURNING id
                """, (param_id,))

                if not cursor.fetchone():
                    # Если параметр не найден
                    raise Exception("Product parameter not found")

                conn.commit()
                return True

            except Exception as e:
                conn.rollback()
                print(f"Error in soft_delete_product_param: {e}")
                return False