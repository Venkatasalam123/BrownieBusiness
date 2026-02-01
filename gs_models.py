"""
Google Sheets model wrappers to maintain compatibility with existing code
"""
from google_sheets import get_gs_db
from datetime import datetime
from decimal import Decimal

class QueryProperty:
    """Descriptor to make query work as a property like SQLAlchemy"""
    def __init__(self, query_class):
        self.query_class = query_class
    
    def __get__(self, obj, cls):
        if cls is None:
            cls = type(obj)
        return self.query_class()


class Column:
    """Column descriptor to mimic SQLAlchemy column access"""
    def __init__(self, name):
        self.name = name
        self.key = name  # For compatibility with order_by parsing
    
    def desc(self):
        """Return a descending column descriptor"""
        desc_col = Column(self.name)
        desc_col.is_descending = True
        return desc_col
    
    def asc(self):
        """Return an ascending column descriptor"""
        asc_col = Column(self.name)
        asc_col.is_descending = False
        return asc_col


# Define query classes first (they'll reference model classes later)
class VarietyQuery:
    """Query interface for Variety"""
    
    def __init__(self):
        self._order_by_attrs = []
        self._order_direction = 'asc'
    
    def order_by(self, *args):
        # Store ordering information
        # args can be like Variety.name or (Variety.name.desc(),)
        for arg in args:
            direction = 'asc'  # Reset direction for each arg
            if hasattr(arg, 'key'):  # Column descriptor
                attr_name = arg.key
                if hasattr(arg, 'is_descending'):
                    direction = 'desc' if arg.is_descending else 'asc'
            elif hasattr(arg, '__name__'):  # Try to get attribute name
                attr_name = arg.__name__
            elif isinstance(arg, str):
                attr_name = arg
            else:
                # Try to extract attribute name from various formats
                attr_name = str(arg).split('.')[-1] if '.' in str(arg) else str(arg)
            self._order_by_attrs.append((attr_name, direction))
        return self
    
    def all(self):
        gs = get_gs_db()
        varieties_data = gs.get_varieties()
        results = [Variety(id=v['id'], name=v['name'], default_price=v['default_price'], 
                          combo_pack_config=v.get('combo_pack_config')) 
                   for v in varieties_data]
        
        # Apply sorting
        if self._order_by_attrs:
            for attr_name, direction in reversed(self._order_by_attrs):
                reverse = (direction == 'desc')
                try:
                    results.sort(key=lambda x: getattr(x, attr_name, ''), reverse=reverse)
                except:
                    # If sorting fails, just continue
                    pass
        
        return results
    
    def filter_by(self, **kwargs):
        return VarietyFilterQuery(kwargs)
    
    def get(self, id):
        varieties = self.all()
        for v in varieties:
            if v.id == id:
                return v
        return None
    
    def get_or_404(self, id):
        """Get variety by ID or raise 404 error (Flask-SQLAlchemy compatibility)"""
        from flask import abort
        variety = self.get(id)
        if variety is None:
            abort(404)
        return variety
    
    def first(self):
        varieties = self.all()
        return varieties[0] if varieties else None


class VarietyFilterQuery:
    """Filter query for Variety"""
    
    def __init__(self, filters):
        self.filters = filters
    
    def first(self):
        varieties = Variety.query.all()
        for variety in varieties:
            match = True
            for key, value in self.filters.items():
                if getattr(variety, key, None) != value:
                    match = False
                    break
            if match:
                return variety
        return None


