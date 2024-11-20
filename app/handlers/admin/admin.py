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

from database import update_product_prices, get_product_params, update_product_stock

from handlers.admin.genereal_report import generate_detailed_sales_report

from database import soft_delete_product_param, soft_delete_product, soft_delete_type_product

from database import get_all_suppliers

from utils import is_valid_command


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
    if not is_valid_command(message.text, state):
        return
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
    if not is_valid_command(message.text, state):
        return
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
    if not is_valid_command(message.text, state):
        return
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


@bot.callback_query_handler(func=lambda call: call.data.endswith('-view') and (call.data.startswith('type_product') or call.data.startswith('product') or call.data.startswith('product_param')  ))
def handle_view_command(call: types.CallbackQuery, state: StateContext):
    command = call.data.split('-')[0]

    if command == "type_product":
        # Получаем список типов продуктов из базы данных
        type_products = get_all_type_products()
        if not type_products:
            bot.send_message(call.message.chat.id, "Типы продуктов не найдены.")
            return
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
            type_product_id = data.get('selected_type_product_info')['id']
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
    if not is_valid_command(message.text, state):
        return
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
    if not is_valid_command(message.text, state):
        return
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


# @bot.callback_query_handler(func=lambda call: call.data in ['is_main_product_yes', 'is_main_product_no'])
# def handle_is_main_product(call,state):
#     is_main_product = True if call.data == 'is_main_product_yes' else False
#     # Сохраняем значение в состоянии пользователя
#     state.add_data(is_main_product=is_main_product)
#     # Получаем параметры типа продукта
#     message = call.message
#     with state.data() as data:
#         product_name = data.get("product_name")
#         selected_type_info = data.get('selected_type_product_info')
#         type_product_params = selected_type_info.get('params', {})
#         sale_price = data.get('sale_price', 0)
#         avito_delivery_price = data.get('avito_delivery_price', 0)
#
#
#     print('selected_type_info')
#
#     # Проверка на наличие параметров в типе продукта
#     if not type_product_params:
#         # Если параметров нет, создаём продукт без параметров
#         skip_markup = types.InlineKeyboardMarkup()
#         skip_markup.add(types.InlineKeyboardButton("Пропустить", callback_data="skip_product_specific_params"))
#
#         bot.send_message(
#             message.chat.id,
#             "Параметры типа продукта отсутствуют. Добавьте параметры для свойств продукта или пропустите шаг.\n\n"
#             "На текущий момент поддерживаются следующие типы данных:\n"
#             "- Строка: просто название\n"
#             "- Перечисление: Название(параметр1, параметр2,...)\n"
#             "- Число: +Название+\n\n"
#             "Каждый параметр начинается с новой строки",
#             reply_markup=skip_markup
#         )
#
#         state.set(AdminStates.enter_product_specific_params)
#         return
#
#         # Формируем сообщение с параметрами, которые необходимо заполнить
#     param_list = "\n".join(
#         [f"{param_name} ({param_info['type']})" for param_name, param_info in type_product_params.items()])
#     message_text = f"Введите значения следующих параметров для продукта '{product_name}':\n\n{param_list}\n\nЗначения указывайте через запятую в том же порядке."
#     bot.send_message(message.chat.id, message_text)
#
#     # Переходим к следующему состоянию
#     state.set(AdminStates.enter_product_params)
@bot.callback_query_handler(func=lambda call: call.data in ['is_main_product_yes', 'is_main_product_no'])
def handle_is_main_product(call, state):
    is_main_product = True if call.data == 'is_main_product_yes' else False
    # Сохраняем значение в состоянии пользователя
    state.add_data(is_main_product=is_main_product)

    # Получаем список поставщиков
    suppliers = get_all_suppliers()
    if not suppliers:
        bot.send_message(call.message.chat.id, "Ошибка: нет доступных поставщиков в системе.")
        return

    # Создаем клавиатуру для выбора поставщика
    markup = types.InlineKeyboardMarkup(row_width=1)
    for supplier in suppliers:
        markup.add(types.InlineKeyboardButton(
            f"{supplier[1]} ({supplier[2]})",  # name (country)
            callback_data=f"supplier_{supplier[0]}"
        ))

    bot.edit_message_text(
        "Выберите поставщика продукта:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )
    state.set(AdminStates.select_supplier)


@bot.callback_query_handler(func=lambda call: call.data.startswith('supplier_'), state=AdminStates.select_supplier)
def handle_supplier_selection(call: types.CallbackQuery, state: StateContext):
    supplier_id = int(call.data.split('_')[1])
    state.add_data(supplier_id=supplier_id)

    # Получаем параметры типа продукта
    message = call.message
    with state.data() as data:
        product_name = data.get("product_name")
        selected_type_info = data.get('selected_type_product_info')
        type_product_params = selected_type_info.get('params', {})

    # Проверка на наличие параметров в типе продукта
    if not type_product_params:
        # Если параметров нет, создаём продукт без параметров
        skip_markup = types.InlineKeyboardMarkup()
        skip_markup.add(types.InlineKeyboardButton("Пропустить", callback_data="skip_product_specific_params"))

        bot.send_message(
            message.chat.id,
            "Параметры типа продукта отсутствуют. Добавьте параметры для свойств продукта или пропустите шаг.\n\n"
            "На текущий момент поддерживаются следующие типы данных:\n"
            "- Строка: просто название\n"
            "- Перечисление: Название(параметр1, параметр2,...)\n"
            "- Число: +Название+\n\n"
            "Каждый параметр начинается с новой строки",
            reply_markup=skip_markup
        )
        state.set(AdminStates.enter_product_specific_params)
        return
    param_list = "\n".join(
        [f"{param_name} ({param_info['type']})" for param_name, param_info in type_product_params.items()])
    message_text = f"Введите значения следующих параметров для продукта '{product_name}':\n\n{param_list}\n\nЗначения указывайте через запятую в том же порядке."
    bot.edit_message_text(message_text, call.message.chat.id, call.message.message_id)

    # Переходим к следующему состоянию
    state.set(AdminStates.enter_product_params)

@bot.message_handler(state=AdminStates.enter_product_name)
def enter_product_name(message: types.Message, state: StateContext):
    # Сохраняем название продукта
    product_name = message.text.strip()
    state.add_data(product_name=product_name)

    # Запрашиваем цену продажи
    bot.send_message(message.chat.id, "Введите цену продажи:")
    state.set(AdminStates.enter_sale_price)


@bot.message_handler(state=AdminStates.enter_sale_price)
def enter_sale_price(message: types.Message, state: StateContext):
    if not is_valid_command(message.text, state):
        return
    try:
        sale_price = float(message.text.strip())
        if sale_price < 0:
            raise ValueError("Price must be positive")

        state.add_data(sale_price=sale_price)

        # Запрашиваем цену доставки Авито
        bot.send_message(message.chat.id, "Введите цену доставки Авито:")
        state.set(AdminStates.enter_avito_price)

    except ValueError:
        bot.send_message(message.chat.id, "Введите корректную цену (положительное число)")


@bot.message_handler(state=AdminStates.enter_avito_price)
def enter_avito_price(message: types.Message, state: StateContext):
    if not is_valid_command(message.text, state):
        return
    try:
        avito_price = float(message.text.strip())
        if avito_price < 0:
            raise ValueError("Price must be positive")

        state.add_data(avito_delivery_price=avito_price)

        # Переходим к следующему шагу - является ли продукт основным
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(types.InlineKeyboardButton("Да", callback_data="is_main_product_yes"),
                   types.InlineKeyboardButton("Нет", callback_data="is_main_product_no"))
        bot.send_message(message.chat.id, "Является ли продукт основным в сезоне?", reply_markup=markup)

    except ValueError:
        bot.send_message(message.chat.id, "Введите корректную цену (положительное число)")


@bot.message_handler(state=AdminStates.enter_product_params)
def enter_product_params(message: types.Message, state: StateContext):
    if not is_valid_command(message.text, state):
        return
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


def ask_is_main_product(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("Да", callback_data="is_main_product_yes"),
               types.InlineKeyboardButton("Нет", callback_data="is_main_product_no"))
    bot.send_message(chat_id, "Является ли продукт основным в сезоне?", reply_markup=markup)




@bot.message_handler(state=AdminStates.enter_product_specific_params)
def enter_product_specific_params(message: types.Message, state: StateContext):
    if not is_valid_command(message.text, state):
        return
    raw_params = message.text.split('\n')
    specific_params = {}

    # Парсинг параметров и определение их типа
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
        product_params = data.get('product_params', {})
        selected_type_info = data.get('selected_type_product_info')
        type_product_id = selected_type_info['id']
        is_main_product = data.get('is_main_product')
        supplier_id = data.get('supplier_id')
        sale_price = data.get('sale_price', 0)
        avito_delivery_price = data.get('avito_delivery_price', 0)

    # Создаем продукт с указанием поставщика
    product_id = create_product(
        name=product_name,
        type_id=type_product_id,
        supplier_id=supplier_id,  # Добавляем поставщика
        is_main_product=is_main_product,
        product_values=product_params,
        param_parameters=specific_params,
        sale_price=sale_price,
        avito_delivery_price=avito_delivery_price
    )

    formatted_product_values = format_type_product_values(product_params)
    formatted_specific_params = format_product_params(specific_params)

    message_text = (
        f"Продукт '{product_name}' и его свойства успешно добавлены.\n\n"
        f"Значения параметров типа продукта:\n{formatted_product_values}\n"
        f"Параметры свойств продукта:\n{formatted_specific_params}"
    )
    bot.send_message(message.chat.id, message_text)
    state.delete()

@bot.callback_query_handler(func=lambda call: call.data == "skip_product_specific_params")
def skip_product_specific_params(call: types.CallbackQuery, state: StateContext):

    with state.data() as data:
        product_name = data.get('product_name')
        product_params = data.get('product_params', {})
        selected_type_info = data.get('selected_type_product_info')
        type_product_id = selected_type_info['id']
        is_main_product = data.get('is_main_product')
        supplier_id = data.get('supplier_id')
        sale_price = data.get('sale_price', 0)
        avito_delivery_price = data.get('avito_delivery_price', 0)

    # Создаем продукт без дополнительных параметров, но с указанием поставщика
    product_id = create_product(
        name=product_name,
        type_id=type_product_id,
        supplier_id=supplier_id,
        is_main_product=is_main_product,
        product_values=product_params,
        sale_price=sale_price,
        avito_delivery_price=avito_delivery_price
    )

    formatted_product_values = format_type_product_values(product_params)

    message_text = (
        f"Продукт '{product_name}' успешно создан без дополнительных параметров.\n\n"
        f"Значения параметров типа продукта:\n{formatted_product_values}"
    )
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=message_text)

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
    bot.send_message(call.message.chat.id, "Введите период для отчета в формате Год-Месяц-День \nНапример, 2023-01-01 2023-12-31:")
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
        # report_path = generate_sales_report(start_date, end_date,type_id)
        report_path = generate_detailed_sales_report(start_date, end_date)
        bot.send_document(message.chat.id, open(report_path, 'rb'))
    elif report_type == 'report_stock':
        report_path = generate_stock_report(type_id)
        bot.send_document(message.chat.id, open(report_path, 'rb'))

    state.delete()


