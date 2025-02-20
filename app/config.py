import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot settings
BOT_TOKEN = os.getenv('BOT_TOKEN')

# Telegram Chat Settings
CHANNEL_CHAT_ID = os.getenv('CHANNEL_ID')

# Database settings
DB_NAME = os.getenv('DB_NAME')
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_HOST = os.getenv('DB_HOST')
DB_PORT = os.getenv('DB_PORT')

# Redis
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
REDIS_DB = int(os.getenv('REDIS_DB', 0))
REDIS_PASSWORD=os.getenv('REDIS_PASSWORD',None)

SECRET_TOKEN=os.getenv('SECRET_TOKEN')
SSL_CERT = os.getenv('SSL_CERT', None)
SSL_PRIV = os.getenv('SSL_PRIV', None)
SERVER_HOST = os.getenv('SERVER_HOST', '0.0.0.0')
SERVER_PORT = int(os.getenv('SERVER_PORT', 8443))

DATABASE_CONFIG = {
    'database': DB_NAME,
    'user': DB_USER,
    'password': DB_PASSWORD,
    'host': DB_HOST,
    'port': DB_PORT
}

# Webhook settings
WEBHOOK_HOST = os.getenv('WEBHOOK_HOST')
WEBHOOK_PORT = os.getenv('WEBHOOK_PORT',8443)
WEBHOOK_URL = f"{WEBHOOK_HOST}/{SECRET_TOKEN}"





# Flask settings
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
PORT = int(os.getenv('PORT'))

WAREHOUSE_LOCATION = {
    'latitude': float(os.getenv('WAREHOUSE_LAT')),  # Пример координат
    'longitude': float(os.getenv('WAREHOUSE_LON'))
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