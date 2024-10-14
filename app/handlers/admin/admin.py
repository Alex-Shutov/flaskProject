from telebot import types
from bot import bot
from telebot.states.sync.context import StateContext
from database import create_type_product, create_product, create_product_param, get_type_product_params
from states import AdminStates
import json

from handlers.parse_params import identify_param_type, parse_enum_options

from handlers.parse_params import validate_number, create_enum_keyboard

from database import get_all_type_products

from database import get_all_product_params, get_all_products

from database import get_product_info_with_params

from handlers.handlers import get_user_by_username
from states import ReportStates

from handlers.admin.reports import generate_sales_report, generate_stock_report


#
#
# @bot.message_handler(commands=['type_product', 'product', 'product_param'])
# def handle_admin_command(message: types.Message, state: StateContext):
#     command = message.text.replace("/", "")
#
#     # Создаем инлайн-клавиатуру CRUD
#     markup = types.InlineKeyboardMarkup(row_width=2)
#     markup.add(
#         types.InlineKeyboardButton("Добавить", callback_data=f"{command}-add"),
#         types.InlineKeyboardButton("Посмотреть", callback_data=f"{command}-view"),
#         types.InlineKeyboardButton("Редактировать", callback_data=f"{command}-edit"),
#         types.InlineKeyboardButton("Удалить", callback_data=f"{command}-delete")
#     )
#
#     bot.send_message(message.chat.id, f"Выберите действие':", reply_markup=markup)
#

@bot.message_handler(commands=['type_product', 'product', 'product_param'])
def handle_admin_command(message: types.Message, state: StateContext):
    command = message.text.replace("/", "")
    # Сохраняем команду в состоянии для использования на следующих шагах
    state.set(AdminStates.admin_command)
    state.add_data(admin_command=command)
    # Запрашиваем тип продукта, если это не команда для типа продукта
    if command != 'type_product':
        # Показываем все доступные типы продуктов
        type_products = get_all_type_products()


        if not type_products:
            bot.send_message(message.chat.id, "Нет доступных типов продуктов.")
            return

        markup = types.InlineKeyboardMarkup(row_width=1)
        for type_product in type_products:
            markup.add(types.InlineKeyboardButton(
                type_product['name'],
                callback_data=f"select_type_{type_product['id']}"
            ))
        state.add_data(choose_type_product=type_products)
        bot.send_message(message.chat.id, "Выберите тип продукта для дальнейших действий:", reply_markup=markup)
        state.set(AdminStates.choose_type_product)
    else:
        # Если это команда для работы с типом продукта, сразу показываем CRUD-клавиатуру
        show_crud_keyboard(message, command)


@bot.callback_query_handler(func=lambda call: call.data.startswith("select_type_"),
                            state=AdminStates.choose_type_product)
def handle_type_product_selection(call: types.CallbackQuery, state: StateContext):
    type_product_id = int(call.data.split("_")[-1])

    # Получаем полную информацию о выбранном типе продукта
    type_products = get_all_type_products()
    selected_type_product_info = next((tp for tp in type_products if tp['id'] == type_product_id), None)

    if not selected_type_product_info:
        bot.send_message(call.message.chat.id, "Тип продукта не найден.")
        return

    # Сохраняем полную информацию о типе продукта в состоянии
    state.add_data(selected_type_product_info=selected_type_product_info)

    # Получаем команду, по которой пользователь вызвал выбор типа продукта
    with state.data() as data:
        admin_command = data.get("admin_command")

    if admin_command == "product":
        # Для команды product сразу отображаем CRUD-клавиатуру
        show_crud_keyboard(call.message, admin_command)
        state.set(AdminStates.admin_command)
    elif admin_command == "product_param":
        # Для команды product_param, переходим к выбору конкретного продукта
        products = get_all_products(selected_type_product_info['id'])
        if not products:
            bot.send_message(call.message.chat.id, "Нет продуктов для выбранного типа.")
            return

        # Формируем клавиатуру для выбора продукта
        markup = types.InlineKeyboardMarkup(row_width=1)
        for product in products:
            markup.add(types.InlineKeyboardButton(
                f"{product['name']}",
                callback_data=f"select_product_{product['id']}"
            ))

        bot.send_message(call.message.chat.id, "Выберите продукт для управления его параметрами:", reply_markup=markup)
        state.set(AdminStates.choose_product)
    else:
        bot.send_message(call.message.chat.id, "Неизвестная команда. Попробуйте еще раз.")


