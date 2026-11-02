# RFC-FARONET-001: red FaroNet
- Estado: borrador inicial
- Versión: 1
- Transporte entre nodos: Faro óptico, Ethernet o Wi-Fi
- Transporte al edge: HTTPS/WSS
- Privacidad: requisito transversal


## 1. Objetivo
FaroNet permite que nodos conectados por distintos medios enruten mensajes hasta su destino, manteniendo el anonimato del origen frente a los nodos intermedios. Los mensajes privados solo se pueden descifrar en el destino.

Los servicios públicos del edge (salas públicas, feeds y directorio público) están separados del chat privado, que permanece dentro de FaroNet.


## 2. Nodos y directorio
Cada nodo tiene un par de claves de firma Ed25519. El directorio distribuye claves públicas y capacidades de conexión en entradas firmadas por el nodo que las publica.

Una entrada incluye como mínimo:

- clave pública de firma;
- capacidades y tipos de transporte admitidos;
- fecha de creación y vencimiento;
- firma Ed25519 sobre la representación canónica de los campos anteriores.

Los receptores verifican la firma y el vencimiento antes de aceptar la entrada. El directorio no publica nombres de usuario, direcciones IP, direcciones físicas del Faro ni información sobre mensajes. Los cambios de dirección física no cambian la clave pública del nodo.


## 3. Rutas y privacidad del origen
Los nodos construyen rutas dinámicas sobre los enlaces disponibles. Una ruta anónima contiene al menos tres saltos de retransmisión antes de llegar al destino.

Cada relay conoce el vecino del cual recibió una trama y el siguiente vecino al cual debe enviarla. El contenido de la instrucción de encaminamiento va protegido por capas criptográficas para que ningún relay vea a la vez el origen y el destino finales.

Cuando no existe una ruta de al menos tres saltos, los mensajes que requieren anonimato se encolan o se rechazan con un error visible. No se degradan silenciosamente a una ruta de un solo salto.

Las rutas deben poder reconstruirse si desaparece un nodo o un enlace. El encaminamiento no depende de una tabla central que conozca el origen real de todos los mensajes.


## 4. Mensajes y criptografía
Las claves de firma y cifrado se manejan con una biblioteca criptográfica reconocida basada en libsodium/PyNaCl. No se implementan primitivas criptográficas propias.

- El payload privado se cifra de extremo a extremo con cifrado autenticado.
- Cada salto de una ruta anónima añade una capa de encaminamiento protegida.
- El padding reduce la filtración del tamaño lógico del mensaje.
- Mensajes mayores que la carga útil de una trama se fragmentan y reensamblan en la capa de red.
- La capa de aplicación valida longitud, tipo y autenticidad antes de entregar el contenido.

El emisor, el destino y los relays rechazan mensajes incompletos, autenticación fallida, fragmentos duplicados fuera de la ventana admitida y mensajes vencidos.


## 5. Gateway
El gateway conecta la red FaroNet con el edge mediante HTTPS/WSS. Cada petición de control se autentica con una firma Ed25519 y una marca de tiempo. El gateway rechaza peticiones vencidas y nonces ya vistos durante su ventana de validez para limitar replay.

El gateway no registra direcciones físicas, IP de nodos, identificadores de usuario, claves ni payloads. Los nonces de protección contra replay se conservan solo temporalmente en memoria.


## 6. Interfaz pública del edge
Rutas lógicas iniciales:

| Ruta | Método | Función |
|---|---|---|
| `/v1/rooms/{room}` | WSS | Sala pública en tiempo real |
| `/v1/feeds/{topic}` | GET | Feed Atom/RSS de un tema público |
| `/v1/drops` | POST | Guardar un blob cifrado con vencimiento |
| `/v1/drops/{token}` | GET/DELETE | Recuperar o borrar un blob cifrado |
| `/v1/nodes` | GET | Leer la réplica pública del directorio firmado |

El edge trata como público todo mensaje enviado a salas o feeds públicos. No intenta descifrar blobs del buzón ni mensajes privados. Los blobs tienen tamaño fijo limitado por la configuración del servicio y vencimiento obligatorio.

Se aplica limitación de peticiones a conexiones y operaciones públicas. La política concreta se configura para la demo y se documenta como una mitigación de abuso; no se usa para tomar decisiones de autorización criptográfica.


## 7. Almacenamiento y retención
La propuesta inicial usa:

- Durable Objects para coordinar cada sala WebSocket;
- KV para la réplica del directorio y blobs cifrados del buzón;
- expiración obligatoria para las entradas del directorio y los blobs;
- cero persistencia de encabezados de usuario, cookies, tokens o mensajes privados.

El contenido del buzón debe ser ciphertext antes de salir del gateway. El token de recuperación es aleatorio y no deriva de una identidad.


## 8. Botón de pánico y borrado
Al activar el botón de pánico, el Faro:

1. elimina de memoria las claves privadas y el estado sensible de sesión;
2. borra la dirección física activa y genera una nueva;
3. cancela rutas y colas pendientes;
4. indica visualmente que el dispositivo quedó en estado de pánico.

El firmware no conserva copias de recuperación de las claves borradas. La generación de nuevas claves después del pánico requiere un proceso explícito de aprovisionamiento.


## 9. Errores
Los errores de autenticación, firma, vencimiento, ruta insuficiente y almacenamiento lleno se reportan con códigos genéricos. No incluyen claves, contenido, dirección física ni identificadores personales.

Los errores de protocolo se documentan en el RFC de cada capa y se mantienen distinguibles durante pruebas para depurar la implementación.