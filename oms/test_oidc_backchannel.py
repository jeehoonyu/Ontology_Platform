"""OIDC public issuer and private back-channel routing contract."""
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'oidc_backchannel.db')}"
os.environ["APP_ENV"] = "production"
os.environ["AUTH_MODE"] = "oidc"
os.environ["OIDC_ISSUER"] = "https://identity.example.test/realms/ontology"
os.environ["OIDC_CLIENT_ID"] = "ontology-platform"
os.environ["OIDC_BACKCHANNEL_BASE_URL"] = "http://keycloak:8080"

from app import production_auth  # noqa: E402

production_auth.validate_auth_configuration()

public_token = "https://identity.example.test/realms/ontology/protocol/openid-connect/token?mode=pkce"
private_token = production_auth._backchannel_url(public_token)
assert private_token == "http://keycloak:8080/realms/ontology/protocol/openid-connect/token?mode=pkce"
assert production_auth._backchannel_url("https://identity.example.test/realms/ontology/protocol/openid-connect/certs") == (
    "http://keycloak:8080/realms/ontology/protocol/openid-connect/certs"
)

os.environ.pop("OIDC_BACKCHANNEL_BASE_URL")
assert production_auth._backchannel_url(public_token) == public_token

os.environ["OIDC_BACKCHANNEL_BASE_URL"] = "http://user:password@keycloak:8080"
try:
    production_auth.validate_auth_configuration()
    raise AssertionError("OIDC back-channel URL credentials were accepted")
except RuntimeError as exc:
    assert "without credentials" in str(exc)

print("OIDC back-channel verified: public issuer validation is preserved while server traffic uses a private service URL.")
