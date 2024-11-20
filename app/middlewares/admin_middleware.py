from telebot import BaseMiddleware, CancelUpdate, TeleBot
from telebot.states.sync.context import StateContext
import logging


logger = logging.getLogger(__name__)

class AdminCheckMiddleware(BaseMiddleware):
    def __init__(self, bot: TeleBot, admin_commands):
        super().__init__()
        self.update_types = ['message']
        self.update_sensitive = False
        self.bot: TeleBot = bot
        self.admin_commands = admin_commands  # Список админских команд

    def pre_process(self, update, data):
        try:
        # Проверяем, является ли сообщение командой
            command = update.text  # Извлекаем команду из сообщения

            if command in self.admin_commands:  # Проверяем, относится ли команда к админским
                state_context = StateContext(update, self.bot)
                user_id = update.from_user.id
                username = update.from_user.username or str(user_id)

                # Получаем информацию о пользователе
                from handlers.handlers import get_user_by_username
                user_info = get_user_by_username(username, state_context, user_id)

                # Если роль "admin" отсутствует, блокируем выполнение
                if not user_info or 'Admin' not in user_info.get('roles', []) or 'Owner' not in user_info.get('roles', []):
                    self.bot.send_message(update.chat.id,"У вас нет прав для выполнения этой команды.")
                    return CancelUpdate()  # Прерываем выполнение

        except Exception as e:
            logger.error(f"Error in AdminCheckMiddleware: {e}")
            logger.exception(e)

    def post_process(self, update, data, exception):
        pass