@bot.callback_query_handler(func=lambda call: call.data.startswith("select_product_"), state=AdminStates.choose_product)
def handle_product_selection(call: types.CallbackQuery, state: StateContext):
    product_id = int(call.data.split("_")[-1])

    # Сохраняем выбранный продукт в состоянии
    state.add_data(selected_product_id=product_id)

    # Показываем CRUD-клавиатуру для управления параметрами продукта
    show_crud_keyboard(call.message, "product_param")

@bot.callback_query_handler(func=lambda call: call.data.endswith('-add'))
def handle_add_action(call: types.CallbackQuery, state: StateContext):
    action = call.data.split('-')[0]
    print(action)
    if action == 'type_product':
        bot.send_message(call.message.chat.id, "Введите название для типа продукта:")
        state.set(AdminStates.enter_type_product_name)
    elif action == 'product':
        bot.send_message(call.message.chat.id, "Введите название продукта:")
        state.set(AdminStates.enter_product_name)
    elif action == 'product_param':
        # Начинаем с ввода title параметра
        bot.send_message(call.message.chat.id, "Введите свойство(размер) продукта:")
        state.set(AdminStates.enter_product_param_title)


@bot.message_handler(state=AdminStates.enter_product_param_title)
def enter_product_param_title(message: types.Message, state: StateContext):
    title = message.text.strip()

    # Сохраняем title в состояние
    state.add_data(product_param_title=title)

    # Проверяем наличие параметров у текущего продукта
    with state.data() as data:
        product_id = data.get('selected_product_id')
        product_info = get_product_info_with_params(product_id)
        print('product_info')
        print('product_info')
        param_parameters = product_info.get('param_parameters', {})

    if not param_parameters:
        # Если параметров нет, переходим к вводу stock
        bot.send_message(message.chat.id, "У данного продукта нет параметров для заполнения.")
        bot.send_message(message.chat.id, "Введите количество (stock) для продукта:")
        state.set(AdminStates.enter_product_stock)
    else:
        # Переход к вводу значений параметров
        print(123444444)
        formatted_params = format_product_params(param_parameters)
        message_text = (
            f"Введите значения для следующих параметров:\n\n"
            f"{formatted_params}\n\n"
            "Значения указывайте через запятую в том же порядке."
        )
        bot.send_message(message.chat.id, message_text)
        state.set(AdminStates.enter_product_param_values)


@bot.message_handler(state=AdminStates.enter_product_param_values)
def enter_product_param_values(message: types.Message, state: StateContext):
    param_values = message.text.split(',')

    with state.data() as data:
        product_id = data.get('selected_product_id')
        product_info = get_product_info_with_params(product_id)
        print('product_info')
        print(product_info)
        param_parameters = product_info.get('param_parameters', {})

    if len(param_values) != len(param_parameters):
        bot.send_message(message.chat.id,
                         "Количество введенных значений не совпадает с количеством параметров. Попробуйте снова.")
        return

    validated_params = {}
    for idx, (param_name, param_info) in enumerate(param_parameters.items()):
        param_value = param_values[idx].strip()

        if param_info['type'] == 'number':
            if not validate_number(param_value):
                bot.send_message(message.chat.id, f"Значение параметра '{param_name}' должно быть числом.")
                return
            validated_params[param_name] = float(param_value)
        elif param_info['type'] == 'enum':
            if param_value not in param_info['options']:
                options_list = ', '.join(param_info['options'])
                bot.send_message(message.chat.id,
                                 f"Значение параметра '{param_name}' должно быть одним из следующих: {options_list}")
                return
            validated_params[param_name] = param_value
        else:
            validated_params[param_name] = param_value

    state.add_data(product_param_values=validated_params)

    # Переход к шагу ввода stock
    bot.send_message(message.chat.id, "Введите количество (stock) для продукта:")
    state.set(AdminStates.enter_product_stock)

