import requests

from config import WEBHOOK_URL, SECRET_TOKEN, BOT_TOKEN


def set_webhook():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
    data = {
        'url': WEBHOOK_URL,
        # Указываем, какие типы обновлений мы хотим получать
        'allowed_updates': ['message', 'callback_query', 'inline_query']
    }

    response = requests.post(url, json=data)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")


if __name__ == "__main__":
    set_webhook()
