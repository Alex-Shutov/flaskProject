import datetime
import json

import psycopg2

from app_types import OrderType
from config import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT

def get_connection():
    return psycopg2.connect(
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT
    )

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
            cursor.execute("SELECT id,title from type_product")
            return cursor.fetchall()


def get_products(type_id=None):
    """Возвращает список продуктов. Если передан тип, фильтрует по нему."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            if type_id:
                # Если type_id передан, фильтруем по нему
                query = "SELECT id, name FROM products WHERE type_id = %s"
                cursor.execute(query, (type_id))
            else:
                # Если type_id не передан, выводим все продукты
                query = "SELECT id, name FROM products"
                cursor.execute(query)

            return cursor.fetchall()


def get_product_params(product_id):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, title,stock FROM product_params WHERE product_id = %s", (product_id,))
            return cursor.fetchall()


def create_order(product_dict, gift, note, sale_type, manager_id, message_id,
                 avito_photos_tracks=None, packer_id=None, status_order=OrderType.ACTIVE.value,
                 delivery_date=None, delivery_time=None, delivery_address=None,
                 delivery_note=None, contact_phone=None, contact_name=None, total_price=None):
    """
    Создает новый заказ в базе данных и добавляет продукты в order_items.
    Теперь фотографии и трек-номера сохраняются в таблицу avito_photos.
    """
    print(product_dict, gift, sale_type, manager_id, message_id, packer_id, status_order,
          delivery_date, delivery_time, delivery_address, delivery_note, contact_phone, contact_name, total_price)

    with get_connection() as conn:
        with conn.cursor() as cursor:
            # Создаем запись в таблице orders
            query = """
                INSERT INTO orders (
                    gift, note, order_type, manager_id, 
                    message_id, packer_id, created_at, status,
                    delivery_date, delivery_time, delivery_address, 
                    delivery_note, contact_phone, contact_name, total_price,avito_boxes_count
                )
                VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s, %s, %s, %s, %s,%s)
                RETURNING id;
            """
            cursor.execute(query, (
                gift, note, sale_type, manager_id, message_id, packer_id, status_order,
                delivery_date, delivery_time, delivery_address, delivery_note, contact_phone, contact_name, total_price,
                len(avito_photos_tracks.keys()) if avito_photos_tracks else 0
            ))
            print(1234222)
            order_id = cursor.fetchone()[0]
            product_info_list = []

            # Добавляем все продукты и их параметры в order_items
            for product_id, param_ids in product_dict.items():
                for param_id in param_ids:
                    product_info = get_product_info_with_params(product_id, param_id)
                    print(product_info)

                    if isinstance(product_info, tuple):
                        product_name = product_info[0]  # name должен быть первым элементом
                        product_values = product_info[1]  # product_values - вторым
                        is_main_product = product_info[2]  # is_main_product - третьим
                    else:
                        product_name = product_info['name']
                        product_values = product_info['product_values']
                        is_main_product = product_info['is_main_product']
                        param_title = product_info['param_title']

                    # Добавляем продукт в order_items
                    cursor.execute("""
                        INSERT INTO order_items (
                            order_id, product_id, product_param_id, product_name, product_param_title, 
                            product_values, is_main_product, status, created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s::public.status_order, NOW())
                    """, (order_id, product_id, param_id, product_name, param_title, json.dumps(product_values),
                          is_main_product, status_order))

                    product_info_list.append({
                        'product_id': product_id,
                        'product_name': product_name,
                        'is_main_product': is_main_product,
                        'param_title': param_title,
                        'param_id': param_id,
                    })
            # Добавляем фотографии и трек-номера в таблицу avito_photos
            if avito_photos_tracks:
                for photo_path, track_number in avito_photos_tracks.items():
                    cursor.execute("""
                        INSERT INTO avito_photos (order_id, photo_path, tracking_number, created_at)
                        VALUES (%s, %s, %s, NOW())
                    """, (order_id, photo_path, track_number))

            conn.commit()
            return {'id': order_id, 'values': product_info_list}


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
            cursor.execute("SELECT name,is_main_product FROM products WHERE id = %s", (product_id,))
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


def get_orders(order_type=None, username=None, status=None, is_courier_null=False, start_date=None, end_date=None, role=None):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            # Строим запрос динамически
            query = """
                SELECT o.id, o.product_id, o.product_param_id, o.gift, o.note, o.order_type, o.status, o.created_at,
                       o.manager_id, o.message_id, o.avito_photo, o.closed_date, o.packer_id, o.courier_id,
                       o.delivery_date, o.delivery_time, o.delivery_address, o.delivery_note, o.contact_phone, o.contact_name, o.total_price
                FROM orders o
                WHERE 1=1
            """

            params = []

            if order_type and isinstance(order_type, list):
                query += " AND o.order_type = ANY(%s)"
                params.append(order_type)

            if status and isinstance(status, list):
                query += " AND o.status = ANY(%s::public.status_order[])"
                params.append(status)

            if username:
                formatted_username = username if username.startswith('@') else f"@{username.lower()}"
                cursor.execute("SELECT id FROM users WHERE username = %s", (formatted_username,))
                user_id = cursor.fetchone()
                if not user_id:
                    return []
                if role == 'courier':
                    query += " AND o.courier_id = %s"
                elif role == 'packer':
                    query += " AND o.packer_id = %s"
                params.append(user_id[0])

            if is_courier_null:
                query += " AND o.courier_id IS NULL"

            if start_date and end_date:
                query += " AND o.closed_date BETWEEN %s AND %s"
                params.append(start_date)
                params.append(end_date)

            if order_type and isinstance(order_type, list):
                query += " ORDER BY CASE"
                for idx, o_type in enumerate(order_type):
                    query += f" WHEN o.order_type = %s THEN {idx}"
                    params.append(o_type)
                query += " END"

            if status and isinstance(status, list):
                query += ", CASE"
                for idx, st in enumerate(status):
                    query += f" WHEN o.status = %s THEN {idx}"
                    params.append(st)
                query += " END"
            query += ", o.id ASC"

            cursor.execute(query, tuple(params))
            orders = cursor.fetchall()

            formatted_orders = [
                {
                    'id': order[0],
                    'product_id': order[1],
                    'product_param_id': order[2],
                    'gift': order[3],
                    'note': order[4],
                    'order_type': order[5],
                    'status': order[6],
                    'created_at': order[7],
                    'manager_id': order[8],
                    'message_id': order[9],
                    'avito_photo': order[10],
                    'closed_date': order[11],
                    'packer_id': order[12],
                    'courier_id': order[13],
                    'delivery_date': order[14],
                    'delivery_time': order[15],
                    'delivery_address': order[16],
                    'delivery_note': order[17],
                    'contact_phone': order[18],
                    'contact_name': order[19],
                    'total_price': order[20]
                }
                for order in orders
            ]

            return formatted_orders



def update_order_status(order_id, status):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            # Обновляем статус заказа
            cursor.execute("UPDATE orders SET status = %s::public.status_order WHERE id = %s", (status, order_id))

            # Обновляем статус всех продуктов в комплектации заказа
            cursor.execute("UPDATE order_items SET status = %s::public.status_order WHERE order_id = %s", (status, order_id))

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


def update_order_invoice_photo(order_id, photo_path):
    """Обновляет путь к фотографии накладной в заказе."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            query = """
                UPDATE orders
                SET invoice_photo = %s
                WHERE id = %s
            """
            cursor.execute(query, (photo_path, order_id))
            conn.commit()


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
    Возвращает список активных заказов без назначенного упаковщика с информацией о продуктах.
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            # Получаем заказы без упаковщика
            query = """
                SELECT o.id, o.gift, o.note, o.order_type, o.status, o.created_at, 
                       o.manager_id, o.message_id,o.avito_boxes_count
                FROM orders o
                WHERE o.status = 'active' AND o.packer_id IS NULL
            """
            cursor.execute(query)
            orders = cursor.fetchall()

            # Форматируем заказы как список словарей
            formatted_orders = [
                {
                    'id': order[0],
                    'gift': order[1],
                    'note': order[2],
                    'order_type': order[3],
                    'status': order[4],
                    'created_at': order[5],
                    'manager_id': order[6],
                    'message_id': order[7],
                    'avito_boxes':order[8],
                    'products': []  # Здесь будем хранить список продуктов
                }
                for order in orders
            ]

            # Получаем список продуктов для всех заказов
            order_ids = [order['id'] for order in formatted_orders]
            if order_ids:
                query_products = """
                    SELECT oi.order_id, p.id AS product_id, p.name AS product_name, 
                           oi.is_main_product, pp.title AS param_title, pp.id AS param_id
                    FROM order_items oi
                    JOIN products p ON oi.product_id = p.id
                    JOIN product_params pp ON oi.product_param_id = pp.id
                    WHERE oi.order_id IN %s
                """
                cursor.execute(query_products, (tuple(order_ids),))
                products = cursor.fetchall()

                # Добавляем продукты к соответствующим заказам
                for product in products:
                    for order in formatted_orders:
                        if order['id'] == product[0]:
                            order['products'].append({
                                'product_id': product[1],
                                'product_name': product[2],
                                'is_main_product': product[3],
                                'param_title': product[4],
                                'param_id': product[5]
                            })

            return formatted_orders

def get_order_by_id(order_id):
    """
    Возвращает заказ по его ID.

    :param order_id: ID заказа
    :return: Заказ в виде словаря, если найден, иначе None
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            # Строим запрос для получения заказа по ID
            query = """
                SELECT o.id, o.product_id, o.product_param_id, o.gift, o.note, o.order_type, o.status, o.created_at, 
                       o.manager_id, o.message_id, o.avito_photo, o.closed_date, o.packer_id, o.courier_id
                FROM orders o
                WHERE o.id = %s
            """
            cursor.execute(query, (order_id,))
            order = cursor.fetchone()

            if order:
                # Форматируем результат как словарь для удобства
                formatted_order = {
                    'id': order[0],
                    'product_id': order[1],
                    'product_param_id': order[2],
                    'gift': order[3],
                    'note': order[4],
                    'order_type': order[5],
                    'status': order[6],
                    'created_at': order[7],
                    'manager_id': order[8],
                    'message_id': order[9],
                    'avito_photo': order[10],
                    'closed_date': order[11],
                    'packer_id': order[12],
                    'courier_id': order[13]
                }
                return formatted_order
            else:
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
            query = "SELECT id, title, product_parameters, created_at FROM type_product"
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
            query = "SELECT id, name, param_parameters, type_id, product_values,is_main_product FROM products WHERE id = %s"
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
                    cursor.execute("SELECT title FROM product_params WHERE id = %s", (param_id,))
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
            query = "SELECT id, title, product_parameters, created_at FROM type_product WHERE id = %s"
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
    :param order_id: ID заказа для получения product_id и product_param_id
    :param product_id: ID продукта (опционально, если указан order_id)
    :param product_param_id: ID параметра продукта (опционально, если указан order_id)
    :param quantity: Количество для вычитания из стока, по умолчанию 1
    """
    if order_id is None and (product_id is None or product_param_id is None):
        raise ValueError("Необходимо указать либо order_id, либо product_id и product_param_id.")

    with get_connection() as conn:
        with conn.cursor() as cursor:
            try:
                # Если указан order_id, извлекаем product_id и product_param_id из заказа
                if order_id is not None:
                    cursor.execute("""
                        SELECT product_id, product_param_id 
                        FROM orders 
                        WHERE id = %s
                    """, (order_id,))
                    result = cursor.fetchone()

                    if result is None:
                        raise ValueError(f"Заказ с ID {order_id} не найден.")

                    product_id, product_param_id = result
                    print(f"Извлеченные данные по заказу: product_id={product_id}, product_param_id={product_param_id}")

                # Проверка стока и блокировка строки
                cursor.execute("""
                    SELECT stock 
                    FROM product_params 
                    WHERE product_id = %s AND id = %s FOR UPDATE
                """, (product_id, product_param_id))
                current_stock = cursor.fetchone()

                if current_stock is None:
                    raise ValueError(f"Продукт с ID {product_id} и параметром {product_param_id} не найден.")

                if current_stock[0] < quantity:
                    raise ValueError("Недостаточно стока для выполнения операции.")

                # Уменьшаем значение стока и обновляем запись
                new_stock = current_stock[0] - quantity
                cursor.execute("""
                    UPDATE product_params 
                    SET stock = %s 
                    WHERE product_id = %s AND id = %s
                """, (new_stock, product_id, product_param_id))
                conn.commit()

                print(f"Сток успешно уменьшен на {quantity}. Новый сток: {new_stock}")

            except Exception as e:
                conn.rollback()
                print(f"Произошла ошибка при обновлении стока: {e}")


def get_all_products_with_stock(type_id=None):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            query = """
                SELECT p.id, p.name, tp.title AS type_name, p.product_values, pp.title AS param_title, 
                       pp.param_values, pp.stock , pp.title
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
                # Проверяем, что данные существуют и обрабатываем их
                product_values = row[3] if isinstance(row[3], dict) else (json.loads(row[3]) if row[3] else {})
                product_param_values = row[5] if isinstance(row[5], dict) else (json.loads(row[5]) if row[5] else {})
                stock = row[6]
                param_title = row[7]
                # Если тип продукта еще не был добавлен, инициализируем его
                if product_type not in products_by_type:
                    products_by_type[product_type] = []

                # Добавляем продукт в структуру
                products_by_type[product_type].append({
                    'id': product_id,
                    'name': product_name,
                    'product_values': product_values,
                    'product_param_values': product_param_values,
                    'stock': stock,
                    'param_title':param_title
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