@bot.message_handler(state=AdminStates.enter_product_stock)
def enter_product_stock(message: types.Message, state: StateContext):
    try:
        stock = int(message.text)
        if stock < 0:
            raise ValueError("Stock не может быть отрицательным")
    except ValueError:
        bot.send_message(message.chat.id, "Введите положительное число для количества (stock).")
        return

    with state.data() as data:
        product_id = data.get('selected_product_id')
        title = data.get('product_param_title')
        param_values = data.get('product_param_values', {})

    # Создание product_param в базе данных
    create_product_param(product_id, title, stock, param_values)
    print(param_values)
    print('param_values')
    # Сообщение о завершении
    formatted_values = format_type_product_values(param_values)
    bot.send_message(
        message.chat.id,
        f"Параметры для продукта '{title}' успешно добавлены:\n"
        f"Значения параметров продукта: \n{formatted_values}\n"
        f"Количество: {stock}"
    )

    # Завершаем создание и очищаем состояние
    state.delete()


@bot.callback_query_handler(func=lambda call: call.data.endswith('-view'))
def handle_view_command(call: types.CallbackQuery, state: StateContext):
    command = call.data.split('-')[0]

    if command == "type_product":
        # Получаем список типов продуктов из базы данных
        type_products = get_all_type_products()
        for type_product in type_products:
            name = type_product['name']
            params = type_product['params']
            creation_date = type_product['created_at']

            # Форматируем список параметров
            formatted_params = format_product_params(params)

            # Формируем текст сообщения
            message_text = (
                f"Тип продукта: {name}\n\n"
                f"Параметры:\n{formatted_params}\n"
                f"Дата создания: {creation_date}"
            )

            # Отправляем сообщение пользователю
            bot.send_message(call.message.chat.id, message_text)

    elif command == "product":
        # Получаем список продуктов для выбранного типа
        with state.data() as data:
            type_product_id = data.get('selected_type_product_id')
        products = get_all_products(type_product_id)

        if not products:
            bot.send_message(call.message.chat.id, "Продукты не найдены.")
            return

        for product in products:
            product_name = product['name']
            product_params = product['params']
            product_values = product['values']
            creation_date = product['created_at']

            # Форматируем параметры и их значения
            formatted_values = format_product_values(product_params, product_values)

            # Формируем текст сообщения
            message_text = (
                f"Продукт: {product_name}\n\n"
                f"Значения параметров:\n{formatted_values}\n"
                f"Дата создания: {creation_date}"
            )

            # Отправляем сообщение пользователю
            bot.send_message(call.message.chat.id, message_text)


    elif command == "product_param":

        # Получаем параметры продукта

        with state.data() as data:

            product_id = data.get('selected_product_id')

        product_params = get_all_product_params(product_id)

        if not product_params:
            bot.send_message(call.message.chat.id, "Параметры продукта не найдены.")

            return

        for param in product_params:

            param_name = param['name']

            param_values = param['params']  # Предполагается, что это словарь

            creation_date = param['created_at']

            # Формируем текст сообщения для параметров

            if isinstance(param_values, dict) and param_values:

                formatted_values = "\n".join([f"{key}: {value}" for key, value in param_values.items()])

            else:

                formatted_values = "Нет указанных значений"

            # Формируем текст сообщения

            message_text = (

                f"Параметр продукта: {param_name}\n\n"

                f"Значения:\n{formatted_values}\n\n"

                f"Дата создания: {creation_date}"

            )

            # Отправляем сообщение пользователю

            bot.send_message(call.message.chat.id, message_text)

    else:
        bot.send_message(call.message.chat.id, "Неверная команда.")


@bot.message_handler(state=AdminStates.enter_type_product_name)
def enter_type_product_name(message: types.Message, state: StateContext):
    state.add_data(enter_type_product_name=message.text)

    # Создаем инлайн-клавиатуру с кнопкой "Пропустить"
    skip_markup = types.InlineKeyboardMarkup()
    skip_markup.add(types.InlineKeyboardButton("Пропустить", callback_data="skip_type_product_params"))

    bot.send_message(
        message.chat.id,
        "Введите базовые параметры для типа продукта с типами данных.\n\n"
        "На текущий момент поддерживаются следующие типы данных:\n"
        "- Строка: просто название\n"
        "- Перечисление: Название(параметр1, параметр2,...)\n"
        "- Число: +Название+\n\n"
        "Каждый параметр начинается с новой строки",
        reply_markup=skip_markup
    )

    state.set(AdminStates.enter_type_product_params)


