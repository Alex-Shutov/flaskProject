from telebot import TeleBot
from config import BOT_TOKEN
from redis_client import save_user_state, load_user_state, delete_user_state

bot = TeleBot(BOT_TOKEN)

def get_bot_instance():
    return bot

def get_user_state(chat_id):
    return load_user_state(chat_id)

def set_user_state(chat_id, state):
    save_user_state(chat_id, state)

def clear_user_state(chat_id):
    delete_user_state(chat_id)