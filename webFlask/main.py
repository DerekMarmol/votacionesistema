from flask import Flask, render_template, request, jsonify, Response, session
import cv2
import face_recognition
import numpy as np
import requests
from io import BytesIO
import pandas as pd
import secrets
import logging
from collections import Counter
from flask_socketio import SocketIO, emit
import os

static_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')

logging.basicConfig(level=logging.INFO)

app = Flask(__name__, static_folder=static_folder)
app.static_folder = 'static'
socketio = SocketIO(app)

# Lista de imágenes de referencia y sus codificaciones
url_imagenes_google_drive = [
    'https://drive.google.com/uc?export=download&id=1ad6T_AlcyUmax_Qlw8ifvEOEARMJup-_',
    'https://drive.google.com/uc?export=download&id=1SCxK7xp-MaI2lCW2AcQaR2JDfi0npeyz',
    'https://drive.google.com/uc?export=download&id=1TF89ZanVI79Vk8QCromAwEZBKxqwHhjw'
]
codificaciones_existente = []

for url_imagen in url_imagenes_google_drive:
    respuesta = requests.get(url_imagen)
    imagen_existente = face_recognition.load_image_file(BytesIO(respuesta.content))
    codificacion_existente = face_recognition.face_encodings(imagen_existente)[0]
    codificaciones_existente.append(codificacion_existente)

face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

@app.before_request
def log_request_info():
    app.logger.info('Headers: %s', request.headers)
    app.logger.info('Body: %s', request.get_data())

@app.route('/')
def index():
    # Convertir la columna es_admin a tipo bool para evitar problemas de serialización JSON
    usuarios_df['es_admin'] = usuarios_df['es_admin'].astype(bool)
    return render_template('index.html', es_admin=session.get('es_admin', False))


usuarios_df = pd.read_excel('base.xlsx')

# Calcular y agregar las codificaciones de las imágenes de los usuarios
codificaciones_usuarios = []
for enlace_drive in usuarios_df['enlace_de_drive']:
    respuesta = requests.get(enlace_drive)
    imagen_usuario = face_recognition.load_image_file(BytesIO(respuesta.content))
    codificacion_usuario = face_recognition.face_encodings(imagen_usuario)[0]
    codificaciones_usuarios.append(codificacion_usuario)

usuarios_df['codificacion'] = codificaciones_usuarios

def generar_token():
    return secrets.token_hex(16)  # Genera un token hexadecimal de 16 bytes

app.secret_key = '1309RTA2005'

@app.route('/login', methods=['POST'])
def login():
    if request.method == 'POST':
        imagen_enviada = request.files['imagen']
        email = request.form['email']
        password = request.form['password']
        
        # Verificar reconocimiento facial
        imagen_enviada = face_recognition.load_image_file(imagen_enviada)
        codificaciones_enviadas = face_recognition.face_encodings(imagen_enviada)

        if not codificaciones_enviadas:
            return jsonify({'resultado': 'No se detectó rostro'})

        # Verificar correo electrónico y contraseña
        usuario = usuarios_df[(usuarios_df['correo'] == email) & (usuarios_df['contraseña'] == password)]
        if usuario.empty:
            return jsonify({'resultado': 'Correo o contraseña incorrectos'})

        # Verificar si el usuario es administrador
        es_admin = usuario.iloc[0]['es_admin']  # Asume que 'es_admin' es una columna booleana en tu Excel
        session['es_admin'] = bool(es_admin)  # Solución aplicada aquí

        # Almacenar el nombre del usuario en la sesión
        session['nombre'] = usuario.iloc[0]['nombre']

        for enlace_drive in usuario['enlace_de_drive']:
            respuesta = requests.get(enlace_drive)
            imagen_usuario = face_recognition.load_image_file(BytesIO(respuesta.content))
            codificacion_usuario = face_recognition.face_encodings(imagen_usuario)[0]
            results = face_recognition.compare_faces(codificaciones_enviadas, codificacion_usuario)
            if True in results:
                token = secrets.token_hex(16)
                session['correo'] = email
                session['token'] = token
                usuarios_df.at[usuario.index[0], 'token'] = token
                usuarios_df.to_excel('base.xlsx', index=False)
                return jsonify({'resultado': 'Coincide', 'token': token, 'enlace_de_drive': enlace_drive})
        else:
            return jsonify({'resultado': 'No coincide'})

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

def generate_frames():
    cap = cv2.VideoCapture(0)
    while True:
        success, frame = cap.read()
        if not success:
            break
        else:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.1, 4)
            for (x, y, w, h) in faces:
                cv2.rectangle(frame, (x, y), (x+w, y+h), (255, 0, 0), 2)
                face_detected = frame[y:y+h, x:x+w]
                face_detected_rgb = cv2.cvtColor(face_detected, cv2.COLOR_BGR2RGB)
                face_encodings = face_recognition.face_encodings(face_detected_rgb)
                if face_encodings:
                    for codificacion_existente in codificaciones_existente:
                        results = face_recognition.compare_faces([codificacion_existente], face_encodings[0])
                        if results[0]:
                            cv2.putText(frame, "Coincide", (x, y), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2, cv2.LINE_AA)
                            break
                    else:
                        cv2.putText(frame, "No coincide", (x, y), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2, cv2.LINE_AA)
            ret, buffer = cv2.imencode('.jpg', frame)
            frame = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@socketio.on('connect')
def handle_connect():
    print('Cliente conectado')

if __name__ == '__main__':
    socketio.run(app, debug=True)