# Обработка параметров типа продукта
@bot.message_handler(state=AdminStates.enter_type_product_params)
def enter_type_product_params(message: types.Message, state: StateContext):
    raw_params = message.text.split('\n')
    params = {}

    # Парсинг параметров и определение их типа
    for param in raw_params:
        param = param.strip()
        param_name = param.replace('+', '').split('(')[0].strip()
        param_type = identify_param_type(param)

        # Сохраняем тип параметра и его значения для перечислений
        params[param_name] = {
            'type': param_type,
            'options': parse_enum_options(param) if param_type == 'enum' else None
        }

    with state.data() as data:
        type_product_name = data['enter_type_product_name']

    create_type_product(type_product_name, params)

    # Формируем сообщение для подтверждения создания типа продукта
    message_text = f"Тип продукта '{type_product_name}' с параметрами:\n\n"
    for param_name, param_info in params.items():
        if param_info['type'] == 'string':
            message_text += f"{param_name} - Строка\n"
        elif param_info['type'] == 'enum':
            options = ', '.join(param_info['options'])
            message_text += f"{param_name} - Перечисление ({options})\n"
        elif param_info['type'] == 'number':
            message_text += f"{param_name} - Число\n"

    message_text += "\nУспешно создан. Теперь для данного типа вы можете создать продукты (модели)."
    bot.send_message(message.chat.id, message_text)

    # Переход к следующему шагу
    state.set(AdminStates.enter_inherited_param_values)


# Обработчик кнопки "Пропустить"
@bot.callback_query_handler(func=lambda call: call.data == "skip_type_product_params")
def skip_type_product_params(call: types.CallbackQuery, state: StateContext):
    with state.data() as data:
        type_product_name = data['enter_type_product_name']

    # Передаем пустой словарь параметров на бэкенд
    create_type_product(type_product_name, {})

    # Подтверждаем успешное создание типа продукта без параметров
    message_text = f"Тип продукта '{type_product_name}' создан без параметров. Теперь для данного типа вы можете создать продукты (модели)."
    bot.edit_message_text(message_text, chat_id=call.message.chat.id, message_id=call.message.message_id)

    # Переход к следующему шагу
    state.set(AdminStates.enter_inherited_param_values)


@bot.callback_query_handler(func=lambda call: call.data == 'manage_products')
def handle_manage_products(call, state: StateContext):
    # Получаем все типы продуктов из базы данных
    type_products = get_all_type_products()

    if not type_products:
        bot.send_message(call.message.chat.id, "Нет доступных типов продуктов.")
        return

    markup = types.InlineKeyboardMarkup()
    for type_product in type_products:
        markup.add(types.InlineKeyboardButton(
            type_product['name'],
            callback_data=f"type_product_select_{type_product['id']}"
        ))

    # Добавляем кнопку "Выбрать"
    markup.add(types.InlineKeyboardButton("Выбрать", callback_data="confirm_type_product"))

    bot.send_message(call.message.chat.id, "Выберите тип продукта:", reply_markup=markup)
    state.set(AdminStates.choose_type_product)

