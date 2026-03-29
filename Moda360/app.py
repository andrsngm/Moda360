import os
from datetime import datetime
from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, session
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, login_user, current_user, logout_user, login_required
from werkzeug.utils import secure_filename
# Importamos ItemPedido además de los otros modelos
from models import db, User, Producto, Pedido, ItemPedido 
from sqlalchemy.exc import IntegrityError

app = Flask(__name__)
app.config['SECRET_KEY'] = 'tu_llave_secreta_aqui'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///moda360.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- CONFIGURACIÓN DE CARGA DE IMÁGENES ---
UPLOAD_FOLDER = os.path.join('static', 'uploads', 'productos')
PAYMENTS_FOLDER = os.path.join('static', 'uploads', 'comprobantes') # Carpeta para pagos
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['PAYMENTS_FOLDER'] = PAYMENTS_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# Asegurar que las carpetas existan
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PAYMENTS_FOLDER, exist_ok=True)

# --- MODELO DE PAGOS PARA VALIDACIÓN ---
class PagoNotificado(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    pedido_id = db.Column(db.Integer, db.ForeignKey('pedido.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    monto = db.Column(db.Float, nullable=False)
    referencia = db.Column(db.String(100), nullable=False)
    comprobante_url = db.Column(db.String(255), nullable=False)
    estado = db.Column(db.String(20), default='pendiente') # pendiente, aprobado, rechazado
    fecha_notificacion = db.Column(db.DateTime, default=datetime.utcnow)

    pedido = db.relationship('Pedido', backref=db.backref('pagos_pendientes', lazy=True))
    usuario = db.relationship('User', backref=db.backref('mis_pagos', lazy=True))

# Inicialización de extensiones
db.init_app(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login' 
login_manager.login_message = "Por favor inicia sesión para acceder."
login_manager.login_message_category = "danger"

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# --- RUTAS PRINCIPALES ---

@app.route('/')
def home():
    productos = Producto.query.filter(Producto.stock_fisico > 0).all()
    todos_los_clientes = []
    if current_user.is_authenticated and current_user.es_admin:
        todos_los_clientes = User.query.filter_by(es_admin=False).all()
        
    return render_template('home.html', productos=productos, todos_los_clientes=todos_los_clientes)

# --- RUTAS DE AUTENTICACIÓN ---

@app.route("/registro", methods=['GET', 'POST'])
def registro():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard_admin' if current_user.es_admin else 'dashboard_cliente'))
    
    if request.method == 'POST':
        try:
            hashed_pw = bcrypt.generate_password_hash(request.form['password']).decode('utf-8')
            user = User(
                username=request.form['telefono'],
                email=request.form.get('email', ''),
                password=hashed_pw,
                first_name=request.form['nombre'],
                last_name=request.form['apellido'],
                telefono=request.form['telefono'],
                es_admin=False
            )
            db.session.add(user)
            db.session.commit()
            
            login_user(user)
            flash('Cuenta creada con éxito', 'success')
            return redirect(url_for('dashboard_cliente'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al registrar: {str(e)}', 'danger')
            
    return render_template('registro.html')

@app.route("/login", methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard_admin' if current_user.es_admin else 'dashboard_cliente'))
        
    if request.method == 'POST':
        telefono = request.form.get('telefono')
        password = request.form.get('password')
        user = User.query.filter_by(username=telefono).first()
        
        if user and bcrypt.check_password_hash(user.password, password):
            login_user(user)
            flash(f'Bienvenido, {user.first_name}', 'success')
            
            if user.es_admin:
                return redirect(url_for('dashboard_admin'))
            return redirect(url_for('dashboard_cliente'))
        else:
            flash('Login fallido. Revisa el teléfono y la clave', 'danger')
            
    return render_template('login.html')

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash('Has cerrado sesión correctamente.', 'info')
    return redirect(url_for('home'))

# --- DASHBOARDS ---

@app.route("/mi-cuenta")
@login_required
def dashboard_cliente():
    if current_user.es_admin:
        return redirect(url_for('dashboard_admin'))
    pedidos = Pedido.query.filter_by(usuario_id=current_user.id).order_by(Pedido.id.desc()).all()
    return render_template('dashboard_cliente.html', user=current_user, pedidos=pedidos)

@app.route('/admin/dashboard')
@login_required
def dashboard_admin():
    if not current_user.es_admin:
        flash('Acceso restringido.', 'danger')
        return redirect(url_for('home'))
    
    total_usuarios = User.query.count()
    productos = Producto.query.all()
    valor_inventario = sum((p.precio_costo or 0) * (p.stock_fisico or 0) for p in productos)
    clientes_deudores = User.query.filter(User.deuda_total > 0).all()
    total_deuda_global = sum(cliente.deuda_total for cliente in clientes_deudores)
    
    # Obtener pagos pendientes para la nueva tabla de validación
    pagos_pendientes = PagoNotificado.query.filter_by(estado='pendiente').all()
    
    return render_template('dashboard_admin.html', 
                           user=current_user, 
                           total_users=total_usuarios, 
                           productos=productos,
                           clientes_deudores=clientes_deudores,
                           total_deuda_global=total_deuda_global,
                           valor_inventario=valor_inventario,
                           pagos_pendientes=pagos_pendientes)

@app.route('/admin/cobranzas')
@login_required
def admin_cobranzas():
    if not current_user.es_admin:
        return redirect(url_for('home'))
    
    clientes_deudores = User.query.filter(User.deuda_total > 0).all()
    return render_template('cobranzas.html', clientes_deudores=clientes_deudores)

# --- LÓGICA DE CARRITO Y PEDIDOS ---

@app.route("/añadir-al-carrito/<int:producto_id>", methods=['POST'])
@login_required
def añadir_al_carrito(producto_id):
    producto = Producto.query.get_or_404(producto_id)
    
    if current_user.es_admin:
        target_user_id = request.form.get('cliente_id')
        if not target_user_id:
            flash('Error: Debes seleccionar un cliente.', 'danger')
            return redirect(url_for('home'))
        nuevo_estado = 'confirmado'
    else:
        target_user_id = current_user.id
        nuevo_estado = 'por confirmar'

    try:
        pedido = Pedido.query.filter_by(usuario_id=target_user_id, estado=nuevo_estado).first()
        
        if not pedido:
            pedido = Pedido(usuario_id=target_user_id, estado=nuevo_estado, total_a_pagar=0.0)
            db.session.add(pedido)
            db.session.flush()

        item = ItemPedido.query.filter_by(pedido_id=pedido.id, producto_id=producto.id).first()

        if item:
            item.cantidad += 1
        else:
            item = ItemPedido(
                pedido_id=pedido.id,
                producto_id=producto.id,
                cantidad=1,
                precio_unitario=producto.precio_final
            )
            db.session.add(item)

        pedido.total_a_pagar += producto.precio_final
        if producto.stock_fisico > 0:
            producto.stock_fisico -= 1
        
        db.session.commit()
        mensaje = "Asignado correctamente." if current_user.es_admin else f"{producto.nombre} añadido. Revisa tu panel."
        flash(mensaje, 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error al procesar: {str(e)}', 'danger')

    return redirect(url_for('home'))

@app.route('/confirmar_pedido/<int:pedido_id>', methods=['POST'])
@login_required
def confirmar_pedido(pedido_id):
    pedido = Pedido.query.get_or_404(pedido_id)
    if pedido.usuario_id != current_user.id:
        flash("Acceso no autorizado.", "danger")
        return redirect(url_for('dashboard_cliente'))
    
    pedido.estado = 'confirmado'
    db.session.commit()
    flash("¡Orden confirmada con éxito!", "success")
    return redirect(url_for('dashboard_cliente'))

@app.route('/eliminar_pedido/<int:pedido_id>', methods=['POST'])
@login_required
def eliminar_pedido(pedido_id):
    pedido = Pedido.query.get_or_404(pedido_id)
    if pedido.usuario_id != current_user.id:
        flash("Acceso no autorizado.", "danger")
        return redirect(url_for('dashboard_cliente'))
        
    try:
        for item in pedido.items:
            item.producto.stock_fisico += item.cantidad
            
        db.session.delete(pedido)
        db.session.commit()
        flash("Pedido cancelado y productos devueltos al stock.", "info")
    except Exception as e:
        db.session.rollback()
        flash(f"Error al eliminar: {str(e)}", "danger")
        
    return redirect(url_for('dashboard_cliente'))

# --- GESTIÓN ADMINISTRATIVA Y PRODUCTOS ---

@app.route("/admin/nuevo-producto", methods=['POST'])
@login_required
def nuevo_producto():
    if not current_user.es_admin:
        return jsonify({"error": "No autorizado"}), 403
    
    try:
        file = request.files.get('imagen')
        filename = 'default.jpg'
        
        if file and file.filename != '':
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        prod = Producto(
            nombre=request.form.get('nombre'),
            precio_costo=float(request.form.get('precio_costo') or 0),
            precio_venta=float(request.form.get('precio_venta') or 0),
            stock_fisico=int(request.form.get('stock') or 0),
            descuento=int(request.form.get('descuento') or 0),
            imagen_url=filename
        )
        db.session.add(prod)
        db.session.commit()
        flash('Producto agregado con éxito', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'danger')

    return redirect(url_for('dashboard_admin'))

# --- NUEVA LÓGICA DE PAGOS SEGURA ---

@app.route("/registrar_pago", methods=['POST'])
@login_required
def registrar_pago():
    """El cliente envía el comprobante, pero NO se descuenta de la deuda aún."""
    try:
        pedido_id = request.form.get('pedido_id')
        monto = float(request.form.get('monto') or 0)
        referencia = request.form.get('referencia')
        file = request.files.get('comprobante')

        if not file or file.filename == '':
            flash('Debes adjuntar el comprobante de pago.', 'warning')
            return redirect(url_for('dashboard_cliente'))

        pedido = Pedido.query.get_or_404(pedido_id)
        if pedido.usuario_id != current_user.id:
            flash("Operación no permitida.", "danger")
            return redirect(url_for('dashboard_cliente'))

        # Guardar archivo con nombre único
        filename = secure_filename(f"REF_{referencia}_{file.filename}")
        file.save(os.path.join(app.config['PAYMENTS_FOLDER'], filename))
        
        # Crear registro de pago pendiente
        nuevo_pago = PagoNotificado(
            pedido_id=pedido.id,
            usuario_id=current_user.id,
            monto=monto,
            referencia=referencia,
            comprobante_url=filename,
            estado='pendiente'
        )
        db.session.add(nuevo_pago)
        db.session.commit()
        
        flash(f'Notificación enviada. Espera a que el administrador valide la referencia {referencia}.', 'info')

    except Exception as e:
        db.session.rollback()
        flash(f'Error al registrar pago: {str(e)}', 'danger')

    return redirect(url_for('dashboard_cliente'))

@app.route("/admin/validar-pago/<int:pago_id>/<string:accion>", methods=['POST'])
@login_required
def validar_pago(pago_id, accion):
    """El administrador aprueba o rechaza el pago. Solo 'aprobar' descuenta la deuda."""
    if not current_user.es_admin:
        return jsonify({"error": "No autorizado"}), 403
    
    pago = PagoNotificado.query.get_or_404(pago_id)
    
    try:
        if accion == 'aprobar':
            pago.estado = 'aprobado'
            # AQUÍ ES DONDE REALMENTE SE ACTUALIZA LA DEUDA
            pago.pedido.monto_pagado += pago.monto
            flash(f"Pago de {pago.usuario.first_name} aprobado con éxito.", "success")
        elif accion == 'rechazar':
            pago.estado = 'rechazado'
            flash(f"Pago de {pago.usuario.first_name} rechazado.", "warning")
        
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f"Error al validar: {str(e)}", "danger")
        
    return redirect(url_for('dashboard_admin'))

@app.route("/admin/registrar-pago-manual/<int:user_id>", methods=['POST'])
@login_required
def registrar_pago_admin(user_id):
    """Pago manual directo (efectivo, etc.) realizado por el admin"""
    if not current_user.es_admin:
        return jsonify({"error": "No autorizado"}), 403
    
    try:
        monto = float(request.form.get('monto'))
        cliente = db.session.get(User, user_id)
        
        if cliente:
            for pedido in cliente.pedidos:
                if monto <= 0: break
                pendiente = pedido.total_a_pagar - pedido.monto_pagado
                if pendiente > 0:
                    pago_aplicado = min(monto, pendiente)
                    pedido.monto_pagado += pago_aplicado
                    monto -= pago_aplicado
            
            db.session.commit()
            flash('Pago manual procesado correctamente.', 'success')
        else:
            flash('Cliente no encontrado.', 'warning')
            
    except Exception as e:
        db.session.rollback()
        flash(f'Error al procesar pago: {str(e)}', 'danger')
        
    return redirect(url_for('dashboard_admin'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)