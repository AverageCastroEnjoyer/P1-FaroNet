# RFC-FARO-PHY-001: enlace óptico Faro
- Estado: borrador inicial
- Versión del protocolo: 1
- Implementación prevista: Python en Raspberry Pi
- Límite: una trama transmitida ocupa como máximo 128 bytes antes de codificarla en símbolos Manchester.


## 1. Objetivo
Definir el enlace entre dos Faros usando luz como medio físico. Este documento fija el formato de trama, la codificación de línea, el control básico de acceso al medio y las métricas que reporta la implementación.

La comunicación entre el computador y un Faro usa USB/serial o la interfaz disponible en el equipo. Ese transporte no altera el formato de trama Faro.


## 2. Parámetros físicos
- Transmisión: OOK (On-Off Keying).
- Codificación de línea: Manchester.
- Faro en reposo: emisor apagado.
- Manchester: bit `0` se representa como emisor encendido durante la primera mitad del bit y apagado durante la segunda; bit `1` se representa al contrario.
- El emisor usa el LED del circuito y el receptor la salida acondicionada del fototransistor.
- La frecuencia de símbolo debe poder configurarse. Se medirá en el circuito final; no se asumirá que el GPIO desde espacio de usuario mantiene temporización precisa.
- Las pruebas se ejecutan con luz ambiental normal y en, al menos, tres distancias documentadas.

La implementación debe mantener el manejo de GPIO detrás de una interfaz para poder probar el protocolo sin hardware real y cambiar la biblioteca de GPIO sin alterar el framing.


## 3. Formato de trama
Todos los enteros multibyte se serializan en orden de red (big-endian). El CRC se transmite primero con el byte más significativo.

| Campo | Tamaño | Descripción |
|---|---:|---|
| Preamble | 2 bytes | `AA AA`, permite adquirir sincronización |
| SFD | 1 byte | `D5`, marca el comienzo del encabezado |
| Version | 1 byte | Versión del formato de trama; inicialmente `1` |
| Type | 1 byte | Tipo de trama |
| Source address | 8 bytes | Dirección física rotatoria del transmisor |
| Destination address | 8 bytes | Dirección física del destinatario o broadcast |
| Sequence | 2 bytes | Número de secuencia, módulo 65536 |
| Payload length | 1 byte | Longitud de `Payload`, de 0 a 102 bytes |
| Payload | 0–102 bytes | Datos de control o datos de red |
| CRC | 2 bytes | CRC-16/CCITT-FALSE de Version hasta el último byte de Payload |

La trama completa, incluidos Preamble, SFD y CRC, no puede exceder 128 bytes antes de Manchester. Por lo tanto, el payload máximo es 102 bytes.

El CRC usa polinomio `0x1021`, valor inicial `0xFFFF` y XOR de salida `0x0000`. El CRC detecta errores accidentales del enlace; no autentica al emisor ni sustituye el cifrado autenticado de la capa de privacidad.

### Tipos iniciales
| Valor | Nombre | Uso |
|---:|---|---|
| `0x01` | DATA | Transporte de datos |
| `0x02` | ACK | Confirmación de una trama recibida |
| `0x03` | BEACON | Anuncio de presencia y capacidades del nodo |
| `0x04` | CONTROL | Control del enlace |

Los valores no definidos se rechazan. Una trama con versión desconocida, tamaño inválido, dirección inválida o CRC incorrecto se descarta sin entregar su payload a capas superiores.


## 4. Direcciones físicas
Cada Faro usa una dirección aleatoria de 8 bytes, distinta de una dirección MAC de fabricante. Se crea con un generador criptográficamente seguro y se conserva en almacenamiento no volátil.

La dirección debe poder rotarse. La política inicial rota la dirección al reiniciar, cada 10 minutos y cuando se activa el botón de pánico. La aplicación no debe escribir esta dirección en registros. La rotación no reemplaza las claves de identidad que se usan para firmar entradas del directorio.

Las direcciones de enlace identifican solo los extremos del enlace actual. No se copian como identificadores persistentes dentro de mensajes de la aplicación.


## 5. Acceso al medio y reintentos
El enlace es half-duplex:
1. Antes de transmitir, el Faro escucha el receptor durante el intervalo de detección de portadora configurado.
2. Si detecta actividad, espera un retardo aleatorio (backoff) en ranuras configurables y vuelve a escuchar.
3. Si el medio está libre, transmite la trama completa.
4. El receptor responde con ACK que incluye el número de secuencia recibido.
5. Si no llega el ACK dentro del timeout configurado, el emisor reintenta con backoff exponencial.
6. Después de cinco intentos sin ACK, la trama se reporta como fallida a la capa superior.

Los intervalos de portadora, ranura y ACK se guardan como parámetros configurables y se ajustan midiendo el circuito real. El driver no debe ocultar pérdidas ni convertirlas en entregas exitosas.


## 6. Interfaz entre módulos
La capa de enlace define un objeto de trama con estos campos:
Frame(version, type, source, destination, sequence, payload)