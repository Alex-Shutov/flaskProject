from dataclasses import dataclass
from typing import Optional, Tuple, Dict, List
import requests
import json
from datetime import datetime
from shapely.geometry import Point, Polygon


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

    def calculate_for_trip(self, trip_items: List[Dict], zone_id: int) -> Optional[DeliveryCost]:
        """Рассчитывает стоимость доставки для поездки"""
        try:
            cursor = self.db_connection.cursor()
            query = """
                SELECT name, base_price, additional_item_price
                FROM delivery_zones
                WHERE id = %s
            """
            cursor.execute(query, (zone_id,))
            zone_info = cursor.fetchone()

            if not zone_info:
                return None

            items_count = len(trip_items)
            base_price = float(zone_info['base_price'])
            additional_items_price = float(zone_info['additional_item_price']) * (items_count - 1)

            return DeliveryCost(
                base_price=base_price,
                additional_items_price=additional_items_price,
                total_price=base_price + additional_items_price,
                zone_name=zone_info['name'],
                items_count=items_count
            )
        except Exception as e:
            print(f"Error calculating delivery cost: {e}")
            return None


class CourierTripManager:
    """Менеджер для работы с поездками курьеров"""

    def __init__(self, db_connection):
        self.db_connection = db_connection

    def create_trip(self, courier_id: int, zone_id: int) -> Optional[int]:
        """Создает новую поездку"""
        try:
            cursor = self.db_connection.cursor()
            query = """
                INSERT INTO courier_trips (courier_id, zone_id, status, created_at)
                VALUES (%s, %s, 'created', %s)
                RETURNING id
            """
            cursor.execute(query, (courier_id, zone_id, datetime.now()))
            self.db_connection.commit()
            return cursor.fetchone()['id']
        except Exception as e:
            print(f"Error creating trip: {e}")
            self.db_connection.rollback()
            return None

    def add_items_to_trip(self, trip_id: int, item_ids: List[int]) -> bool:
        """Добавляет товары в поездку"""
        try:
            cursor = self.db_connection.cursor()
            values = [(trip_id, item_id, 'pending', datetime.now()) for item_id in item_ids]

            query = """
                INSERT INTO trip_items (trip_id, order_item_id, status, created_at)
                VALUES (%s, %s, %s, %s)
            """
            cursor.executemany(query, values)
            self.db_connection.commit()
            return True
        except Exception as e:
            print(f"Error adding items to trip: {e}")
            self.db_connection.rollback()
            return False

    def get_trip_items(self, trip_id: int) -> List[Dict]:
        """Получает все товары в поездке"""
        cursor = self.db_connection.cursor()
        query = """
            SELECT 
                ti.id as trip_item_id,
                ti.status as trip_item_status,
                oi.id as order_item_id,
                oi.product_name,
                o.id as order_id,
                da.city,
                da.street,
                da.house,
                da.apartment,
                dz.name as zone_name
            FROM trip_items ti
            JOIN order_items oi ON ti.order_item_id = oi.id
            JOIN orders o ON oi.order_id = o.id
            JOIN delivery_addresses da ON o.delivery_address_id = da.id
            JOIN delivery_zones dz ON da.zone_id = dz.id
            WHERE ti.trip_id = %s
        """
        cursor.execute(query, (trip_id,))
        return cursor.fetchall()

    def update_trip_status(self, trip_id: int, new_status: str) -> bool:
        """Обновляет статус поездки"""
        try:
            cursor = self.db_connection.cursor()
            query = """
                UPDATE courier_trips
                SET status = %s,
                    completed_at = CASE WHEN %s = 'completed' THEN NOW() ELSE NULL END
                WHERE id = %s
            """
            cursor.execute(query, (new_status, new_status, trip_id))
            self.db_connection.commit()
            return True
        except Exception as e:
            print(f"Error updating trip status: {e}")
            self.db_connection.rollback()
            return False

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