@bot.message_handler(commands=['manage_stock'])
def handle_manage_stock(message: types.Message, state: StateContext):
    """Команда для управления стоком и ценами"""
    type_products = get_all_type_products()

    if not type_products:
        bot.send_message(message.chat.id, "Нет доступных типов продуктов.")
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    for type_product in type_products:
        markup.add(types.InlineKeyboardButton(
            type_product['name'],
            callback_data=f"stock_type_{type_product['id']}"
        ))
    state.set(AdminStates.manage_stock_type)
    bot.send_message(message.chat.id, "Выберите тип продукта:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('stock_type_'), state=AdminStates.manage_stock_type)
def handle_stock_type_selection(call: types.CallbackQuery, state: StateContext):
    type_id = int(call.data.split('_')[2])

    # Получаем все продукты данного типа
    products = get_all_products(type_id)
    if not products:
        bot.send_message(call.message.chat.id, "Нет продуктов данного типа.")
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    for product in products:
        markup.add(types.InlineKeyboardButton(
            product['name'],
            callback_data=f"stock_product_{product['id']}"
        ))

    state.add_data(selected_type_id=type_id)
    state.set(AdminStates.manage_stock_product)

    bot.edit_message_text(
        "Выберите продукт:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('stock_product_'),
                            state=AdminStates.manage_stock_product)
def handle_stock_product_selection(call: types.CallbackQuery, state: StateContext):
    product_id = int(call.data.split('_')[2])

    # Получаем параметры продукта
    params = get_product_params(product_id)
    if not params:
        bot.send_message(call.message.chat.id, "У продукта нет параметров.")
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    for param in params:
        markup.add(types.InlineKeyboardButton(
            f"{param[1]} (Остаток: {param[2]})",
            callback_data=f"stock_param_{param[0]}_{param[2]}"
        ))

    state.add_data(selected_product_id=product_id)
    state.set(AdminStates.manage_stock_param)

    # Добавляем кнопку для управления ценами
    markup.add(types.InlineKeyboardButton(
        "💰 Управление ценами",
        callback_data=f"manage_prices_{product_id}"
    ))

    bot.edit_message_text(
        "Выберите параметр продукта или управление ценами:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('stock_param_'),
                            state=AdminStates.manage_stock_param)
def handle_stock_param_selection(call: types.CallbackQuery, state: StateContext):
    param_id = int(call.data.split('_')[2])
    prev_stock=call.data.split('_')[3]
    state.add_data(selected_param_id=param_id)

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("➕ Добавить", callback_data=f"stock_add_{prev_stock}"),
        types.InlineKeyboardButton("➖ Убавить", callback_data=f"stock_subtract_{prev_stock}")
    )

    bot.edit_message_text(
        "Выберите действие:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

    state.set(AdminStates.manage_stock_action)


@bot.callback_query_handler(func=lambda call: call.data.startswith('stock_'), state=AdminStates.manage_stock_action)
def handle_stock_action(call: types.CallbackQuery, state: StateContext):
    action = call.data.split('_')[1]
    prev_stock = call.data.split('_')[2]
    state.add_data(stock_action=action)

    bot.edit_message_text(
        f"Введите количество:\nПредыдущее кол-во: {prev_stock}",
        call.message.chat.id,
        call.message.message_id
    )

    state.set(AdminStates.manage_stock_quantity)


@bot.message_handler(state=AdminStates.manage_stock_quantity)
def handle_stock_quantity(message: types.Message, state: StateContext):
    try:
        quantity = int(message.text)
        if quantity < 0:
            raise ValueError("Quantity must be positive")

        with state.data() as data:
            param_id = data['selected_param_id']
            action = data['stock_action']

        # Обновляем сток
        success = update_product_stock(param_id, quantity, action == 'add')

        if success:
            bot.send_message(
                message.chat.id,
                f"✅ Сток успешно {'увеличен' if action == 'add' else 'уменьшен'} на {quantity}"
            )
        else:
            bot.send_message(
                message.chat.id,
                "❌ Ошибка при обновлении стока. Возможно, недостаточно товара для списания."
            )

        state.delete()

    except ValueError:
        bot.reply_to(message, "Введите положительное целое число.")


@bot.callback_query_handler(func=lambda call: call.data.startswith('manage_prices_'))
def handle_manage_prices(call: types.CallbackQuery, state: StateContext):
    product_id = int(call.data.split('_')[2])
    state.add_data(selected_product_id=product_id)

    product_info = get_product_info_with_params(product_id)
    current_prices = (
        f"Текущие цены:\n"
        f"Продажа: {product_info.get('sale_price', '0')} руб.\n"
        f"Авито доставка: {product_info.get('avito_delivery_price', '0')} руб.\n\n"
        f"Введите новые цены через запятую (продажа, авито):"
    )

    bot.edit_message_text(
        current_prices,
        call.message.chat.id,
        call.message.message_id
    )

    state.set(AdminStates.manage_prices)


@bot.message_handler(state=AdminStates.manage_prices)
def handle_prices_update(message: types.Message, state: StateContext):
    try:
        # Парсим цены из сообщения
        prices = [float(price.strip()) for price in message.text.split(',')]
        if len(prices) != 2:
            raise ValueError("Need exactly two prices")

        sale_price, avito_price = prices

        with state.data() as data:
            product_id = data['selected_product_id']

        # Обновляем цены
        success = update_product_prices(product_id, sale_price, avito_price)

        if success:
            bot.reply_to(
                message,
                f"✅ Цены успешно обновлены:\n"
                f"Продажа: {sale_price} руб.\n"
                f"Авито доставка: {avito_price} руб."
            )
        else:
            bot.reply_to(message, "❌ Ошибка при обновлении цен.")

        state.delete()

    except ValueError:
        bot.reply_to(
            message,
            "Неверный формат. Введите два числа через запятую (например: 1000, 1500)"
        )


@bot.callback_query_handler(func=lambda call: call.data.endswith('-delete'))
def handle_delete_action(call: types.CallbackQuery, state: StateContext):
    command = call.data.split('-')[0]

    if command == 'type_product':
        # Показываем список доступных типов продуктов для удаления
        type_products = get_all_type_products()
        if not type_products:
            bot.answer_callback_query(call.id, "Нет доступных типов продуктов.")
            return

        markup = types.InlineKeyboardMarkup(row_width=1)
        for type_product in type_products:
            markup.add(types.InlineKeyboardButton(
                type_product['name'],
                callback_data=f"delete_type_{type_product['id']}"
            ))

        bot.edit_message_text(
            "Выберите тип продукта для удаления:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

    elif command == 'product':
        # Проверяем, выбран ли тип продукта
        with state.data() as data:
            selected_type_info = data.get('selected_type_product_info')

        if not selected_type_info:
            bot.answer_callback_query(call.id, "Сначала выберите тип продукта.")
            return

        products = get_all_products(selected_type_info['id'])
        if not products:
            bot.answer_callback_query(call.id, "Нет доступных продуктов.")
            return

        markup = types.InlineKeyboardMarkup(row_width=1)
        for product in products:
            markup.add(types.InlineKeyboardButton(
                product['name'],
                callback_data=f"delete_product_{product['id']}"
            ))

        bot.edit_message_text(
            "Выберите продукт для удаления:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

    elif command == 'product_param':
        with state.data() as data:
            product_id = data.get('selected_product_id')

        if not product_id:
            bot.answer_callback_query(call.id, "Сначала выберите продукт.")
            return

        params = get_all_product_params(product_id)
        if not params:
            bot.answer_callback_query(call.id, "Нет доступных параметров.")
            return

        markup = types.InlineKeyboardMarkup(row_width=1)
        for param in params:
            markup.add(types.InlineKeyboardButton(
                param['name'],
                callback_data=f"delete_param_{param['id']}"
            ))

        bot.edit_message_text(
            "Выберите параметр для удаления:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )


@bot.callback_query_handler(func=lambda call: call.data.startswith('delete_type_'))
def handle_type_deletion(call: types.CallbackQuery, state: StateContext):
    type_id = int(call.data.split('_')[2])

    # Запрашиваем подтверждение
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_delete_type_{type_id}"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_delete")
    )

    bot.edit_message_text(
        "⚠️ Вы уверены, что хотите удалить этот тип продукта?\n"
        "Это действие также скроет все связанные продукты.",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('delete_product_'))
def handle_product_deletion(call: types.CallbackQuery, state: StateContext):
    product_id = int(call.data.split('_')[2])

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_delete_product_{product_id}"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_delete")
    )

    bot.edit_message_text(
        "⚠️ Вы уверены, что хотите удалить этот продукт?\n"
        "Это действие также скроет все его параметры.",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('delete_param_'))
