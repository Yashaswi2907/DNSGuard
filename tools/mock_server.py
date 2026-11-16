"""
Development / screenshot server that uses the MOCKED DNS transport from the
test suite. It exists only because the build sandbox blocked outbound DNS.
Never use it for real measurements: run `python app.py` instead.

    python -m tools.mock_server  [port]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app  # noqa: E402
from config import Config  # noqa: E402
from dns_engine import DNSQueryEngine  # noqa: E402
from tests.mock_dns import CLOUDFLARE, GOOGLE, MockDNS  # noqa: E402

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5055
    db = sys.argv[2] if len(sys.argv) > 2 else str(Path("instance/mock-demo.db").resolve())
    mock = MockDNS(latency={GOOGLE: (18, 4), CLOUDFLARE: (13, 3)})
    app = create_app(Config, engine=DNSQueryEngine(udp=mock.udp, tcp=mock.tcp), DATABASE=db,
                     RATE_LIMIT_ENABLED=False)
    print(f"MOCKED DNS dev server on http://127.0.0.1:{port}  (db: {db})")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
