from flask import Flask, render_template, request, jsonify, session
import numpy as np
import pandas as pd
import secrets
import logging
from flask_socketio import SocketIO, emit
import os

static_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')

logging.basicConfig(level=logging.INFO)

app = Flask(__name__, static_folder=static_folder)
app.static_folder = 'static'
socketio = SocketIO(app)

def generar_token():
    return secrets.token_hex(16)  # Genera un token hexadecimal de 16 bytes

app.secret_key = '1309RTA2005'

@app.route('/')
def index():
    # Convertir la columna es_admin a tipo bool para evitar problemas de serialización JSON
    usuarios_df['es_admin'] = usuarios_df['es_admin'].astype(bool)
    return render_template('index.html', es_admin=session.get('es_admin', False))


usuarios_df = pd.read_excel('base.xlsx')

@app.route('/login', methods=['POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        # Verificar correo electrónico y contraseña
        usuario = usuarios_df[(usuarios_df['correo'] == email) & (usuarios_df['contraseña'] == password)]
        if usuario.empty:
            return jsonify({'resultado': 'Correo o contraseña incorrectos'})

        # Verificar si el usuario es administrador
        es_admin = usuario.iloc[0]['es_admin']  # Asume que 'es_admin' es una columna booleana en tu Excel
        session['es_admin'] = bool(es_admin)  # Solución aplicada aquí

        # Almacenar el nombre del usuario en la sesión
        session['nombre'] = usuario.iloc[0]['nombre']

        token = secrets.token_hex(16)
        session['correo'] = email
        session['token'] = token
        usuarios_df.at[usuario.index[0], 'token'] = token
        usuarios_df.to_excel('base.xlsx', index=False)
        return jsonify({'resultado': 'Coincide', 'token': token})

    return render_template('index.html', es_admin=session.get('es_admin', False))

@app.route('/asignar_rol_admin', methods=['POST'])
def asignar_rol_admin():
    if request.method == 'POST':
        email_usuario = request.form['email_usuario']

        # Buscar al usuario por su correo electrónico
        usuario = usuarios_df.loc[usuarios_df['correo'] == email_usuario]

        # Verificar si el usuario existe
        if usuario.empty:
            return jsonify({'resultado': 'Usuario no encontrado'})

        # Asignar rol de administrador al usuario
        usuarios_df.at[usuario.index[0], 'es_admin'] = True
        usuarios_df.to_excel('base.xlsx', index=False)

        return jsonify({'resultado': 'Rol de administrador asignado correctamente'})

    return jsonify({'resultado': 'Error en la solicitud'})

@app.route('/votacion')
def votacion():
    return render_template('votacion.html')

# Inicializar el contador de votos
votos = {str(i): 0 for i in range(1, 31)}

# Función para reiniciar los votos
def reiniciar_votos():
    global votos
    votos = {str(i): 0 for i in range(1, 31)}  # Inicializar votos para 30 grupos
    usuarios_df['voto'] = np.nan  # Reiniciar la columna 'voto' en el DataFrame

# Bandera para controlar si la votación está abierta o no
votacion_abierta = False

@app.route('/abrir_votacion', methods=['POST'])
def abrir_votacion():
    global votacion_abierta
    votacion_abierta = True
    reiniciar_votos()  # Reiniciar los votos antes de abrir una nueva votación
    
    # Obtener el recuento de votos y enviarlo como parte de la respuesta JSON
    recuento_votos = {grupo: votos[grupo] for grupo in votos}
    
    return jsonify({'resultado': 'Votación abierta', 'recuento_votos': recuento_votos})

logging.basicConfig(filename='app.log', filemode='w', format='%(name)s - %(levelname)s - %(message)s')

# Diccionario para rastrear qué usuarios han votado
usuarios_votaron = set()

@app.route('/votar', methods=['POST'])
def votar():
    # Obtener el grupo por el que se está votando desde la solicitud
    grupo_votado = int(request.get_json()['grupo'])

    # Obtener el correo del usuario actual
    correo_usuario = session.get('correo', None)

    # Verificar si el usuario está autenticado y tiene un correo electrónico válido
    if correo_usuario is None:
        return jsonify({'resultado': 'Usuario no autenticado'})

    # Verificar si el usuario ya ha votado antes
    if correo_usuario in usuarios_votaron:
        return jsonify({'resultado': 'Ya has votado anteriormente'})

    # Registrar que el usuario ha votado
    usuarios_votaron.add(correo_usuario)

    # Actualizar la columna voto en el archivo Excel para el usuario actual y el grupo votado
    usuarios_df.loc[usuarios_df['correo'] == correo_usuario, 'voto'] = grupo_votado
    usuarios_df.to_excel('base.xlsx', index=False)

    # Incrementar el conteo de votos para el grupo votado
    votos[str(grupo_votado)] += 1  # Convertir grupo_votado a una cadena aquí

    logging.info(f'Usuario {correo_usuario} votó por el grupo {grupo_votado}. Votos actuales: {votos}')

    # Emitir un mensaje WebSocket informando sobre el voto realizado
    socketio.emit('voto_registrado', {'usuario': correo_usuario, 'grupo_votado': grupo_votado})

    return jsonify({'resultado': 'Voto registrado correctamente'})

@app.route('/cerrar_votacion', methods=['POST'])
def cerrar_votacion():
    # Determinar el grupo ganador
    max_votos = max(votos.values())
    grupos_ganadores = [grupo for grupo, voto in votos.items() if voto == max_votos]
    
    # Si hay un solo grupo ganador, retornar ese grupo
    if len(grupos_ganadores) == 1:
        grupo_ganador = grupos_ganadores[0]
        resultado = f'Grupo ganador: {grupo_ganador}'
    else:
        resultado = f'Empate entre los grupos {", ".join(str(grupo) for grupo in grupos_ganadores)}'
    
    # Enviar el recuento de votos al cliente
    recuento_votos = {grupo: votos[grupo] for grupo in votos}
    
    return jsonify({'resultado': resultado, 'recuento_votos': recuento_votos})

@app.route('/reiniciar_votaciones', methods=['POST'])
def reiniciar_votaciones():
    global usuarios_votaron
    usuarios_votaron = set()  # Vaciar el conjunto de usuarios que han votado
    reiniciar_votos()  # Reiniciar también los votos de los grupos
    return jsonify({'resultado': 'Votaciones reiniciadas correctamente'})

@socketio.on('connect')
def handle_connect():
    print('Cliente conectado')

if __name__ == '__main__':
    socketio.run(app, debug=True)