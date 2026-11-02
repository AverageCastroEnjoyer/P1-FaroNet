# Modelo de amenazas FaroNet
- Estado: borrador inicial
- Revisión: actualizar cuando cambien protocolos, almacenamiento o despliegue


## 1. Activos que se protegen
- Contenido de mensajes privados.
- Claves privadas de firma y cifrado.
- Relación entre el origen y el destino de un mensaje.
- Direcciones físicas rotatorias del Faro.
- Mensajes cifrados pendientes de recuperación en el edge.
- Disponibilidad básica de la red y del botón de pánico.


## 2. Adversarios considerados

### Nodo malicioso de la mesh
Puede recibir, reenviar, retrasar, duplicar, descartar o modificar tramas que transitan por él. Puede intentar correlacionar mensajes entrantes y salientes.

### Observador del medio óptico
Puede observar emisiones de luz y sus tiempos, intentar inferir actividad y producir interferencia luminosa.

### Operador del gateway
Puede observar solicitudes que pasan por el gateway, tiempos de conexión y el estado de la red exterior. No debe poder leer mensajes privados ni obtener direcciones físicas estables de los Faros.

### Proveedor del edge
Puede observar conexiones y metadatos de acceso al servicio, además de los mensajes enviados explícitamente a funciones públicas. Los blobs del buzón y el tráfico privado deben llegar cifrados.

### Atacante con acceso temporal al dispositivo
Puede intentar leer la memoria o el almacenamiento accesible del Faro. El botón de pánico debe borrar el estado sensible que controla el software, pero el proyecto no afirma resistencia a extracción física avanzada del hardware.


## 3. Supuestos
- Las bibliotecas criptográficas y el sistema operativo no están comprometidos.
- Los nodos ejecutan la versión de protocolo documentada.
- Las claves privadas no se incluyen en el repositorio, logs, RFCs ni binarios de entrega.
- El reloj de los equipos tiene precisión suficiente para validar ventanas cortas de autenticación.
- La conectividad puede perder paquetes y nodos sin que esto indique por sí solo un ataque.


## 4. Mitigaciones requeridas
| Riesgo | Mitigación |
|---|---|
| Relay lee el mensaje privado | Cifrado autenticado de extremo a extremo |
| Relay asocia origen y destino | Onion routing de al menos tres saltos y direcciones por enlace |
| Nodo suplanta una entrada del directorio | Firma Ed25519 y vencimiento verificable |
| Replay de mensajes al gateway | Firma con marca temporal, nonce temporal y ventana de validez |
| Observador infiere tamaño de mensajes | Padding antes del envío |
| Seguimiento mediante dirección física estable | Dirección aleatoria rotatoria y no registrar su valor |
| Pérdida de información sensible al retirar Faro | Botón de pánico que borra claves y sesiones controladas por software |
| Abuso de endpoints públicos | Límite de peticiones, tamaños máximos y expiración obligatoria |
| Corrupción accidental de tramas ópticas | CRC en capa física y autenticación criptográfica en capa de privacidad |


## 5. Límites conocidos
- El tiempo, volumen y patrón de tráfico pueden filtrar información aunque el contenido esté cifrado y haya padding.
- El proveedor del edge puede observar metadatos de las conexiones que llegan a su servicio.
- Un extremo comprometido puede revelar el contenido que recibe o envía.
- El botón de pánico no borra copias que ya hayan sido observadas o guardadas por un adversario.
- El CRC no protege contra modificación maliciosa; la protección criptográfica se aplica en las capas superiores.
- El proyecto no promete anonimato frente a un adversario que controle simultáneamente todos los nodos de la ruta o correlacione globalmente el tráfico.

## 6. Revisión
Antes de integrar una funcionalidad nueva, se actualiza este archivo para identificar:
1. qué información puede observar cada participante;
2. qué información no debe conocer;
3. cómo se mantiene el anonimato del origen;
4. qué datos se retienen y durante cuánto tiempo;
5. cómo se prueban las mitigaciones.