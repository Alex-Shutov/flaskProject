from enum import Enum

class UserRole(Enum):
    MANAGER = 'Manager'
    COURIER = 'Courier'
    ADMIN = 'Admin'
    OWNER = 'Owner'

class SaleType(Enum):
    DIRECT='direct'
    DELIVERY='delivery'
    AVITO='avito'

class SaleTypeRu(Enum):
    DIRECT='Прямая'
    DELIVERY='Доставка'
    AVITO='Авито'

class OrderType(Enum):
    ACTIVE='active'
    IN_DELIVERY='in_delivery'
    CLOSED='closed'
    REFUND='refund'

class OrderTypeRu(Enum):
    ACTIVE = 'Активный'
    IN_DELIVERY = 'В доставке'
    CLOSED = 'Закрыт'
    REFUND = 'Возврат'

