"""Conversión entre bytes y símbolos Manchester."""

from __future__ import annotations

from collections.abc import Sequence


class ManchesterDecodeError(ValueError):
    """Señal Manchester inválida o incompleta."""


def encode_manchester(data: bytes) -> tuple[int, ...]:
    """Codifica bytes MSB-first.

    Convención:
      - bit 0 -> nivel alto, nivel bajo
      - bit 1 -> nivel bajo, nivel alto

    Cada elemento de la tupla representa un semiperíodo del símbolo.
    """

    symbols: list[int] = []

    for byte in data:
        for bit_position in range(7, -1, -1):
            bit = (byte >> bit_position) & 1
            if bit == 0:
                symbols.extend((1, 0))
            else:
                symbols.extend((0, 1))

    return tuple(symbols)


def decode_manchester(symbols: Sequence[int]) -> bytes:
    """Decodifica símbolos Manchester MSB-first a bytes."""

    if len(symbols) % 16 != 0:
        raise ManchesterDecodeError(
            "la cantidad de semiperíodos debe ser múltiplo de 16"
        )

    output = bytearray()

    for byte_offset in range(0, len(symbols), 16):
        value = 0
        byte_symbols = symbols[byte_offset : byte_offset + 16]

        for symbol_offset in range(0, 16, 2):
            first = byte_symbols[symbol_offset]
            second = byte_symbols[symbol_offset + 1]

            if first not in (0, 1) or second not in (0, 1):
                raise ManchesterDecodeError("los niveles deben ser 0 o 1")

            if (first, second) == (1, 0):
                bit = 0
            elif (first, second) == (0, 1):
                bit = 1
            else:
                raise ManchesterDecodeError(
                    "transición Manchester inválida en el centro del bit"
                )

            value = (value << 1) | bit

        output.append(value)

    return bytes(output)