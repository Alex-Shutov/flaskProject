from dataclasses import dataclass
from typing import Optional, Tuple, Dict, List
import requests
import json
from datetime import datetime
from shapely.geometry import Point, Polygon

from database import get_product_info_with_params



@dataclass
class DeliveryZone:
    """Класс для представления зоны доставки"""
    id: int
    name: str
    color: str
    base_price: float
    additional_item_price: float
    polygon: Optional[Polygon] = None

@dataclass
class DeliveryCost:
    """Класс для представления стоимости доставки"""
    base_price: float
    additional_items_price: float
    total_price: float
    zone_name: str
    items_count: int
    zone_id:int


@dataclass
class AddressComponents:
    """Класс для хранения компонентов адреса"""
    city: str
    street: str
    house: str
    apartment: Optional[str] = None


class DeliveryZoneManager:
    """Менеджер для работы с зонами доставки"""

    def __init__(self, db_connection, yandex_api_key: str):
        self.db_connection = db_connection
        self.api_key = yandex_api_key
        self.geocoding_url = "https://geocode-maps.yandex.ru/1.x/"

    def get_all_zones(self) -> List[DeliveryZone]:
        """Получает все зоны доставки из базы данных"""
        cursor = self.db_connection.cursor()
        query = """
            SELECT 
                id, name, color, base_price, additional_item_price,
                ST_AsGeoJSON(polygon)::json as polygon_geojson
            FROM delivery_zones
            WHERE polygon IS NOT NULL
            ORDER BY base_price ASC
        """
        cursor.execute(query)
        zones = []
        for row in cursor.fetchall():
            # row - это кортеж, преобразуем его в именованные поля
            id_, name, color, base_price, additional_item_price, polygon_geojson = row

            # Преобразуем GeoJSON полигон в объект Shapely
            if polygon_geojson:
                try:
                    # Получаем координаты из первого "кольца" полигона
                    coordinates = polygon_geojson['coordinates'][0]
                    polygon = Polygon(coordinates)
                except Exception as e:
                    print(f"Error creating polygon: {e}")
                    polygon = None
            else:
                polygon = None

            zones.append(DeliveryZone(
                id=id_,
                name=name,
                color=color,
                base_price=float(base_price),
                additional_item_price=float(additional_item_price),
                polygon=polygon
            ))
        return zones

    def get_zone_by_coordinates(self, lat: float, lon: float) -> Optional[DeliveryZone]:
        """Определяет зону доставки по координатам"""
        point = Point(lon, lat)
        print(point,'123')

        zones = self.get_all_zones()
        print(zones)
        # Проверяем каждую зону
        for zone in zones:
            if zone.polygon and zone.polygon.contains(point):
                return zone
        print('white')

        # Если точка не входит ни в одну зону, возвращаем белую зону
        cursor = self.db_connection.cursor()
        query = """
            SELECT id, name, color, base_price, additional_item_price
            FROM delivery_zones
            WHERE color = 'white'
            LIMIT 1
        """
        cursor.execute(query)
        white_zone = cursor.fetchone()
        print(white_zone)
        if white_zone:
            return DeliveryZone(
                id=white_zone[0],
                name=white_zone[1],
                color=white_zone[2],
                base_price=float(white_zone[3]),
                additional_item_price=float(white_zone[4]),
                polygon=None
            )
        return None

    def geocode_address(self, address: str) -> Optional[Tuple[float, float]]:
        """Геокодирует адрес, возвращает координаты"""
        params = {
            "apikey": self.api_key,
            "format": "json",
            "geocode": address,
            "lang": "ru_RU"
        }

        try:
            response = requests.get(
                self.geocoding_url,
                params=params,
                headers={
                    'User-Agent': 'Mozilla/5.0',
                    'Accept': 'application/json'
                }
            )

            if response.status_code == 403:
                print(f"Authorization Error - API Key: {self.api_key}")
                return None

            if response.status_code != 200:
                print(f"Error status code: {response.status_code}")
                return None

            data = response.json()

            if "response" not in data:
                print(f"Unexpected response structure: {data}")
                return None

            features = data["response"]["GeoObjectCollection"]["featureMember"]
            if not features:
                print("No results found")
                return None

            coords = features[0]["GeoObject"]["Point"]["pos"].split()
            return float(coords[1]), float(coords[0])  # lat, lon

        except Exception as e:
            print(f"Error in geocode_address: {str(e)}")
            return None

    def prepare_delivery_address(self, components: AddressComponents,
                                 coordinates: Tuple[float, float]) -> Optional[dict]:
        """Подготавливает данные о адресе доставки для сохранения в state"""
        try:
            zone = self.get_zone_by_coordinates(*coordinates)
            if not zone:
                return None

            # Создаем GeoJSON объект для координат
            coordinates_json = {
                "type": "Point",
                "coordinates": [coordinates[1], coordinates[0]]  # [lon, lat]
            }

            # Формируем полный адрес для отображения
            full_address = f"{components.city}, {components.street}, {components.house}"
            if components.apartment:
                full_address += f", кв. {components.apartment}"

            # Возвращаем словарь с данными для сохранения в state
            address_data = {
                'city': components.city,
                'street': components.street,
                'house': components.house,
                'apartment': components.apartment,
                'coordinates': coordinates_json,
                'zone_id': zone.id,
                'full_address': full_address,  # Добавляем полный адрес для удобства
                'zone_info': {
                    'name': zone.name,
                    'base_price': zone.base_price,
                    'additional_item_price': zone.additional_item_price
                }
            }

            return address_data

        except Exception as e:
            print(f"Error preparing delivery address: {e}")
            return None

    def save_delivery_address(self, order_id: int, components: AddressComponents,
                              coordinates: Tuple[float, float]) -> Optional[int]:
        """Сохраняет адрес доставки в базу данных"""
        try:
            print(order_id,components,coordinates)
            components = AddressComponents(**components)
            zone = self.get_zone_by_coordinates(*coordinates)
            zone_id = zone.id if zone else None

            # Создаем GeoJSON объект для координат
            coordinates_json = {
                "type": "Point",
                "coordinates": [coordinates[1], coordinates[0]]  # [lon, lat]
            }

            cursor = self.db_connection.cursor()
            query = """
                INSERT INTO delivery_addresses 
                    (order_id, city, street, house, apartment, coordinates, zone_id, created_at)
                VALUES 
                    (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                RETURNING id
            """
            values = (
                order_id,
                components.city,
                components.street,
                components.house,
                components.apartment,
                json.dumps(coordinates_json),  # Преобразуем словарь в JSON строку
                zone_id,
                datetime.now()
            )

            cursor.execute(query, values)
            self.db_connection.commit()
            print('Заказ с доставкой зарегистрирован')
            return cursor.fetchone()[0]
        except Exception as e:
            print(f"Error saving delivery address: {e}")
            self.db_connection.rollback()
            return None

