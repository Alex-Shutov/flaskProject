from telebot.states.sync.context import StateContext
from database import get_user_info


def get_user_by_username(username, state):
    """
    Получает информацию о пользователе из state. Если информации нет, запрашивает её из БД и сохраняет в state.

    :param username: Имя пользователя
    :param state: Контекст состояния для хранения данных
    :return: Словарь с информацией о пользователе (id, имя, username, роли) или None, если не найден
    """
    # Проверяем данные в state
    with state.data() as user_data:
        user_info = user_data.get('user_info')

    if not user_info:
        # Если нет в state, получаем из базы данных
        user_info = get_user_info(username)  # Это функция запроса к базе данных

        if user_info:
            # Сохраняем данные в state
             state.add_data(user_info=user_info)
        else:
            return None  # Если пользователь не найден в БД

    return user_info
