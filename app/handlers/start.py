from telebot import types
from bot import get_bot_instance
from database import check_user_access
from utils import get_available_buttons

bot = get_bot_instance()


@bot.message_handler(commands=['start'])
def start(message):
    print(99)
    user_access = check_user_access(message.from_user.username)

    if not user_access:
        bot.reply_to(message, "У вас нет доступа к боту. Обратитесь к администратору для получения доступа.")
        return

    user_id, name, roles = user_access
    available_buttons = get_available_buttons(roles)

    if not available_buttons:
        bot.reply_to(message,
                     "У вас нет доступа к функциям бота. Обратитесь к администратору для получения необходимых прав.")
        return

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(*available_buttons)
    bot.send_message(message.chat.id, f"Добро пожаловать, {name}! Выберите действие:", reply_markup=markup)