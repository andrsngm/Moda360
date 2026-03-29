from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.ext.hybrid import hybrid_property

db = SQLAlchemy()

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False) # Teléfono
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(60), nullable=False)
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    telefono = db.Column(db.String(20))
    
    # Rol de administrador
    es_admin = db.Column(db.Boolean, default=False)
    
    # Relación uno a muchos con Pedidos
    pedidos = db.relationship('Pedido', backref='cliente', lazy=True)

    @hybrid_property
    def deuda_total(self):
        """Calcula la deuda sumando lo pendiente de todos sus pedidos"""
        total_deuda = 0
        if self.pedidos:
            for pedido in self.pedidos:
                # Solo sumamos deuda de pedidos confirmados o validados, no "por confirmar" si así lo deseas
                # Por ahora suma todo lo pendiente general
                total_deuda += (pedido.total_a_pagar - pedido.monto_pagado)
        return round(total_deuda, 2)

    @deuda_total.expression
    def deuda_total(cls):
        """Permite filtrar por deuda_total en consultas SQL"""
        return (
            select(func.sum(Pedido.total_a_pagar - Pedido.monto_pagado))
            .where(Pedido.usuario_id == cls.id)
            .label('deuda_total_query')
        )

class Producto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    precio_costo = db.Column(db.Float, nullable=False, default=0.0) 
    precio_venta = db.Column(db.Float, nullable=False)
    stock_fisico = db.Column(db.Integer, default=0)
    imagen_url = db.Column(db.String(300), default='default.jpg')
    descuento = db.Column(db.Integer, default=0) # 0 a 100

    @property
    def precio_final(self):
        """Calcula el precio aplicando el descuento"""
        if self.descuento > 0:
            return self.precio_venta * (1 - self.descuento / 100)
        return self.precio_venta

class ItemPedido(db.Model):
    """
    Clase intermedia que permite múltiples unidades del mismo producto 
    y guarda el precio al que se vendió en ese momento.
    """
    __tablename__ = 'item_pedido'
    id = db.Column(db.Integer, primary_key=True)
    pedido_id = db.Column(db.Integer, db.ForeignKey('pedido.id'), nullable=False)
    producto_id = db.Column(db.Integer, db.ForeignKey('producto.id'), nullable=False)
    
    cantidad = db.Column(db.Integer, default=1)
    precio_unitario = db.Column(db.Float, nullable=False) # Precio con descuento aplicado al momento de la orden

    # Relación directa con el objeto producto para acceder a su nombre, imagen, etc.
    producto = db.relationship('Producto')

class Pedido(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Estados: 'por confirmar', 'confirmado', 'pagado'
    estado = db.Column(db.String(20), default='por confirmar') 
    
    total_a_pagar = db.Column(db.Float, default=0.0)
    monto_pagado = db.Column(db.Float, default=0.0) 
    
    usuario_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    
    # Relación con los items del pedido
    # cascade="all, delete-orphan" asegura que si borras un pedido, se borren sus productos asociados
    items = db.relationship('ItemPedido', backref='pedido', cascade="all, delete-orphan", lazy=True)

    @property
    def saldo_pendiente(self):
        """Diferencia entre total y lo pagado"""
        return self.total_a_pagar - self.monto_pagado

    @property
    def productos(self):
        """
        Mantiene compatibilidad con código anterior devolviendo 
        una lista de objetos Producto a través de los items.
        """
        return [item.producto for item in self.items]