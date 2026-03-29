# set_admin.py
from app import app, db, User

def convertir_a_admin(telefono):
    with app.app_context():
        # Buscamos al usuario por el campo 'username' (que es el teléfono)
        user = User.query.filter_by(username=telefono).first()
        
        if user:
            user.es_admin = True
            db.session.commit()
            print(f"✅ ¡Éxito! {user.first_name} {user.last_name} ahora es Administrador.")
            print(f"Ahora puedes loguearte con el teléfono {telefono} para ver el Panel de Admin.")
        else:
            print(f"❌ Error: No se encontró ningún usuario con el teléfono {telefono}.")

if __name__ == '__main__':
    tel = input("Ingresa el número de teléfono del usuario para hacerlo ADMIN: ")
    convertir_a_admin(tel)