"""Demostración manual del framing usando el backend loopback."""

from faro.link.frame import Frame, FrameType
from faro.link.transceiver import OpticalLink
from faro.physical.loopback import create_loopback_pair


def main() -> None:
    left_backend, right_backend = create_loopback_pair()
    sender = OpticalLink(left_backend)
    receiver = OpticalLink(right_backend)

    message = Frame(
        kind=FrameType.DATA,
        source=b"\x01" * 8,
        destination=b"\x02" * 8,
        sequence=1,
        payload=b"FaroNet",
    )

    sender.send_frame(message)
    received = receiver.receive_frame(timeout_seconds=1.0)

    if received is None:
        raise RuntimeError("no se recibió ninguna trama")

    print(f"Tipo: {received.kind.name}")
    print(f"Secuencia: {received.sequence}")
    print(f"Payload: {received.payload!r}")


if __name__ == "__main__":
    main()