import os
import socket

import pytest

from tests.conftest import CREDENTIAL_VARIABLES


def test_network_connections_are_refused():
    with pytest.raises(RuntimeError, match="network"):
        socket.create_connection(("192.0.2.1", 80), timeout=0.1)
    with socket.socket() as sock, pytest.raises(RuntimeError, match="network"):
        sock.connect(("192.0.2.1", 80))


def test_credentials_are_absent():
    assert not [name for name in CREDENTIAL_VARIABLES if name in os.environ]
