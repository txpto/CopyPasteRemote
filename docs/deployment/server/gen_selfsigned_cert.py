#!/usr/bin/env python3
"""Generate a self-signed TLS certificate (cert.pem + key.pem) for CopyPasteRemote.

Usage:
    python gen_selfsigned_cert.py <out_dir> <host1> [host2 ...]

Each host may be an IP (added as an IP SAN) or a DNS name. Example:
    python gen_selfsigned_cert.py C:\\CopyPasteRemote\\certs <PUBLIC_IP_OR_DOMAIN> 127.0.0.1 localhost
"""
import datetime
import ipaddress
import os
import sys

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    out_dir = sys.argv[1]
    hosts = sys.argv[2:]
    os.makedirs(out_dir, exist_ok=True)

    sans = []
    cn = hosts[0]
    for h in hosts:
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(h)))
        except ValueError:
            sans.append(x509.DNSName(h))

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.datetime.utcnow()
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([x509.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .sign(key, hashes.SHA256())
    )

    key_path = os.path.join(out_dir, "key.pem")
    cert_path = os.path.join(out_dir, "cert.pem")
    with open(key_path, "wb") as fh:
        fh.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ))
    with open(cert_path, "wb") as fh:
        fh.write(cert.public_bytes(serialization.Encoding.PEM))
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass

    print("Certificate written:")
    print("  cert: %s" % cert_path)
    print("  key : %s" % key_path)
    print("  SAN : %s" % ", ".join(hosts))
    print("\nCopy cert.pem to the clients (ca_cert) for TLS verification.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
