import sys
import psycopg2
from psycopg2.extras import execute_values
import argparse
from datetime import datetime

# Parse command line arguments
parser = argparse.ArgumentParser(description='Populate products and product_params tables.')
parser.add_argument('--type_id', default=None, type=int, help='Type product ID (if type_name is not provided)')
parser.add_argument('--type_name', default=None, type=str, help='Type product name (if type_id is not provided)')
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

products_inventory = [
    {"name": "Sk 8", "count": 14, "type": "Sk", "param": "8"},
    {"name": "SkyWay Panda", "count": 9, "type": "SkyWay", "param": "Panda"},
    {"name": "SkyWay 12Ah", "count": 14, "type": "SkyWay", "param": "12Ah"},
    {"name": "SkyWay Tank", "count": 15, "type": "SkyWay", "param": "Tank"},
    {"name": "SkyWay 007", "count": 8, "type": "SkyWay", "param": "007"}
]

# If type_name is provided, insert it into type_product table
if args.type_name:
    type_insert = """
    INSERT INTO type_product (title)
    VALUES (%s)
    RETURNING id
    """
    cur.execute(type_insert, (args.type_name,))
    type_result = cur.fetchone()
    type_id=type_result[0]
    print(f"Created new type_product entry with title '{args.type_name}' and ID: {type_result[0]}")
else:
    # If no type_name provided, use type_id from command line argument
    if args.type_id is None:
        print("Error: Either --type_id or --type_name must be provided")
        sys.exit(1)

    type_id = args.type_id

    # Check if the type_id exists in the database
    type_query = """
        SELECT title FROM type_product WHERE id = %s
        """
    cur.execute(type_query, (type_id,))
    type_result = cur.fetchone()
    print(type_result)
    if not type_result:
        print(f"Error: No type_product found with ID {type_id}")
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
        type_id,
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