class ShopQuery:
    """Query interface for Shop"""
    
    def __init__(self):
        self._order_by_attrs = []
        self._order_direction = 'asc'
    
    def order_by(self, *args):
        # Store ordering information
        for arg in args:
            direction = 'asc'  # Reset direction for each arg
            if hasattr(arg, 'key'):  # Column descriptor
                attr_name = arg.key
                if hasattr(arg, 'is_descending'):
                    direction = 'desc' if arg.is_descending else 'asc'
            elif hasattr(arg, '__name__'):
                attr_name = arg.__name__
            elif isinstance(arg, str):
                attr_name = arg
            else:
                attr_name = str(arg).split('.')[-1] if '.' in str(arg) else str(arg)
            self._order_by_attrs.append((attr_name, direction))
        return self
    
    def all(self):
        gs = get_gs_db()
        shops_data = gs.get_shops()
        results = [Shop(id=s['id'], name=s['name']) for s in shops_data]
        
        # Apply sorting
        if self._order_by_attrs:
            for attr_name, direction in reversed(self._order_by_attrs):
                reverse = (direction == 'desc')
                try:
                    results.sort(key=lambda x: getattr(x, attr_name, ''), reverse=reverse)
                except:
                    pass
        
        return results
    
    def filter_by(self, **kwargs):
        return ShopFilterQuery(kwargs)
    
    def get(self, id):
        shops = self.all()
        for s in shops:
            if s.id == id:
                return s
        return None
    
    def get_or_404(self, id):
        """Get shop by ID or raise 404 error (Flask-SQLAlchemy compatibility)"""
        from flask import abort
        shop = self.get(id)
        if shop is None:
            abort(404)
        return shop
    
    def first(self):
        shops = self.all()
        return shops[0] if shops else None


class ShopFilterQuery:
    """Filter query for Shop"""
    
    def __init__(self, filters):
        self.filters = filters
    
    def first(self):
        shops = Shop.query.all()
        for shop in shops:
            match = True
            for key, value in self.filters.items():
                if getattr(shop, key, None) != value:
                    match = False
                    break
            if match:
                return shop
        return None


class OrderQuery:
    """Query interface for Order"""
    
    def __init__(self):
        self._order_by_attrs = []
        self._order_direction = 'asc'
    
    def order_by(self, *args):
        # Store ordering information
        for arg in args:
            direction = 'asc'  # Reset direction for each arg
            if hasattr(arg, 'key'):  # Column descriptor
                attr_name = arg.key
                if hasattr(arg, 'is_descending'):
                    direction = 'desc' if arg.is_descending else 'asc'
            elif hasattr(arg, '__name__'):
                attr_name = arg.__name__
            elif isinstance(arg, str):
                attr_name = arg
            else:
                # For things like Order.delivery_date.desc()
                attr_str = str(arg)
                if '.desc()' in attr_str or '.asc()' in attr_str:
                    attr_name = attr_str.split('.')[1] if '.' in attr_str else attr_str
                    direction = 'desc' if '.desc()' in attr_str else 'asc'
                else:
                    attr_name = attr_str.split('.')[-1] if '.' in attr_str else attr_str
            self._order_by_attrs.append((attr_name, direction))
        return self
    
    def all(self):
        gs = get_gs_db()
        orders_data = gs.get_orders()
        results = [Order(
            id=o['id'],
            variety_id=o['variety_id'],
            shop_id=o['shop_id'],
            quantity=o['quantity'],
            price=o['price'],
            delivery_date=o['delivery_date'],
            payment_status=o['payment_status'],
            paid_amount=o['paid_amount'],
            courier_price=o.get('courier_price', 0),
            created_at=o['created_at']
        ) for o in orders_data]
        
        # Apply sorting
        if self._order_by_attrs:
            for attr_name, direction in reversed(self._order_by_attrs):
                reverse = (direction == 'desc')
                try:
                    # Handle None values by putting them at the end
                    def sort_key(x):
                        val = getattr(x, attr_name, None)
                        return (val is None, val) if val is not None else (True, None)
                    results.sort(key=sort_key, reverse=reverse)
                except Exception as e:
                    # If sorting fails, try simple attribute access
                    try:
                        results.sort(key=lambda x: getattr(x, attr_name, ''), reverse=reverse)
                    except:
                        pass
        
        return results
    
    def filter_by(self, **kwargs):
        return OrderFilterQuery(kwargs)
    
    def get(self, id):
        orders = self.all()
        for o in orders:
            if o.id == id:
                return o
        return None
    
    def get_or_404(self, id):
        """Get order by ID or raise 404 error (Flask-SQLAlchemy compatibility)"""
        from flask import abort
        order = self.get(id)
        if order is None:
            abort(404)
        return order
    
    def count(self):
        return len(self.all())