def handle_param_deletion(call: types.CallbackQuery, state: StateContext):
    param_id = int(call.data.split('_')[2])

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_delete_param_{param_id}"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_delete")
    )

    bot.edit_message_text(
        "⚠️ Вы уверены, что хотите удалить этот параметр продукта?",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_delete_'))
def handle_delete_confirmation(call: types.CallbackQuery, state: StateContext):
    _, _, entity, entity_id = call.data.split('_')
    entity_id = int(entity_id)
    success = False

    if entity == 'type':
        success = soft_delete_type_product(entity_id)
        message = "тип продукта"
    elif entity == 'product':
        success = soft_delete_product(entity_id)
        message = "продукт"
    elif entity == 'param':
        success = soft_delete_product_param(entity_id)
        message = "параметр продукта"

    # if success:
    bot.edit_message_text(
        f"✅ {message.capitalize()} успешно удален.",
        call.message.chat.id,
        call.message.message_id
    )
    # else:
    #     bot.edit_message_text(
    #         f"❌ Ошибка при удалении: {message} не найден.",
    #         call.message.chat.id,
    #         call.message.message_id
    #     )


@bot.callback_query_handler(func=lambda call: call.data == 'cancel_delete')
def handle_delete_cancellation(call: types.CallbackQuery, state: StateContext):
    bot.edit_message_text(
        "❌ Удаление отменено.",
        call.message.chat.id,
        call.message.message_id
    )
