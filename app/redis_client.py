import redis
import json
from config import REDIS_HOST, REDIS_PORT, REDIS_DB
# Настройка подключения к Redis
redis_client = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)

def save_user_state(chat_id, state):
    state_json = json.dumps(state)  # Преобразуем состояние в JSON-строку
    redis_client.set(f"user_state:{chat_id}", state_json)

def load_user_state(chat_id):
    state_json = redis_client.get(f"user_state:{chat_id}")
    if state_json:
        return json.loads(state_json)  # Преобразуем JSON обратно в словарь
    return {}

def delete_user_state(chat_id):
    redis_client.delete(f"user_state:{chat_id}")
