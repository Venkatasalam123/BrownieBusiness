from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class Variety(db.Model):
    """Brownie variety model"""
    __tablename__ = 'varieties'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    default_price = db.Column(db.Numeric(10, 2), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship with orders
    orders = db.relationship('Order', backref='variety', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Variety {self.name}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'default_price': float(self.default_price)
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
            'total': float(self.price * effective_quantity),
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

