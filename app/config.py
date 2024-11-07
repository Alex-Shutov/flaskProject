import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot settings
BOT_TOKEN = os.getenv('BOT_TOKEN')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')

# Telegram Chat Settings
CHANNEL_CHAT_ID = os.getenv('CHANNEL_ID')

# Database settings
DB_NAME = os.getenv('DB_NAME', 'postgres')
DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASSWORD = os.getenv('DB_PASSWORD', '12345')
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '5432')

# Redis
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
REDIS_DB = int(os.getenv('REDIS_DB', 0))

DATABASE_CONFIG = {
    'database': DB_NAME,
    'user': DB_USER,
    'password': DB_PASSWORD,
    'host': DB_HOST,
    'port': DB_PORT
}




# Flask settings
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
PORT = int(os.getenv('PORT', 5000))

WAREHOUSE_LOCATION = {
    'latitude': float(os.getenv('WAREHOUSE_LAT', '56.8519')),  # Пример координат
    'longitude': float(os.getenv('WAREHOUSE_LON', '60.6122'))
}


YANDEX_API_KEY = os.getenv('YANDEX_API_KEY')
DELIVERY_ZONES = {
    'green': {
        'base_price': 100,
        'additional_price': 50
    },
    'yellow': {
        'base_price': 200,
        'additional_price': 75
    },
    'red': {
        'base_price': 300,
        'additional_price': 100
    },
    'purple': {
        'base_price': 400,
        'additional_price': 150
    },
    'white': {
        'base_price': 500,
        'additional_price': 200
    }
}