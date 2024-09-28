from bot import get_bot_instance

bot = get_bot_instance()

@bot.message_handler(func=lambda message: message.text == 'Доставка')
def handle_delivery(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "Функционал доставки находится в разработке.")