# # Шаг 1: Начало создания продукта
# @bot.message_handler(state=AdminStates.enter_inherited_param_values)
# def enter_inherited_param_values(message: types.Message, state: StateContext):
#     params = state.data()['type_product_params']
#     param_values = {}
#
#     for param_name, param_info in params.items():
#         if param_info['type'] == 'number' and not validate_number(message.text):
#             bot.send_message(message.chat.id, f"Значение параметра '{param_name}' должно быть числом.")
#             return
#
#         elif param_info['type'] == 'enum':
#             keyboard = create_enum_keyboard(param_info['options'])
#             bot.send_message(message.chat.id, f"Выберите значение для '{param_name}':", reply_markup=keyboard)
#             # После выбора сохраните выбранное значение
#
#         else:
#             param_values[param_name] = message.text  # Строковые значения сохраняются как есть
#
#     # После валидации и сохранения значений
#     state.add_data(inherited_params=param_values)
#     bot.send_message(message.chat.id, "Параметры успешно установлены.")
#
#
# # Шаг 1: Начало создания параметров продукта
# @bot.message_handler(state=AdminStates.enter_inherited_param_values)
# def enter_inherited_param_values(message: types.Message, state: StateContext):
#     params = state.data()['type_product_params']
#     param_values = {}
#
#     for param_name, param_info in params.items():
#         if param_info['type'] == 'number' and not validate_number(message.text):
#             bot.send_message(message.chat.id, f"Значение параметра '{param_name}' должно быть числом.")
#             return
#
#         elif param_info['type'] == 'enum':
#             keyboard = create_enum_keyboard(param_info['options'])
#             bot.send_message(message.chat.id, f"Выберите значение для '{param_name}':", reply_markup=keyboard)
#             # После выбора сохраните выбранное значение
#
#         else:
#             param_values[param_name] = message.text  # Строковые значения сохраняются как есть
#
#     # После валидации и сохранения значений
#     state.add_data(inherited_params=param_values)
#     bot.send_message(message.chat.id, "Параметры успешно установлены.")

@bot.message_handler(state=AdminStates.enter_product_name)
def enter_product_name(message: types.Message, state: StateContext):
    # Сохраняем название продукта
    product_name = message.text.strip()
    state.add_data(product_name=product_name)

    # Получаем параметры типа продукта
    with state.data() as data:
        selected_type_info = data.get('selected_type_product_info')
        print(selected_type_info)
        print('selected_type_info')
        type_product_params = selected_type_info.get('params', {})
    print(selected_type_info)
    print('selected_type_info')

    # Проверка на наличие параметров в типе продукта
    if not type_product_params:
        # Уведомляем о необходимости ввести параметры для свойств продукта или пропустить шаг
        skip_markup = types.InlineKeyboardMarkup()
        skip_markup.add(types.InlineKeyboardButton("Пропустить", callback_data="skip_product_specific_params"))

        bot.send_message(message.chat.id,
                         "Параметры типа продукта отсутствуют. Добавьте параметры для свойств продукта или пропустите шаг.\n\n"
                         "На текущий момент поддерживаются следующие типы данных:\n"
                         "- Строка: просто название\n"
                         "- Перечисление: Название(параметр1, параметр2,...)\n"
                         "- Число: +Название+\n\n"
                         "Каждый параметр начинается с новой строки", reply_markup=skip_markup)

        state.set(AdminStates.enter_product_specific_params)
        return

    # Формируем сообщение с параметрами, которые необходимо заполнить
    param_list = "\n".join(
        [f"{param_name} ({param_info['type']})" for param_name, param_info in type_product_params.items()])
    message_text = f"Введите значения следующих параметров для продукта '{product_name}':\n\n{param_list}\n\nЗначения указывайте через запятую в том же порядке."
    bot.send_message(message.chat.id, message_text)

    # Переходим к следующему состоянию
    state.set(AdminStates.enter_product_params)