class DeliveryCostCalculator:
    """Калькулятор стоимости доставки"""

    def __init__(self, db_connection):
        self.db_connection = db_connection

    def calculate_for_trip(self, orders_info: List[Dict], selected_items: Dict[str, List[int]]) -> Optional[
        DeliveryCost]:
        """
        Рассчитывает стоимость доставки для поездки

        Args:
            orders_info: список информации о заказах с типами и зонами
            selected_items: словарь {order_id: [order_item_id, ...]}
        """
        try:
            total_price = 0
            items_count = sum(len(items) for items in selected_items.values())
            delivery_zone = None

            # Находим зону доставки с максимальной стоимостью
            for order_info in orders_info:
                if order_info.get('type') == 'delivery' and order_info.get('zone'):
                    current_zone = order_info['zone']
                    if (not delivery_zone or
                            float(current_zone.base_price) > float(delivery_zone.base_price)):
                        delivery_zone = current_zone

            # Обработка заказов
            for order_info in orders_info:
                order_id = str(order_info['id'])

                if order_info.get('type') == 'delivery':
                    if delivery_zone:
                        # Расчет стоимости доставки для обычного заказа
                        base_price = float(delivery_zone.base_price)
                        additional_items = len(selected_items.get(order_id, [])) - 1
                        additional_price = max(0, additional_items * float(delivery_zone.additional_item_price))
                        total_price += base_price + additional_price


                else:  # Авито заказ

                    item_ids = [int(item.split('|')[1]) for item in selected_items.get(order_id, [])]
                    if not item_ids:
                        continue

                    # Получаем информацию о каждом товаре из order_items и связанного продукта

                    query = """

                                    SELECT 

                                        oi.product_values,

                                        p.avito_delivery_price

                                    FROM order_items oi

                                    JOIN products p ON oi.product_id = p.id

                                    WHERE oi.order_id = ANY(%s)

                                """

                    with self.db_connection.cursor() as cursor:

                        cursor.execute(query, (item_ids,))

                        items_info = cursor.fetchall()

                        for product_values, product_avito_price in items_info:

                            # Сначала проверяем цену в product_values

                            avito_price = 0

                            if product_values and isinstance(product_values, dict):

                                order_item_price = product_values.get('цена за доставку авито')

                                if order_item_price:

                                    try:

                                        avito_price = float(str(order_item_price).lower().strip())

                                    except ValueError:

                                        print(f"Invalid order item avito delivery price: {order_item_price}")

                            # Если цена не найдена в order_items, используем цену из продукта

                            if avito_price == 0 and product_avito_price:

                                try:

                                    avito_price = float(product_avito_price)

                                except ValueError:

                                    print(f"Invalid product avito delivery price: {product_avito_price}")

                            # Добавляем цену к общей сумме

                            total_price += avito_price

            # Определение зоны и имени зоны
            if not delivery_zone:
                # Если нет заказов с доставкой, используем первую зону
                from handlers.courier.trips import zone_manager
                default_zone = zone_manager.get_all_zones()[0]
                zone_id = default_zone.id
                zone_name = default_zone.name
                delivery_zone = default_zone
            else:
                from handlers.courier.trips import zone_manager
                zone_name = next(
                    (info.name for info in zone_manager.get_all_zones() if info.id == delivery_zone.id),
                    'Неизвестная зона'
                )

            return DeliveryCost(
                base_price=float(delivery_zone.base_price if delivery_zone else 0),
                additional_items_price=total_price - float(delivery_zone.base_price if delivery_zone else 0),
                total_price=total_price,
                zone_name=zone_name,
                zone_id=delivery_zone.id,
                items_count=items_count
            )

        except Exception as e:
            print(f"Error calculating delivery cost: {e}")
            return None

