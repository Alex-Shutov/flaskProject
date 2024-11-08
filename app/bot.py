from telebot import TeleBot
from telebot.storage import StateRedisStorage

from config import REDIS_HOST, REDIS_PORT, REDIS_DB
from config import BOT_TOKEN
from telebot.states import State, StatesGroup
from redis_client import save_user_state, load_user_state, delete_user_state,redis_client
import states

state_storage = StateRedisStorage(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)

# Инициализируем бота с хранилищем состояний
bot = TeleBot(BOT_TOKEN, state_storage=state_storage,use_class_middlewares=True)

def get_bot_instance():
    return bot

def get_user_state(chat_id):
    return load_user_state(chat_id)

def set_user_state(chat_id, state):
    save_user_state(chat_id, state)

def clear_user_state(chat_id):
    delete_user_state(chat_id)