class OrderFilterQuery:
    """Filter query for Order"""
    
    def __init__(self, filters):
        self.filters = filters
        self._order_by_attrs = []
        self._order_direction = 'asc'
    
    def all(self):
        orders = Order.query.all()
        filtered = []
        for order in orders:
            match = True
            for key, value in self.filters.items():
                if getattr(order, key, None) != value:
                    match = False
                    break
            if match:
                filtered.append(order)
        
        # Apply sorting if any
        if self._order_by_attrs:
            for attr_name, direction in reversed(self._order_by_attrs):
                reverse = (direction == 'desc')
                try:
                    def sort_key(x):
                        val = getattr(x, attr_name, None)
                        return (val is None, val) if val is not None else (True, None)
                    filtered.sort(key=sort_key, reverse=reverse)
                except Exception as e:
                    try:
                        filtered.sort(key=lambda x: getattr(x, attr_name, ''), reverse=reverse)
                    except:
                        pass
        
        return filtered
    
    def order_by(self, *args):
        # Store ordering information
        for arg in args:
            direction = 'asc'  # Reset direction for each arg
            if hasattr(arg, 'key'):  # Column descriptor
                attr_name = arg.key
                if hasattr(arg, 'is_descending'):
                    direction = 'desc' if arg.is_descending else 'asc'
            elif hasattr(arg, '__name__'):
                attr_name = arg.__name__
            elif isinstance(arg, str):
                attr_name = arg
            else:
                # For things like Order.delivery_date.desc()
                attr_str = str(arg)
                if '.desc()' in attr_str or '.asc()' in attr_str:
                    attr_name = attr_str.split('.')[1] if '.' in attr_str else attr_str
                    direction = 'desc' if '.desc()' in attr_str else 'asc'
                else:
                    attr_name = attr_str.split('.')[-1] if '.' in attr_str else attr_str
            self._order_by_attrs.append((attr_name, direction))
        return self


class IngredientPriceQuery:
    """Query interface for IngredientPrice"""
    
    def __init__(self):
        self._order_by_attrs = []
        self._order_direction = 'asc'
    
    def order_by(self, *args):
        for arg in args:
            direction = 'asc'
            if hasattr(arg, 'key'):
                attr_name = arg.key
                if hasattr(arg, 'is_descending'):
                    direction = 'desc' if arg.is_descending else 'asc'
            elif hasattr(arg, '__name__'):
                attr_name = arg.__name__
            elif isinstance(arg, str):
                attr_name = arg
            else:
                attr_name = str(arg).split('.')[-1] if '.' in str(arg) else str(arg)
            self._order_by_attrs.append((attr_name, direction))
        return self
    
    def all(self):
        gs = get_gs_db()
        ingredients_data = gs.get_ingredient_prices()
        results = [IngredientPrice(
            id=i['id'],
            name=i['name'],
            price=i['price'],
            unit=i['unit'],
            package_size=i['package_size'],
            package_unit=i['package_unit'],
            updated_at=i['updated_at']
        ) for i in ingredients_data]
        
        # Apply sorting
        if self._order_by_attrs:
            for attr_name, direction in reversed(self._order_by_attrs):
                reverse = (direction == 'desc')
                try:
                    results.sort(key=lambda x: getattr(x, attr_name, ''), reverse=reverse)
                except:
                    pass
        
        return results
    
    def filter_by(self, **kwargs):
        return IngredientPriceFilterQuery(kwargs)
    
    def get(self, id):
        ingredients = self.all()
        for i in ingredients:
            if i.id == id:
                return i
        return None
    
    def get_or_404(self, id):
        """Get ingredient price by ID or raise 404 error"""
        from flask import abort
        ingredient = self.get(id)
        if ingredient is None:
            abort(404)
        return ingredient
    
    def first(self):
        ingredients = self.all()
        return ingredients[0] if ingredients else None


class IngredientPriceFilterQuery:
    """Filter query for IngredientPrice"""
    
    def __init__(self, filters):
        self.filters = filters
    
    def first(self):
        ingredients = IngredientPrice.query.all()
        for ingredient in ingredients:
            match = True
            for key, value in self.filters.items():
                if getattr(ingredient, key, None) != value:
                    match = False
                    break
            if match:
                return ingredient
        return None


