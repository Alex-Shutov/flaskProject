from telebot import types
from bot import get_bot_instance
from database import check_user_access
from utils import get_available_buttons
import handlers.manager
import handlers.courier

from database import get_user_info

bot = get_bot_instance()


@bot.message_handler(commands=['start'])
def start(message,state):
    user_access = get_user_info(message.from_user.username)

    if not user_access:
        bot.reply_to(message, "У вас нет доступа к боту. Обратитесь к администратору для получения доступа.")
        return


    available_buttons = get_available_buttons(user_access['roles'])

    username = message.from_user.username

    # Проверка в Redis
    with state.data() as data:
        user = data.get('user_info')

    if not user:
        # Допустим, получаем user_id из базы данных
        user_info = get_user_info(username)  # Это твоя функция
        if user_info:
            state.add_data(user_info=user_info)  # Сохраняем user_id в Redis

    if not available_buttons:
        bot.reply_to(message,
                     "У вас нет доступа к функциям бота. Обратитесь к администратору для получения необходимых прав.")
        return

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(*available_buttons)
    bot.send_message(message.chat.id, f"Добро пожаловать, {user_access['name']}! Выберите действие:", reply_markup=markup)