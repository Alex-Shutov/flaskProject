import psycopg2
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

def get_products():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, name FROM products")
            return cursor.fetchall()

def get_product_params(product_id):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, size FROM product_params WHERE product_id = %s", (product_id,))
            return cursor.fetchall()

def create_order(product_id, param_id, gift, note, sale_type, manager_id,message_id = None,avito_photo = None):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO orders (product_id, product_param_id, gift, note, order_type, manager_id,avito_photo,message_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s,%s,%s, NOW())
                RETURNING id
            """, (product_id, param_id, gift, note, sale_type, manager_id,avito_photo,message_id))
            order_id = cursor.fetchone()[0]
            conn.commit()
            return order_id

def get_product_info(product_id, param_id):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT name FROM products WHERE id = %s", (product_id,))
            product_name = cursor.fetchone()[0]
            cursor.execute("SELECT size FROM product_params WHERE id = %s", (param_id,))
            product_param = cursor.fetchone()[0]
            return product_name, product_param
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


def get_orders(order_type=None, username=None, status=None, is_courier_null=False):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            # Строим запрос динамически
            query = """
                SELECT o.id, o.product_id, o.product_param_id, o.gift, o.note, o.order_type, o.status
                FROM orders o
                WHERE 1=1
            """

            # Параметры для подстановки в запрос
            params = []

            # Фильтруем по типу заказа (если указан)
            if order_type:
                query += " AND o.order_type = %s"
                params.append(order_type)

            # Фильтруем по нескольким статусам, если передан список статусов
            if status and isinstance(status, list):
                query += " AND o.status = ANY(%s)"
                params.append(status)

            # Фильтруем по курьеру (если указан username)
            if username:
                cursor.execute("SELECT id FROM users WHERE username = %s", (f"@{username.lower()}",))
                user_id = cursor.fetchone()

                if not user_id:
                    return []

                query += " AND o.courier_id = %s"
                params.append(user_id[0])

            # Фильтруем заказы без назначенного курьера, если это указано
            if is_courier_null:
                query += " AND o.courier_id IS NULL"

            # Выполняем запрос с динамическими параметрами
            cursor.execute(query, tuple(params))
            orders = cursor.fetchall()

            # Форматируем результат как список словарей для удобства
            formatted_orders = [
                {
                    'id': order[0],
                    'product_id': order[1],
                    'product_param_id': order[2],
                    'gift': order[3],
                    'note': order[4],
                    'order_type': order[5],
                    'status': order[6]
                }
                for order in orders
            ]

            return formatted_orders


def update_order_status(order_id, status):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE orders SET status = %s WHERE id = %s", (status, order_id))
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



