from telebot.handler_backends import BaseMiddleware
import logging

logger = logging.getLogger(__name__)


class UsernameMiddleware(BaseMiddleware):
    def __init__(self):
        self.update_types = ['message', 'callback_query']
        self.update_sensitive = True

    def pre_process(self, update, data):
        try:
            # Обработка обычных сообщений
            if update.message:
                if not update.message.from_user.username:
                    update.message.from_user.username = f"{update.message.from_user.id}"
                    logger.info(
                        f"Set username to {update.message.from_user.username} for user {update.message.from_user.id}")

            # Обработка callback query
            elif update.callback_query:
                if 'username' not in update.callback_query.message.json['chat'] or \
                        not update.callback_query.message.json['chat']['username']:
                    user_id = update.callback_query.from_user.id
                    update.callback_query.message.json['chat']['username'] = f"{user_id}"
                    logger.info(f"Set username in callback to id{user_id} for user {user_id}")

        except Exception as e:
            logger.error(f"Error in UsernameMiddleware: {e}")
            logger.exception(e)

    def post_process(self, update, data, exception):
        pass

    def pre_process_message(self, message, data):
        """Обработка обычных сообщений"""
        try:
            if not message.from_user.username:
                message.from_user.username = f"{message.from_user.id}"
                logger.info(f"Set username to {message.from_user.username} for user {message.from_user.id}")
        except Exception as e:
            logger.error(f"Error in pre_process_message: {e}")
            logger.exception(e)

    def pre_process_callback_query(self, call, data):
        """Обработка callback query"""
        try:
            if 'username' not in call.message.json['chat'] or \
                    not call.message.json['chat']['username']:
                user_id = call.from_user.id
                call.message.json['chat']['username'] = f"{user_id}"
                logger.info(f"Set username in callback to id{user_id} for user {user_id}")
        except Exception as e:
            logger.error(f"Error in pre_process_callback_query: {e}")
            logger.exception(e)