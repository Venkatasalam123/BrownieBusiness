from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json

db = SQLAlchemy()


def _normalize_combo_pack_item_list(items):
    """Coerce variety id/quantity from JSON (e.g. string ids from Sheets) to int."""
    if not items:
        return []
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        vid = item.get('id')
        if isinstance(vid, str) and vid.strip().isdigit():
            vid = int(vid.strip())
        elif isinstance(vid, (int, float)) and not isinstance(vid, bool):
            vid = int(vid)
        qty = item.get('quantity', 1)
        if isinstance(qty, str) and qty.strip().isdigit():
            qty = int(qty.strip())
        elif isinstance(qty, (int, float)) and not isinstance(qty, bool):
            qty = int(qty)
        else:
            qty = 1
        if vid is not None:
            out.append({'id': vid, 'quantity': qty})
    return out


class Variety(db.Model):
    """Brownie variety model"""
    __tablename__ = 'varieties'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    default_price = db.Column(db.Numeric(10, 2), nullable=False)
    combo_pack_config = db.Column(db.Text, nullable=True)  # JSON string storing list of variety IDs
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship with orders
    orders = db.relationship('Order', backref='variety', lazy=True, cascade='all, delete-orphan')
    
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
                data = json.loads(self.combo_pack_config)
                raw = []
                if isinstance(data, dict) and 'items' in data:
                    raw = data.get('items', [])
                elif isinstance(data, list) and data:
                    if all(isinstance(x, int) for x in data):
                        raw = [{"id": vid, "quantity": 1} for vid in data]
                    elif all(
                        isinstance(x, (int, str)) and str(x).strip().lstrip('-').isdigit()
                        for x in data
                    ):
                        raw = [
                            {"id": int(str(x).strip()), "quantity": 1} for x in data
                        ]
                    else:
                        raw = data
                return _normalize_combo_pack_item_list(raw)
            except (json.JSONDecodeError, TypeError, ValueError):
                return []
        return []
    
    def get_extra_packing_cost(self):
        """Get extra packing cost for combo pack, defaults to 5.0"""
        if self.combo_pack_config:
            try:
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
            'default_price': float(self.default_price),
            'combo_pack_config': self.get_combo_pack_varieties()
        }


class Shop(db.Model):
    """Shop/Customer model"""
    __tablename__ = 'shops'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship with orders
    orders = db.relationship('Order', backref='shop', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Shop {self.name}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name
        }


class Order(db.Model):
    """Order model"""
    __tablename__ = 'orders'
    
    id = db.Column(db.Integer, primary_key=True)
    variety_id = db.Column(db.Integer, db.ForeignKey('varieties.id'), nullable=False)
    shop_id = db.Column(db.Integer, db.ForeignKey('shops.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    returns = db.Column(db.Integer, nullable=False, default=0)  # Number of returned items
    price = db.Column(db.Numeric(10, 2), nullable=False)
    delivery_date = db.Column(db.Date, nullable=False)
    payment_status = db.Column(db.String(20), nullable=False, default='unpaid')  # 'paid', 'unpaid', 'partial'
    paid_amount = db.Column(db.Numeric(10, 2), nullable=True, default=0)
    courier_price = db.Column(db.Numeric(10, 2), nullable=True, default=0)  # Courier/shipping cost
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Order {self.id}>'
    
    def to_dict(self):
        effective_quantity = max(0, self.quantity - (self.returns or 0))
        goods = float(self.price) * effective_quantity
        courier = float(self.courier_price) if self.courier_price else 0.0
        return {
            'id': self.id,
            'variety_id': self.variety_id,
            'shop_id': self.shop_id,
            'quantity': self.quantity,
            'returns': self.returns or 0,
            'effective_quantity': effective_quantity,
            'price': float(self.price),
            'delivery_date': self.delivery_date.isoformat(),
            'created_at': self.created_at.isoformat(),
            'total': goods + courier,
            'payment_status': self.payment_status,
            'paid_amount': float(self.paid_amount) if self.paid_amount else 0,
            'courier_price': float(self.courier_price) if self.courier_price else 0
        }


class IngredientPrice(db.Model):
    """Ingredient price model"""
    __tablename__ = 'ingredient_prices'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    unit = db.Column(db.String(50), nullable=False)  # e.g., '500g', '1kg', '1pc', '100ml', '25g'
    package_size = db.Column(db.Numeric(10, 2), nullable=False)  # Size of the package (e.g., 500 for 500g, 1 for 1pc)
    package_unit = db.Column(db.String(20), nullable=False)  # Unit of package (e.g., 'g', 'kg', 'pc', 'ml')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<IngredientPrice {self.name}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'price': float(self.price),
            'unit': self.unit,
            'package_size': float(self.package_size),
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

