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
    price = db.Column(db.Numeric(10, 2), nullable=False)
    delivery_date = db.Column(db.Date, nullable=False)
    payment_status = db.Column(db.String(20), nullable=False, default='unpaid')  # 'paid', 'unpaid', 'partial'
    paid_amount = db.Column(db.Numeric(10, 2), nullable=True, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Order {self.id}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'variety_id': self.variety_id,
            'shop_id': self.shop_id,
            'quantity': self.quantity,
            'price': float(self.price),
            'delivery_date': self.delivery_date.isoformat(),
            'created_at': self.created_at.isoformat(),
            'total': float(self.price * self.quantity),
            'payment_status': self.payment_status,
            'paid_amount': float(self.paid_amount) if self.paid_amount else 0
        }

