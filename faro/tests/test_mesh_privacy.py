"""Pruebas de aceptación para mesh, padding y borrado de pánico."""

from dataclasses import replace

import pytest
from nacl.public import PrivateKey
from nacl.signing import SigningKey

from faro.link.mac import MediumAccess
from faro.mesh.directory import create_entry, verify_entry
from faro.mesh.fragmentation import (
    FRAGMENT_HEADER_SIZE,
    FragmentError,
    FragmentReassembler,
    fragment_message,
)
from faro.mesh.onion import OnionRelay
from faro.mesh.routing import RouteUnavailable, find_route
from faro.mesh.transport import (
    decrypt_private_message,
    make_private_message_frames,
    relay_private_packet,
)
from faro.privacy.panic import PanicController


def _reassemble(fragments: tuple[bytes, ...]) -> bytes:
    reassembler = FragmentReassembler()
    result = None
    for fragment in fragments:
        candidate = reassembler.add(fragment)
        if candidate is not None:
            result = candidate
    assert result is not None
    return result


def test_directory_signature_and_expiration() -> None:
    signing_key = SigningKey.generate()
    entry = create_entry(signing_key, ("faro", "wifi"), expires_at=2_000_000_000)

    assert verify_entry(entry, now=1_900_000_000)
    assert not verify_entry(replace(entry, signature=b"\x00" * 64), now=1_900_000_000)
    assert not verify_entry(replace(entry, expires_at=1_950_000_000), now=1_900_000_000)
    assert not verify_entry(entry, now=2_000_000_000)


def test_route_requires_three_relays_and_recomputes_from_topology() -> None:
    graph = {
        "src": ("r1",),
        "r1": ("r2",),
        "r2": ("r3",),
        "r3": ("dst",),
        "dst": (),
    }
    assert find_route(graph, "src", "dst", min_relays=3) == (
        "src", "r1", "r2", "r3", "dst"
    )

    changed_graph = {
        "src": ("r1",),
        "r1": ("r2",),
        "r2": ("dst",),
        "dst": (),
    }
    with pytest.raises(RouteUnavailable):
        find_route(changed_graph, "src", "dst", min_relays=3)


def test_fragment_reassembly_duplicate_inconsistency_and_clear() -> None:
    fragments = fragment_message(b"a" * 120, message_id=b"M" * 8)
    reassembler = FragmentReassembler()

    assert reassembler.add(fragments[0]) is None
    assert reassembler.add(fragments[0]) is None
    assert reassembler.add(fragments[1]) == b"a" * 120
    assert reassembler.buffered_bytes == 0

    reassembler.add(fragments[0])
    reassembler.clear()
    assert reassembler.buffered_bytes == 0

    malformed = bytearray(fragments[1])
    count_offset = 1 + 8 + 2
    malformed[count_offset : count_offset + 2] = (3).to_bytes(2, "big")
    with pytest.raises(FragmentError):
        reassembler.add(bytes(malformed))

    with pytest.raises(FragmentError):
        reassembler.add(b"\x01" + b"\x00" * (FRAGMENT_HEADER_SIZE - 2))


def test_private_message_has_fixed_frame_sizes_and_three_relay_path() -> None:
    private_keys = [PrivateKey.generate() for _ in range(3)]
    addresses = [bytes((value,)) * 8 for value in (1, 2, 3, 4, 5)]
    relays = (
        OnionRelay(bytes(private_keys[0].public_key), addresses[2]),
        OnionRelay(bytes(private_keys[1].public_key), addresses[3]),
        OnionRelay(bytes(private_keys[2].public_key), addresses[4]),
    )
    key = b"K" * 32

    frames_short = make_private_message_frames(
        b"hi", key, relays, addresses[0], addresses[1]
    )
    frames_long = make_private_message_frames(
        b"hello" * 70, key, relays, addresses[0], addresses[1]
    )

    assert len(frames_short) == len(frames_long)
    assert tuple(map(lambda frame: len(frame.payload), frames_short)) == tuple(
        map(lambda frame: len(frame.payload), frames_long)
    )

    packet = _reassemble(tuple(frame.payload for frame in frames_short))
    for private_key, relay_address, expected_next in zip(
        private_keys, addresses[1:4], addresses[2:5], strict=True
    ):
        next_address, outbound_frames = relay_private_packet(
            packet,
            bytes(private_key),
            relay_address,
        )
        assert next_address == expected_next
        packet = _reassemble(tuple(frame.payload for frame in outbound_frames))

    assert decrypt_private_message(packet, key) == b"hi"


def test_private_message_rejects_short_route_oversize_and_tampering() -> None:
    private_key = PrivateKey.generate()
    relay = OnionRelay(bytes(private_key.public_key), b"D" * 8)
    with pytest.raises(ValueError, match="3 relays"):
        make_private_message_frames(b"msg", b"K" * 32, (relay,), b"S" * 8, b"R" * 8)

    three_relays = (relay, relay, relay)
    with pytest.raises(ValueError, match="excede"):
        make_private_message_frames(
            b"x" * 471, b"K" * 32, three_relays, b"S" * 8, b"R" * 8
        )

    frames = make_private_message_frames(
        b"msg", b"K" * 32, three_relays, b"S" * 8, b"R" * 8
    )
    packet = _reassemble(tuple(frame.payload for frame in frames))
    with pytest.raises(Exception):
        relay_private_packet(packet, bytes(PrivateKey.generate()), b"R" * 8)


def test_panic_zeroizes_buffers_rotates_address_and_clears_pending_state() -> None:
    secret = bytearray(b"secret")
    address_updates: list[bytes] = []
    cleared: list[str] = []
    access = MediumAccess(object(), b"A" * 8)

    controller = PanicController(
        set_address=address_updates.append,
        cancel_pending=lambda: (access.clear_pending(), cleared.append("pending")),
        clear_sessions=lambda: cleared.append("sessions"),
        indicate_panic=lambda: cleared.append("indicator"),
    )
    controller.register_secret(secret)

    assert controller.panic()
    assert secret == b"\x00" * len(secret)
    assert len(address_updates) == 1 and len(address_updates[0]) == 8
    assert cleared == ["pending", "sessions", "indicator"]
    assert controller.triggered
    assert not controller.panic()