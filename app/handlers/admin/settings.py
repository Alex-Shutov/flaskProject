from telebot import types
from telebot.states.sync import StateContext

from bot import bot

from database import get_all_settings, update_setting_value
from handlers.handlers import get_user_by_username
from states import AdminStates


@bot.message_handler(commands=['settings'])
def handle_settings_command(message: types.Message, state: StateContext):
    user_info = get_user_by_username(message.from_user.username, state)
    if 'Admin' not in user_info['roles']:
        bot.reply_to(message, "У вас нет доступа к этой команде.")
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("Просмотреть настройки", callback_data="view_settings"),
        types.InlineKeyboardButton("Изменить настройку", callback_data="edit_settings")
    )

    bot.reply_to(message, "Выберите действие:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "view_settings")
def view_settings(call: types.CallbackQuery):
    settings = get_all_settings()
    message = "Текущие настройки:\n\n"
    for key, value, description in settings:
        message += f"{key}: {value}\n{description}\n\n"

    bot.edit_message_text(
        message,
        call.message.chat.id,
        call.message.message_id
    )


@bot.callback_query_handler(func=lambda call: call.data == "edit_settings")
def start_edit_settings(call: types.CallbackQuery, state: StateContext):
    settings = get_all_settings()
    markup = types.InlineKeyboardMarkup(row_width=1)

    for key, value, _ in settings:
        markup.add(types.InlineKeyboardButton(
            f"{key}: {value}",
            callback_data=f"edit#setting#{key}"
        ))

    bot.edit_message_text(
        "Выберите настройку для изменения:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("edit#setting#"))
def edit_setting_value(call: types.CallbackQuery, state: StateContext):
    setting_key = call.data.split('#')[2]
    state.set(AdminStates.edit_setting)
    state.add_data(editing_setting=setting_key)

    bot.edit_message_text(
        f"Введите новое значение для {setting_key}:",
        call.message.chat.id,
        call.message.message_id
    )


@bot.message_handler(state=AdminStates.edit_setting)
def handle_new_setting_value(message: types.Message, state: StateContext):
    try:
        with state.data() as data:
            setting_key = data['editing_setting']

        new_value = message.text.strip()

        if update_setting_value(setting_key, new_value):
            bot.reply_to(message, f"Значение {setting_key} успешно обновлено на {new_value}")
        else:
            bot.reply_to(message, "Произошла ошибка при обновлении значения")
    except ValueError:
        if setting_key == 'default_present':
            bot.reply_to(message, "Пожалуйста, введите текстовое значение")
        else:
            bot.reply_to(message, "Пожалуйста, введите числовое значение")

    state.delete()