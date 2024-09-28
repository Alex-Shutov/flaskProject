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


def get_manager_info(username):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, name, username FROM users WHERE username = %s", (f"@{username.lower()}",))
            return cursor.fetchone()

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

def create_order(product_id, param_id, gift, note, sale_type, manager_id):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO orders (product_id, product_param_id, gift, note, order_type, manager_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                RETURNING id
            """, (product_id, param_id, gift, note, sale_type, manager_id))
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