# Now define model classes
class Variety:
    """Variety model wrapper for Google Sheets"""
    
    # Column descriptors for SQLAlchemy-like access
    name = Column('name')
    id = Column('id')
    default_price = Column('default_price')
    combo_pack_config = Column('combo_pack_config')
    
    def __init__(self, id=None, name=None, default_price=None, combo_pack_config=None):
        self.id = id
        self.name = name
        self.default_price = default_price
        self.combo_pack_config = combo_pack_config
    
    def __repr__(self):
        return f'<Variety {self.name}>'
    
    def get_combo_pack_varieties(self):
        """Get list of variety items in this combo pack with quantities
        Returns list of dicts: [{"id": 1, "quantity": 2}, {"id": 2, "quantity": 1}]
        For backward compatibility, handles multiple formats:
        - Old format: [1, 2, 3] (list of integers)
        - Medium format: [{"id": 1, "quantity": 2}] (list of dicts)
        - New format: {"items": [...], "extra_packing_cost": 5.0} (object with items and cost)
        """
        if self.combo_pack_config:
            try:
                import json
                data = json.loads(self.combo_pack_config)
                # Check if it's new format (object with items and extra_packing_cost)
                if isinstance(data, dict) and 'items' in data:
                    return data.get('items', [])
                # Check if it's old format (list of integers)
                elif isinstance(data, list) and data and isinstance(data[0], int):
                    # Convert old format to new format
                    return [{"id": vid, "quantity": 1} for vid in data]
                # Medium format (list of dicts)
                elif isinstance(data, list):
                    return data
            except:
                return []
        return []
    
    def get_extra_packing_cost(self):
        """Get extra packing cost for combo pack, defaults to 5.0"""
        if self.combo_pack_config:
            try:
                import json
                data = json.loads(self.combo_pack_config)
                # Check if it's new format (object with items and extra_packing_cost)
                if isinstance(data, dict) and 'extra_packing_cost' in data:
                    return float(data.get('extra_packing_cost', 5.0))
            except:
                pass
        return 5.0  # Default value
    
    def is_combo_pack(self):
        """Check if this variety is a combo pack"""
        return self.combo_pack_config is not None and self.combo_pack_config.strip() != ''
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'default_price': float(self.default_price) if self.default_price else 0.0,
            'combo_pack_config': self.get_combo_pack_varieties()
        }


class Shop:
    """Shop model wrapper for Google Sheets"""
    
    # Column descriptors for SQLAlchemy-like access
    name = Column('name')
    id = Column('id')
    
    def __init__(self, id=None, name=None):
        self.id = id
        self.name = name
    
    def __repr__(self):
        return f'<Shop {self.name}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name
        }


class Order:
    """Order model wrapper for Google Sheets"""
    
    # Column descriptors for SQLAlchemy-like access
    id = Column('id')
    variety_id = Column('variety_id')
    shop_id = Column('shop_id')
    quantity = Column('quantity')
    returns = Column('returns')
    price = Column('price')
    delivery_date = Column('delivery_date')
    payment_status = Column('payment_status')
    paid_amount = Column('paid_amount')
    courier_price = Column('courier_price')
    created_at = Column('created_at')
    
    def __init__(self, id=None, variety_id=None, shop_id=None, quantity=None, 
                 returns=0, price=None, delivery_date=None, payment_status='unpaid', 
                 paid_amount=0, courier_price=0, created_at=None):
        self.id = id
        self.variety_id = variety_id
        self.shop_id = shop_id
        self.quantity = quantity
        self.returns = returns or 0
        self.price = price
        self.delivery_date = delivery_date
        self.payment_status = payment_status
        self.paid_amount = paid_amount
        self.courier_price = courier_price
        self.created_at = created_at
        self._variety = None
        self._shop = None
    
    @property
    def variety(self):
        if not self._variety and self.variety_id:
            self._variety = Variety.query.get(self.variety_id)
        return self._variety
    
    @property
    def shop(self):
        if not self._shop and self.shop_id:
            self._shop = Shop.query.get(self.shop_id)
        return self._shop
    
    def __repr__(self):
        return f'<Order {self.id}>'
    
    def to_dict(self):
        effective_quantity = max(0, (self.quantity or 0) - (self.returns or 0))
        return {
            'id': self.id,
            'variety_id': self.variety_id,
            'shop_id': self.shop_id,
            'quantity': self.quantity or 0,
            'returns': self.returns or 0,
            'effective_quantity': effective_quantity,
            'price': float(self.price) if self.price else 0.0,
            'delivery_date': self.delivery_date.isoformat() if self.delivery_date else None,
            'payment_status': self.payment_status,
            'paid_amount': float(self.paid_amount) if self.paid_amount else 0.0,
            'courier_price': float(self.courier_price) if self.courier_price else 0.0,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'total': float(self.price * effective_quantity) if self.price and effective_quantity else 0.0
        }


