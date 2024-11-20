from telebot import TeleBot, custom_filters
from telebot.states.sync.middleware import StateMiddleware
from telebot.storage import StateRedisStorage

from middlewares.user_middleware import UsernameMiddleware
from middlewares.admin_middleware import AdminCheckMiddleware
from config import REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD
from config import BOT_TOKEN
from telebot.states import State, StatesGroup
from redis_client import save_user_state, load_user_state, delete_user_state,redis_client
import states

state_storage = StateRedisStorage(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, password=REDIS_PASSWORD)

# Инициализируем бота с хранилищем состояний
bot = TeleBot(BOT_TOKEN, state_storage=state_storage, use_class_middlewares=True)

admin_commands = [
    "/type_product",
    "/product",
    "/product_param",
    "/manage_stock",
    "/reports",
    "/settings",
    "/pack_info"
]


# Создаем middleware для состояний
state_middleware = StateMiddleware(bot)
username_middleware = UsernameMiddleware()
admin_middleware = AdminCheckMiddleware(bot,admin_commands)
bot.add_custom_filter(custom_filters.StateFilter(bot))

bot.setup_middleware(username_middleware)
bot.setup_middleware(state_middleware)
bot.setup_middleware(admin_middleware)

bot._user=bot.user

def get_bot_instance():
    return bot

def get_user_state(chat_id):
    return load_user_state(chat_id)

def set_user_state(chat_id, state):
    save_user_state(chat_id, state)

def clear_user_state(chat_id):
    delete_user_state(chat_id)