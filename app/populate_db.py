import sys
import psycopg2
from psycopg2.extras import execute_values
import argparse
from datetime import datetime

# Parse command line arguments
parser = argparse.ArgumentParser(description='Populate products and product_params tables.')
parser.add_argument('--type_id', default=1, type=int, help='Type product ID')
parser.add_argument('--sale_price', default=800, type=int, help='Sale price for products')
parser.add_argument('--avito_delivery_price', default=200, type=int, help='Avito delivery price')
parser.add_argument('--host', default='localhost', help='Database host')
parser.add_argument('--database', default='your_database', help='Database name')
parser.add_argument('--user', default='your_username', help='Database user')
parser.add_argument('--password', default='your_password', help='Database password')
args = parser.parse_args()

# Connect to the database
conn = psycopg2.connect(
    host=args.host,
    database=args.database,
    user=args.user,
    password=args.password
)
cur = conn.cursor()

# Define our product inventory with details
products_inventory = [
    {"name": "Тотем механика", "price": 12500, "count": 13, "type": "Тотем", "param": "механика"},
    {"name": "Тотем гилравлика", "price": 14000, "count": 10, "type": "Тотем", "param": "гилравлика"},
    {"name": "Тотем женский", "price": 14000, "count": 3, "type": "Тотем", "param": "женский"},
    {"name": "Msep 26 Al", "price": 14800, "count": 7, "type": "Msep", "param": "26 Al"},
    {"name": "SkyWay 26 BMW", "price": 10500, "count": 4, "type": "SkyWay", "param": "26 BMW"},
    {"name": "Фэтбайк б/у", "price": 15000, "count": 1, "type": "Фэтбайк", "param": "б/у"},
    {"name": "SkyWay 27,5", "price": 11500, "count": 1, "type": "SkyWay", "param": "27,5"},
    {"name": "Msep 27,5 Al", "price": 15000, "count": 3, "type": "Msep", "param": "27,5 Al"},
    {"name": "Paruisi 24", "price": 11000, "count": 9, "type": "Paruisi", "param": "24"},
    {"name": "SkyWay 24 женский", "price": 10500, "count": 3, "type": "SkyWay", "param": "24 женский"},
    {"name": "Green 24 складной", "price": 10500, "count": 1, "type": "Green", "param": "24 складной"},
    {"name": "SkyWay 24", "price": 10500, "count": 5, "type": "SkyWay", "param": "24"},
    {"name": "Msep 29", "price": 13000, "count": 4, "type": "Msep", "param": "29"},
    {"name": "Progress 29", "price": 10000, "count": 1, "type": "Progress", "param": "29"}
]

# Filter products based on the type_id parameter
type_query = """
SELECT title FROM type_product WHERE id = %s
"""
cur.execute(type_query, (args.type_id,))
type_result = cur.fetchone()

if not type_result:
    print(f"Error: No type_product found with ID {args.type_id}")
    sys.exit(1)

product_type = type_result[0]

# Get unique product types from the inventory
unique_product_types = set()
for product in products_inventory:
    unique_product_types.add(product["type"])

# Create dictionary to store mapping of product type to product_id
product_id_map = {}

# Current time for timestamps
current_time = datetime.now()

# First, create entries in the products table for each unique product type
for product_type_name in unique_product_types:
    product_insert = """
    INSERT INTO products 
    (name, description, created_at, type_id, product_values, param_parameters, 
    is_main_product, sale_price, avito_delivery_price, is_available, supplier_id)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING id
    """

    description = f"{product_type_name}"
    product_values = "{}"  # JSON empty object for now
    param_parameters = "{}"  # JSON empty object for now
    is_main_product = True
    is_available = True
    supplier_id = None

    cur.execute(product_insert, (
        product_type_name,  # Name is just the product type (e.g., "Тотем")
        description,
        current_time,
        args.type_id,
        product_values,
        param_parameters,
        is_main_product,
        args.sale_price,
        args.avito_delivery_price,
        is_available,
        supplier_id
    ))

    product_id = cur.fetchone()[0]
    product_id_map[product_type_name] = product_id

    print(f"Created product entry for {product_type_name} with ID: {product_id}")

# Now, insert the parameters for each product into product_params
for product in products_inventory:
    product_type_name = product["type"]
    product_id = product_id_map[product_type_name]

    param_insert = """
    INSERT INTO product_params
    (product_id, title, stock, created_at, param_values, is_available)
    VALUES (%s, %s, %s, %s, %s, %s)
    RETURNING id
    """

    cur.execute(param_insert, (
        product_id,
        product["param"],  # The parameter/characteristic (e.g., "механика")
        product["count"],  # Stock count
        current_time,
        "{}",  # JSON empty object for param_values
        True  # is_available
    ))

    param_id = cur.fetchone()[0]
    print(f"Created parameter '{product['param']}' for {product_type_name} with ID: {param_id}")

# Commit changes
conn.commit()

print(
    f"Successfully created {len(unique_product_types)} product types and {len(products_inventory)} product parameters")

# Close connection
cur.close()
conn.close()