class IngredientPrice:
    """IngredientPrice model wrapper for Google Sheets"""
    
    # Column descriptors for SQLAlchemy-like access
    id = Column('id')
    name = Column('name')
    price = Column('price')
    unit = Column('unit')
    package_size = Column('package_size')
    package_unit = Column('package_unit')
    updated_at = Column('updated_at')
    
    def __init__(self, id=None, name=None, price=None, unit=None, 
                 package_size=None, package_unit=None, updated_at=None):
        self.id = id
        self.name = name
        self.price = price
        self.unit = unit
        self.package_size = package_size
        self.package_unit = package_unit
        self.updated_at = updated_at
    
    def __repr__(self):
        return f'<IngredientPrice {self.name}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'price': float(self.price) if self.price else 0.0,
            'unit': self.unit,
            'package_size': float(self.package_size) if self.package_size else 0.0,
            'package_unit': self.package_unit
        }
    
    def get_price_per_gram(self):
        """Get price per gram for weight-based ingredients"""
        if self.package_unit in ['g', 'kg']:
            size_in_grams = float(self.package_size) * (1000 if self.package_unit == 'kg' else 1)
            return float(self.price) / size_in_grams
        return None
    
    def get_price_per_ml(self):
        """Get price per ml for volume-based ingredients"""
        if self.package_unit == 'ml':
            return float(self.price) / float(self.package_size)
        return None
    
    def get_price_per_piece(self):
        """Get price per piece for count-based ingredients"""
        if self.package_unit == 'pc':
            return float(self.price) / float(self.package_size)
        return None


# Set query properties after all classes are defined
Variety.query = QueryProperty(VarietyQuery)
Shop.query = QueryProperty(ShopQuery)
Order.query = QueryProperty(OrderQuery)
IngredientPrice.query = QueryProperty(IngredientPriceQuery)


# Database session mock for compatibility
class DBSession:
    """Mock database session for compatibility"""
    
    def add(self, obj):
        gs = get_gs_db()
        if isinstance(obj, Variety):
            gs.add_variety(obj.name, obj.default_price)
        elif isinstance(obj, Shop):
            gs.add_shop(obj.name)
        elif isinstance(obj, Order):
            gs.add_order(
                obj.variety_id, obj.shop_id, obj.quantity, obj.price,
                obj.delivery_date, obj.payment_status, obj.paid_amount,
                obj.courier_price if hasattr(obj, 'courier_price') and obj.courier_price else 0
            )
        elif isinstance(obj, IngredientPrice):
            gs.add_ingredient_price(
                obj.name, obj.price, obj.unit, obj.package_size, obj.package_unit
            )
    
    def delete(self, obj):
        gs = get_gs_db()
        if isinstance(obj, Variety):
            gs.delete_variety(obj.id)
        elif isinstance(obj, Shop):
            gs.delete_shop(obj.id)
        # Orders and IngredientPrices deletion handled separately
    
    def commit(self):
        pass  # Google Sheets writes are immediate
    
    def flush(self):
        pass
    
    def rollback(self):
        pass  # Not applicable for Google Sheets


# Mock db object for compatibility
class MockDB:
    def init_app(self, app):
        pass
    
    def create_all(self):
        gs = get_gs_db()
        gs.initialize_sheets()


db = MockDB()
session = DBSession()