class CourierTripManager:
    """Менеджер для работы с поездками курьеров"""

    def __init__(self, db_connection):
        self.db_connection = db_connection

    def get_courier_active_trips(self, courier_id: int) -> List[Dict]:
        """
        Получает активные поездки курьера

        Args:
            courier_id: ID курьера
        Returns:
            List[Dict]: Список активных поездок
        """
        cursor = self.db_connection.cursor()
        try:
            query = """
                SELECT 
                    ct.id,
                    ct.status,
                    ct.zone_id,
                    ct.total_price,
                    ct.created_at,
                    ct.completed_at,
                    COUNT(DISTINCT CASE WHEN ti.status = 'pending' THEN ti.id END) as pending_items,
                    COUNT(DISTINCT CASE WHEN ti.status = 'delivered' THEN ti.id END) as delivered_items,
                    SUM(CASE 
                        WHEN o.order_type = 'avito' THEN 
                            (SELECT COUNT(DISTINCT tracking_number) 
                             FROM avito_photos 
                             WHERE order_id = o.id)
                        ELSE 1
                    END) as total_items,
                    ARRAY_AGG(DISTINCT o.order_type) as order_types
                FROM courier_trips ct
                LEFT JOIN trip_items ti ON ct.id = ti.trip_id
                LEFT JOIN order_items oi ON ti.order_item_id = oi.id
                LEFT JOIN orders o ON oi.order_id = o.id
                WHERE ct.courier_id = %s
                AND ct.status IN ('created', 'in_progress')
                GROUP BY ct.id, ct.status, ct.zone_id, ct.total_price, ct.created_at, ct.completed_at
            """
            cursor.execute(query, (courier_id,))
            trips = cursor.fetchall()

            formatted_trips = []
            for trip in trips:
                formatted_trip = {
                    'id': trip[0],
                    'status': trip[1],
                    'zone_id': trip[2],
                    'total_price': trip[3],
                    'created_at': trip[4],
                    'completed_at': trip[5],
                    'pending_items': trip[6],
                    'delivered_items': trip[7],
                    'total_items': trip[8],
                    'order_types': trip[9],
                    'has_avito': 'avito' in trip[9] if trip[9] else False
                }
                formatted_trips.append(formatted_trip)

            return formatted_trips

        except Exception as e:
            print(f"Error getting courier active trips: {e}")
            return []
        finally:
            cursor.close()

    def create_trip(self, courier_id: int, zone_id: int = None, total_price: float = 0) -> Optional[Dict]:
        """
        Создает новую поездку

        Args:
            courier_id: ID курьера
            zone_id: ID зоны доставки (опционально)
            total_price: Общая стоимость доставки (опционально)
        Returns:
            Optional[Dict]: Информация о созданной поездке или None в случае ошибки
        """
        cursor = self.db_connection.cursor()
        try:
            if zone_id is None:
                # Для поездок только с Авито заказами
                query = """
                    INSERT INTO courier_trips (courier_id, status, total_price, created_at)
                    VALUES (%s, 'created', %s, NOW())
                    RETURNING id
                """
                cursor.execute(query, (courier_id, total_price))
            else:
                # Для поездок с заказами доставки
                query = """
                    INSERT INTO courier_trips (courier_id, zone_id, status, total_price, created_at)
                    VALUES (%s, %s, 'created', %s, NOW())
                    RETURNING id
                """
                cursor.execute(query, (courier_id, zone_id, total_price))

            trip_id = cursor.fetchone()[0]
            self.db_connection.commit()
            return {'id': trip_id}

        except Exception as e:
            print(f"Error creating trip: {e}")
            self.db_connection.rollback()
            return None
        finally:
            cursor.close()

    def add_item_to_trip(self, trip_id: int, order_id: int, item_key: str) -> bool:
        """
        Добавляет товар в поездку

        Args:
            trip_id: ID поездки
            order_id: ID заказа
            item_key: строка с идентификатором товара
        """
        try:
            cursor = self.db_connection.cursor()
            # Получаем order_item_id из базы данных по product_id и param_id
            order_item_id,_,_ = item_key.split('|')

            # query = """
            #     SELECT id
            #     FROM order_items
            #     WHERE order_id = %s AND product_id = %s AND product_param_id = %s
            #     LIMIT 1
            # """
            # cursor.execute(query, (order_id, product_id, param_id))
            # result = cursor.fetchone()
            #
            # if not result:
            #     print(f"Order item not found for order {order_id}, product {product_id}, param {param_id}")
            #     return False
            #
            # order_item_id = result[0]

            # Добавляем запись в trip_items
            insert_query = """
                INSERT INTO trip_items (trip_id, order_item_id, status, created_at)
                VALUES (%s, %s, %s, %s)
            """
            cursor.execute(insert_query, (trip_id, order_item_id, 'pending', datetime.now()))
            self.db_connection.commit()
            return True

        except Exception as e:
            print(f"Error adding item to trip: {e}")
            self.db_connection.rollback()
            return False

    def get_items_for_order_in_ride(self, order_id,status='ready_to_delivery'):
        """
        Получает все товары заказа в статусе READY_TO_DELIVERY.

        Args:
            order_id (int): ID заказа

        Returns:
            list: Список словарей с информацией о товарах:
                - id: ID записи order_items
                - product_id: ID продукта
                - product_param_id: ID параметра продукта
                - product_name: Название продукта
                - param_title: Название параметра
                - status: Статус товара
                - trip_item_id: ID записи в trip_items (если есть)
                - trip_status: Статус в trip_items (если есть)
        """
        cursor = self.db_connection.cursor()
        query = """
            SELECT 
                oi.id,
                oi.product_id,
                oi.product_param_id,
                oi.product_name,
                oi.product_param_title as param_title,
                oi.status,
                ti.id as trip_item_id,
                ti.status as trip_status
            FROM order_items oi
            LEFT JOIN trip_items ti ON ti.order_item_id = oi.id
            WHERE oi.order_id = %s 
            AND oi.status = %s
        """
        cursor.execute(query, (order_id,status))

        items = []
        for row in cursor.fetchall():
            items.append({
                'id': row[0],
                'product_id': row[1],
                'product_param_id': row[2],
                'product_name': row[3],
                'param_title': row[4],
                'status': row[5],
                'trip_item_id': row[6],
                'trip_status': row[7]
            })

        return items

    def get_trip_items_for_order(
            self,
            order_id: int,
            trip_status=None,
            order_status=None,
            order_item_status=None,
            courier_trip_status=None
    ) -> List[Dict]:
        """
        Получает товары заказа в текущей поездке с опциональной фильтрацией по статусам

        Args:
            order_id: ID заказа
            trip_status: Статус(ы) поездки (строка или список)
            order_status: Статус(ы) заказа (строка или список)
            order_item_status: Статус(ы) товаров (строка или список)
            courier_trip_status: Статус(ы) courier_trips (строка или список)
        Returns:
            List[Dict]: Список товаров с их информацией
        """
        cursor = self.db_connection.cursor()
        try:
            query = """
                SELECT 
                    ti.id,
                    ti.status as trip_item_status,
                    oi.id as order_item_id,
                    oi.product_name,
                    oi.product_param_title as param_title,
                    oi.status as order_item_status,
                    o.order_type,
                    o.delivery_address,
                    oi.product_param_id,
                    o.status as order_status,
                    ct.status as courier_trip_status
                FROM trip_items ti
                JOIN order_items oi ON ti.order_item_id = oi.id
                JOIN orders o ON oi.order_id = o.id
                JOIN courier_trips ct ON ti.trip_id = ct.id
                WHERE oi.order_id = %s
            """
            params = [order_id]

            # Обработка trip_status
            if trip_status:
                if isinstance(trip_status, str):
                    trip_status = [trip_status]
                query += " AND ti.status::text = ANY(%s)"
                params.append(trip_status)

            # Обработка order_status
            if order_status:
                if isinstance(order_status, str):
                    order_status = [order_status]
                query += " AND o.status::text = ANY(%s)"
                params.append(order_status)

            # Обработка order_item_status
            if order_item_status:
                if isinstance(order_item_status, str):
                    order_item_status = [order_item_status]
                query += " AND oi.status::text = ANY(%s)"
                params.append(order_item_status)

            # Обработка courier_trip_status
            if courier_trip_status:
                if isinstance(courier_trip_status, str):
                    courier_trip_status = [courier_trip_status]
                query += " AND ct.status::text = ANY(%s)"
                params.append(courier_trip_status)

            cursor.execute(query, params)
            items = cursor.fetchall()

            return [{
                'id': item[0],
                'trip_status': item[1],
                'order_item_id': item[2],
                'product_name': item[3],
                'param_title': item[4],
                'status': item[5],  # order_item status
                'order_type': item[6],
                'delivery_address': item[7],
                'product_param_id': item[8],
                'order_status': item[9],
                'courier_trip_status': item[10]
            } for item in items]

        except Exception as e:
            print(f"Error getting trip items for order: {e}")
            return []
        finally:
            cursor.close()

    def get_trip_items(self, trip_id: int) -> List[Dict]:
        """Получает все товары в поездке с координатами"""
        cursor = self.db_connection.cursor()
        query = """
            SELECT 
                ti.id as trip_item_id,
                ti.status as trip_item_status,
                oi.status as status,
                oi.id as order_item_id,
                oi.product_name,
                oi.product_param_title,
                o.id as order_id,
                o.delivery_address,
                o.delivery_time,
                o.delivery_date,
                o.contact_name,
                o.contact_phone,
                o.order_type,
                da.coordinates
            FROM trip_items ti
            JOIN order_items oi ON ti.order_item_id = oi.id
            JOIN orders o ON oi.order_id = o.id
            LEFT JOIN delivery_addresses da ON o.id = da.order_id
            WHERE ti.trip_id = %s
            AND oi.status::text = ANY('{ready_to_delivery,in_delivery,partly_delivered}'::text[])
        """
        cursor.execute(query, (trip_id,))
        results = cursor.fetchall()

        formatted_results = []
        for row in results:
            # Разбираем адрес на компоненты, если он есть
            address_parts = row[7].split(',') if row[7] else []
            city = address_parts[0].strip() if len(address_parts) > 0 else None
            street = address_parts[1].strip() if len(address_parts) > 1 else None
            house = address_parts[2].strip() if len(address_parts) > 2 else None
            apartment = address_parts[3].strip() if len(address_parts) > 3 else None

            # Получаем координаты из GeoJSON
            coordinates = None
            if row[13]:  # Проверяем наличие координат
                coords_data = row[13]
                if isinstance(coords_data, str):
                    coords_data = json.loads(coords_data)
                coordinates = coords_data.get('coordinates', None) if coords_data else None

            formatted_results.append({
                'trip_item_id': row[0],
                'trip_item_status': row[1],
                'status': row[2],
                'order_item_id': row[3],
                'product_name': row[4],
                'param_title': row[5],
                'order_id': row[6],
                'delivery_address': row[7],
                'delivery_time': row[8],
                'delivery_date': row[9],
                'contact_name': row[10],
                'contact_phone': row[11],
                'order_type': row[12],
                'coordinates': coordinates,
                # Разбитые компоненты адреса
                'city': city,
                'street': street,
                'house': house,
                'apartment': apartment
            })

        return formatted_results

    def update_trip_status(self, trip_id: int, new_status: str) -> bool:
        """
        Обновляет статус поездки и связанных элементов

        Args:
            trip_id: ID поездки
            new_status: Новый статус
        Returns:
            bool: Успешность операции
        """
        cursor = self.db_connection.cursor()
        try:
            cursor.execute("BEGIN")

            # Обновляем статус поездки
            update_trip_query = """
                UPDATE courier_trips
                SET status = %s,
                    completed_at = CASE WHEN %s IN ('completed', 'cancelled') THEN NOW() ELSE NULL END
                WHERE id = %s
            """
            cursor.execute(update_trip_query, (new_status, new_status, trip_id))

            # Если поездка отменяется, обрабатываем все pending элементы
            if new_status == 'cancelled':
                # Получаем информацию о pending товарах
                cursor.execute("""
                    SELECT ti.id, ti.order_item_id, o.order_type
                    FROM trip_items ti
                    JOIN order_items oi ON ti.order_item_id = oi.id
                    JOIN orders o ON oi.order_id = o.id
                    WHERE ti.trip_id = %s AND ti.status = 'pending'
                """, (trip_id,))
                pending_items = cursor.fetchall()

                for item in pending_items:
                    item_id, order_item_id, order_type = item
                    # Обновляем статус в trip_items на 'refunded' вместо 'cancelled'
                    cursor.execute("""
                        UPDATE trip_items
                        SET status = 'refunded'
                        WHERE id = %s
                    """, (item_id,))

                    # Обновляем статус в order_items в зависимости от типа заказа
                    if order_type == 'avito':
                        cursor.execute("""
                            UPDATE order_items
                            SET status = 'refund'::public.status_order
                            WHERE id = %s
                        """, (order_item_id,))
                    else:
                        cursor.execute("""
                            UPDATE order_items
                            SET status = 'ready_to_delivery'::public.status_order
                            WHERE id = %s
                        """, (order_item_id,))

            cursor.execute("COMMIT")
            return True

        except Exception as e:
            cursor.execute("ROLLBACK")
            print(f"Error updating trip status: {e}")
            return False
        finally:
            cursor.close()

    def cancel_trip_items(self, trip_id: int, item_ids: List[int]) -> bool:
        """Отменяет выбранные товары в поездке"""
        try:
            cursor = self.db_connection.cursor()

            # Обновляем статус товаров
            update_query = """
                UPDATE trip_items
                SET status = 'refunded'
                WHERE trip_id = %s AND id = ANY(%s)
            """
            cursor.execute(update_query, (trip_id, item_ids))

            # Проверяем, остались ли активные товары
            check_query = """
                SELECT COUNT(*) as active_items
                FROM trip_items
                WHERE trip_id = %s AND status = 'pending'
            """
            cursor.execute(check_query, (trip_id,))
            active_items = cursor.fetchone()['active_items']

            # Если активных товаров не осталось, завершаем поездку
            if active_items == 0:
                self.update_trip_status(trip_id, 'completed')

            self.db_connection.commit()
            return True
        except Exception as e:
            print(f"Error canceling trip items: {e}")
            self.db_connection.rollback()
            return False