@bot.message_handler(state=AdminStates.enter_product_params)
def enter_product_params(message: types.Message, state: StateContext):
    # Получаем значения, введенные пользователем
    param_values = message.text.split(',')

    # Получаем параметры из состояния
    with state.data() as data:
        selected_type_info = data.get('selected_type_product_info')
        type_product_params = selected_type_info.get('params', {})
        product_name = data.get('product_name')

    # Проверка на соответствие количества введенных значений количеству параметров
    # if len(param_values) != len(type_product_params):
    #     bot.send_message(message.chat.id,
    #                      "Количество введенных значений не совпадает с количеством параметров. Попробуйте снова.")
    #     return

    # Валидация и сохранение значений параметров
    validated_params = {}
    for idx, (param_name, param_info) in enumerate(type_product_params.items()):
        param_value = param_values[idx].strip()

        # Валидация на основе типа параметра
        if param_info['type'] == 'number':
            # Проверка, что значение является числом
            if not validate_number(param_value):
                bot.send_message(message.chat.id, f"Значение параметра '{param_name}' должно быть числом.")
                return
            validated_params[param_name] = float(param_value)
        elif param_info['type'] == 'enum':
            # Проверка, что значение входит в допустимые перечисления
            if param_value not in param_info['options']:
                options_list = ', '.join(param_info['options'])
                bot.send_message(message.chat.id,
                                 f"Значение параметра '{param_name}' должно быть одним из следующих: {options_list}")
                return
            validated_params[param_name] = param_value
        else:
            # Строковое значение
            validated_params[param_name] = param_value

    # Сохраняем параметры продукта в состоянии
    state.add_data(product_params=validated_params)

    # Уведомление о необходимости ввести параметры для свойств продукта или пропустить шаг
    skip_markup = types.InlineKeyboardMarkup()
    skip_markup.add(types.InlineKeyboardButton("Пропустить", callback_data="skip_product_specific_params"))

    bot.send_message(message.chat.id,
                     "Добавьте параметры для свойств продукта\nНа текущий момент поддерживаются следующие типы данных:\n"
        "- Строка: просто название\n"
        "- Перечисление: Название(параметр1, параметр2,...)\n"
        "- Число: +Название+\n\n"
        "Каждый параметр начинается с новой строки",
                     reply_markup=skip_markup)

    # Переход к следующему состоянию для ввода параметров свойств продукта
    state.set(AdminStates.enter_product_specific_params)


@bot.message_handler(state=AdminStates.enter_product_specific_params)
def enter_product_specific_params(message: types.Message, state: StateContext):
    raw_params = message.text.split('\n')
    specific_params = {}

    # Парсинг параметров и определение их типа, как и для типа продукта
    for param in raw_params:
        param = param.strip()
        param_name = param.replace('+', '').split('(')[0].strip()
        param_type = identify_param_type(param)

        specific_params[param_name] = {
            'type': param_type,
            'options': parse_enum_options(param) if param_type == 'enum' else None
        }

    # Получаем данные из состояния
    with state.data() as data:
        product_name = data.get('product_name')
        product_params = data.get('product_params',{})
        selected_type_info = data.get('selected_type_product_info')
        type_product_id = selected_type_info['id']

    # Создаем продукт, добавляем основной набор параметров
    product_id = create_product(product_name, type_product_id, product_params, specific_params)
    formatted_product_values = format_type_product_values(product_params)
    formatted_specific_params = format_product_params(specific_params)
    # Создаем параметры для свойств продукта
    # create_product_param(product_id, specific_params)
    message_text = (
        f"Продукт '{product_name}' и его свойства успешно добавлены.\n\n"
        f"Значения параметров типа продукта:\n{formatted_product_values}\n"
        f"Параметры свойств продукта:\n{formatted_specific_params}"
    )
    # Сообщение о завершении
    bot.send_message(message.chat.id, message_text)
    # Завершаем создание и очищаем состояние
    state.delete()

@bot.callback_query_handler(func=lambda call: call.data == "skip_product_specific_params")
def skip_product_specific_params(call: types.CallbackQuery, state: StateContext):
    with state.data() as data:
        product_name = data.get('product_name')
        product_params = data.get('product_params',{})
        selected_type_info = data.get('selected_type_product_info')
        type_product_id = selected_type_info['id']

    # Создаем продукт без дополнительных параметров
    product_id = create_product(product_name, type_product_id, product_params)

    # Форматируем значения параметров типа продукта для отображения
    formatted_product_values = format_type_product_values(product_params)

    # Сообщение о завершении
    message_text = (
        f"Продукт '{product_name}' успешно создан без дополнительных параметров.\n\n"
        f"Значения параметров типа продукта:\n{formatted_product_values}"
    )
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=message_text)

    # Завершаем создание
    state.delete()
def show_crud_keyboard(message, command):
    # Создаем инлайн-клавиатуру CRUD
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("Добавить", callback_data=f"{command}-add"),
        types.InlineKeyboardButton("Посмотреть", callback_data=f"{command}-view"),
        types.InlineKeyboardButton("Редактировать", callback_data=f"{command}-edit"),
        types.InlineKeyboardButton("Удалить", callback_data=f"{command}-delete")
    )
    bot.send_message(message.chat.id, f"Выберите действие:", reply_markup=markup)


