import logging
import socket
import sys
import uuid

import requests
import urllib3
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from src import config

logger = logging.getLogger(__name__)


def fail(message):
    """Logs the error and ends agent-cli with exit code 1."""
    logger.error(message)
    sys.exit(1)


def download_server_ca(server_url):
    """Downloads the server CA certificate, returns it as PEM bytes."""
    # verify=False schválně: důvěra nejde z TLS, ale z kontroly otisku hned potom
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    try:
        response = requests.get(f"{server_url}/api/server_ca.pem", verify=False, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException:
        fail(f"Can't reach the server at {server_url}. Check the address and that port 8443 is open.")
    return response.content


def check_fingerprint(certificate, cert_hash):
    """Ends agent-cli unless the CA's fingerprint matches --cert-hash or the user confirms it."""
    # otisk z certifikátu v DER, ne z bajtů .pem souboru, stejně jako v dashboardu
    fingerprint = certificate.fingerprint(hashes.SHA256()).hex()

    if cert_hash:
        expected = cert_hash.replace(" ", "").lower()
        if expected.startswith("sha256:"):
            expected = expected[len("sha256:"):]
        if expected != fingerprint:
            fail(
                "The server's certificate doesn't match --cert-hash. Don't enroll: check the "
                "address, or copy the command from the dashboard again."
            )
        return

    # bez --cert-hash otisk ukáže po čtveřicích jako dashboard a zeptá se
    upper = fingerprint.upper()
    groups = []
    for i in range(0, len(upper), 4):
        groups.append(upper[i:i + 4])
    print("The server's certificate fingerprint:")
    print(" ".join(groups))
    answer = input("Does this match the fingerprint in the dashboard? [y/N] ")
    if answer.strip().lower() != "y":
        fail("Not enrolled.")


def load_or_make_key_and_id():
    """Returns the machine's key and agent_id, the existing ones or new ones."""
    # odebraný stroj se zapíše znova se stejným klíčem a ID, takže jeho historie pokračuje
    cfg = config.load()
    if config.KEY_FILE.exists() and cfg.get("agent_id"):
        with open(config.KEY_FILE, "rb") as f:
            key = serialization.load_pem_private_key(f.read(), password=None)
        return key, cfg["agent_id"]
    return ec.generate_private_key(ec.SECP256R1()), str(uuid.uuid4())


def make_csr(key, agent_id):
    """Returns a certificate request (PEM text) with agent_id as its name."""
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, agent_id)]))
        .sign(key, hashes.SHA256())
    )
    return csr.public_bytes(serialization.Encoding.PEM).decode("ascii")


def enroll(server_url, code, cert_hash):
    """Enrolls this machine on the server with an enrollment code."""
    if not server_url.startswith("https://"):
        fail("The server address must start with https://")
    server_url = server_url.rstrip("/")

    ca_pem = download_server_ca(server_url)
    certificate = x509.load_pem_x509_certificate(ca_pem)
    check_fingerprint(certificate, cert_hash)
    # ověřená CA serveru, nevadí, když se pak enroll nepovede. Ukládá se jen ten jeden
    # zkontrolovaný certifikát, ne stažené bajty: útočník by za něj mohl připsat svou CA
    # a verify=ca.pem by pak věřilo oběma
    config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.CA_FILE, "wb") as f:
        f.write(certificate.public_bytes(serialization.Encoding.PEM))

    key, agent_id = load_or_make_key_and_id()
    # klíč a ID se uloží ještě před žádostí: když server stroj zapíše, ale odpověď se ztratí,
    # další pokus pošle stejný klíč a ID, server to bere jako opakování a kód znova nepoužije
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    with open(config.KEY_FILE, "wb") as f:
        f.write(key_pem)
    cfg = config.load()
    cfg["agent_id"] = agent_id
    config.save(cfg)

    hostname = socket.gethostname()
    payload = {"code": code, "csr_pem": make_csr(key, agent_id), "hostname": hostname}
    try:
        response = requests.post(
            f"{server_url}/api/enroll", json=payload, verify=str(config.CA_FILE), timeout=30
        )
    except requests.exceptions.SSLError:
        fail(
            "The server's certificate isn't valid for this address. Check that it matches "
            "the address in the dashboard."
        )
    except requests.exceptions.RequestException:
        fail(f"Can't reach the server at {server_url}. Check the address and that port 8443 is open.")

    if response.status_code != 200:
        # backend už v detail píše, co je špatně (kód, platnost, jiný klíč)
        try:
            fail(response.json()["detail"])
        except (ValueError, KeyError):
            fail(f"Enrollment failed: {response.status_code} {response.text}")

    with open(config.CERTIFICATE_FILE, "w") as f:
        f.write(response.json()["certificate_pem"])
    cfg["server_url"] = server_url
    config.save(cfg)

    logger.info(
        "Enrolled as %s (%s). The first check-in comes within an hour, or now: "
        "schtasks /run /tn MonitoringAgent",
        hostname,
        agent_id,
    )
