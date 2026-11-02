"""Formato y validación de las tramas ópticas Faro."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


PREAMBLE = b"\xAA\xAA"
START_DELIMITER = 0xD5
PROTOCOL_VERSION = 1

MAX_FRAME_SIZE = 128
ADDRESS_SIZE = 8

# Campos desde Version hasta Payload Length:
# Version(1) + Type(1) + Source(8) + Destination(8) + Sequence(2)
# + Payload Length(1) = 21 bytes.
HEADER_SIZE = 21
CRC_SIZE = 2
FIXED_FRAME_SIZE = len(PREAMBLE) + 1 + HEADER_SIZE + CRC_SIZE
MAX_PAYLOAD_SIZE = MAX_FRAME_SIZE - FIXED_FRAME_SIZE

BROADCAST_ADDRESS = b"\xFF" * ADDRESS_SIZE


class FrameError(ValueError):
    """La trama está mal formada o no cumple el protocolo."""


class FrameType(IntEnum):
    DATA = 0x01
    ACK = 0x02
    BEACON = 0x03
    CONTROL = 0x04


@dataclass(frozen=True, slots=True)
class Frame:
    """Trama Faro antes de serializarse."""

    kind: FrameType
    source: bytes
    destination: bytes
    sequence: int
    payload: bytes
    version: int = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        try:
            normalized_kind = FrameType(self.kind)
        except (TypeError, ValueError) as exc:
            raise FrameError(f"Tipo de trama inválido: {self.kind!r}") from exc

        object.__setattr__(self, "kind", normalized_kind)

        if not isinstance(self.source, bytes) or len(self.source) != ADDRESS_SIZE:
            raise FrameError(f"source debe ser exactamente {ADDRESS_SIZE} bytes")
        if (
            not isinstance(self.destination, bytes)
            or len(self.destination) != ADDRESS_SIZE
        ):
            raise FrameError(
                f"destination debe ser exactamente {ADDRESS_SIZE} bytes"
            )
        if not isinstance(self.payload, bytes):
            raise FrameError("payload debe ser bytes")
        if len(self.payload) > MAX_PAYLOAD_SIZE:
            raise FrameError(
                f"payload excede el máximo de {MAX_PAYLOAD_SIZE} bytes"
            )
        if not 0 <= self.sequence <= 0xFFFF:
            raise FrameError("sequence debe estar entre 0 y 65535")
        if not 0 <= self.version <= 0xFF:
            raise FrameError("version debe estar entre 0 y 255")


def crc16_ccitt_false(data: bytes) -> int:
    """Calcula CRC-16/CCITT-FALSE: poly=0x1021, init=0xFFFF, xorout=0."""
    crc = 0xFFFF

    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF

    return crc


def encode_frame(frame: Frame) -> bytes:
    """Serializa una trama y agrega su CRC."""

    body = (
        bytes((frame.version, int(frame.kind)))
        + frame.source
        + frame.destination
        + frame.sequence.to_bytes(2, byteorder="big")
        + bytes((len(frame.payload),))
        + frame.payload
    )

    checksum = crc16_ccitt_false(body).to_bytes(2, byteorder="big")
    raw = PREAMBLE + bytes((START_DELIMITER,)) + body + checksum

    if len(raw) > MAX_FRAME_SIZE:
        # La validación de Frame ya evita este caso; queda como defensa adicional.
        raise FrameError(f"trama excede {MAX_FRAME_SIZE} bytes")

    return raw


def decode_frame(raw: bytes) -> Frame:
    """Valida una trama recibida y la convierte en Frame."""

    if not isinstance(raw, bytes):
        raise FrameError("la trama recibida debe ser bytes")
    if len(raw) < FIXED_FRAME_SIZE:
        raise FrameError("trama demasiado corta")
    if len(raw) > MAX_FRAME_SIZE:
        raise FrameError(f"trama excede {MAX_FRAME_SIZE} bytes")
    if raw[:2] != PREAMBLE:
        raise FrameError("preamble inválido")
    if raw[2] != START_DELIMITER:
        raise FrameError("delimitador de inicio inválido")

    version = raw[3]
    if version != PROTOCOL_VERSION:
        raise FrameError(f"versión de protocolo no admitida: {version}")

    try:
        kind = FrameType(raw[4])
    except ValueError as exc:
        raise FrameError(f"tipo de trama desconocido: 0x{raw[4]:02X}") from exc

    source_start = 5
    source_end = source_start + ADDRESS_SIZE
    destination_end = source_end + ADDRESS_SIZE

    source = raw[source_start:source_end]
    destination = raw[source_end:destination_end]
    sequence = int.from_bytes(raw[destination_end : destination_end + 2], "big")
    payload_length = raw[destination_end + 2]

    if payload_length > MAX_PAYLOAD_SIZE:
        raise FrameError("longitud de payload excede el máximo")

    expected_length = FIXED_FRAME_SIZE + payload_length
    if len(raw) != expected_length:
        raise FrameError(
            f"longitud incorrecta: se esperaban {expected_length} bytes "
            f"y llegaron {len(raw)}"
        )

    payload_start = destination_end + 3
    payload_end = payload_start + payload_length
    payload = raw[payload_start:payload_end]

    received_crc = int.from_bytes(raw[payload_end : payload_end + CRC_SIZE], "big")
    calculated_crc = crc16_ccitt_false(raw[3:payload_end])

    if received_crc != calculated_crc:
        raise FrameError(
            f"CRC inválido: recibido 0x{received_crc:04X}, "
            f"calculado 0x{calculated_crc:04X}"
        )

    return Frame(
        kind=kind,
        source=source,
        destination=destination,
        sequence=sequence,
        payload=payload,
        version=version,
    )