def format_product_params(params):
    formatted_params = ""
    for param_name, param_info in params.items():
        param_type = param_info.get('type')
        options = param_info.get('options')
        if param_type == "enum" and options:
            formatted_params += f"{param_name} - Перечисление ({', '.join(options)})\n"
        elif param_type == "number":
            formatted_params += f"{param_name} - Число\n"
        else:
            formatted_params += f"{param_name} - Строка\n"
    return formatted_params


def format_product_values(params, values):
    if not params:
        return "Не указаны"

    formatted_values = ""
    for param_name, param_info in params.items():
        # Получаем значение из values по ключу параметра
        value = values.get(param_name, "Не указано") if values else "Не указано"
        formatted_values += f"{param_name}: {value}\n"
    return formatted_values


def format_type_product_values(values):
    if not values:
        return "Не указаны"
    formatted_values = ""
    for param_name, value in values.items():
        formatted_values += f"{param_name}: {value}\n"
    return formatted_values


@bot.message_handler(commands=['reports'])
def report_selection(message: types.Message, state: StateContext):
    type_products = get_all_type_products()

    if not type_products:
        bot.send_message(message.chat.id, "Нет доступных типов продуктов.")
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    for type_product in type_products:
        markup.add(types.InlineKeyboardButton(
            type_product['name'],
            callback_data=f"reports_{type_product['id']}"
        ))
    state.set(ReportStates.report_type_id)
    bot.send_message(message.chat.id, "Выберите тип продукта для отчета:", reply_markup=markup)



@bot.callback_query_handler(func=lambda call: call.data.startswith('reports_'))
def choose_type_id(call: types.CallbackQuery, state: StateContext):
    type_id = call.data.split('_')[1]
    user_info = get_user_by_username(call.from_user.username, state)
    if 'Admin' not in user_info['roles']:
        bot.reply_to(call.message, "У вас нет доступа к этой команде.")
        return
    state.add_data(report_type_id=type_id)

    # Формируем клавиатуру для выбора типа отчета
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("Отчет по продажам", callback_data="report_sales"),
        types.InlineKeyboardButton("Отчет по остаткам", callback_data="report_stock")
    )

    bot.send_message(call.message.chat.id, "Выберите тип отчета:", reply_markup=markup)
    state.set(ReportStates.report_type)

@bot.callback_query_handler(func=lambda call: call.data in ['report_sales', 'report_stock'], state=ReportStates.report_type)
def handle_report_type_selection(call: types.CallbackQuery, state: StateContext):
    report_type = call.data

    state.add_data(report_type=report_type)

    if report_type == 'report_stock':
        with state.data() as data:
            type_id = data.get('report_type_id')
        report_path = generate_stock_report(type_id)
        bot.send_document(call.message.chat.id, open(report_path, 'rb'))
        return

    # Запрашиваем период для формирования отчета
    bot.send_message(call.message.chat.id, "Введите период для отчета (например, 2023-01-01 2023-12-31):")
    state.set(ReportStates.report_period)

@bot.message_handler(state=ReportStates.report_period)
def generate_report(message: types.Message, state: StateContext):
    # Получаем тип отчета и период из состояния
    with state.data() as data:
        report_type = data['report_type']
        report_period = message.text
        type_id = data.get('report_type_id')

    # Разбираем даты начала и конца периода
    try:
        start_date, end_date = [d.strip() for d in report_period.split(' ')]
    except ValueError:
        bot.send_message(message.chat.id, "Некорректный формат периода. Используйте формат: YYYY-MM-DD - YYYY-MM-DD")
        return

    if report_type == 'report_sales':
        report_path = generate_sales_report(start_date, end_date,type_id)
        bot.send_document(message.chat.id, open(report_path, 'rb'))
    elif report_type == 'report_stock':
        report_path = generate_stock_report(type_id)
        bot.send_document(message.chat.id, open(report_path, 'rb'))

    state.delete()
