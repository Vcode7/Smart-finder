"""
Prepare backend/.env and workspace/.env for a secure setup (run by setup.bat).

- JWT_SECRET: generated when missing or still the public default, and copied to
  workspace/.env so the Next.js proxy can verify the backend's session cookie.
- ADMIN_PASSWORD: on a fresh install (no database yet) a default password is replaced
  by a random one, printed once. Existing installs keep their admin account; change the
  password from Settings > Account.

Secrets are never printed except the one-time generated admin password.
"""
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ENV = ROOT / "backend" / ".env"
WORKSPACE_ENV = ROOT / "workspace" / ".env"
PUBLIC_DEFAULT_SECRETS = {
    "",
    "smart-find-super-secret-jwt-key-change-in-production",
    "smart-find-dev-secret-change-in-production",
    "change-me-to-a-long-random-string",
}
DEFAULT_ADMIN_PASSWORDS = {"", "Admin@123456", "choose-a-strong-password"}
DEFAULT_SETUP_CODES = {"", "choose-a-setup-code"}


def read_value(text: str, key: str) -> str:
    m = re.search(rf"^{key}=(.*)$", text, flags=re.MULTILINE)
    return m.group(1).strip() if m else ""


def set_value(text: str, key: str, value: str) -> str:
    if re.search(rf"^{key}=", text, flags=re.MULTILINE):
        return re.sub(rf"^{key}=.*$", f"{key}={value}", text, flags=re.MULTILINE)
    return text.rstrip("\n") + f"\n{key}={value}\n"


def db_file(backend: str) -> Path:
    """The database configured by DB_PATH (relative paths are resolved against backend/)."""
    p = Path(read_value(backend, "DB_PATH") or "data/smartfind.db")
    return p if p.is_absolute() else ROOT / "backend" / p


def main() -> int:
    if not BACKEND_ENV.exists():
        print("[configure_env] backend/.env not found", file=sys.stderr)
        return 1
    backend = BACKEND_ENV.read_text(encoding="utf-8")
    workspace = WORKSPACE_ENV.read_text(encoding="utf-8") if WORKSPACE_ENV.exists() else ""

    secret = read_value(backend, "JWT_SECRET")
    if secret in PUBLIC_DEFAULT_SECRETS:
        secret = secrets.token_hex(48)
        backend = set_value(backend, "JWT_SECRET", secret)
        print("[configure_env] Generated a new random JWT_SECRET")
    if read_value(workspace, "JWT_SECRET") != secret:
        workspace = set_value(workspace, "JWT_SECRET", secret)
        print("[configure_env] Synchronized JWT_SECRET into workspace/.env")

    backend = set_value(backend, "HOST", "127.0.0.1")
    workspace = set_value(workspace, "BACKEND_URL", f"http://127.0.0.1:{read_value(backend, 'PORT') or '8000'}")

    if read_value(backend, "ADMIN_PASSWORD") in DEFAULT_ADMIN_PASSWORDS:
        if db_file(backend).exists():
            print("[configure_env] WARNING: the admin account uses the default password. "
                  "Change it from Settings > Account after signing in.")
        else:
            password = secrets.token_urlsafe(12)
            backend = set_value(backend, "ADMIN_PASSWORD", password)
            print(f"[configure_env] Admin password for {read_value(backend, 'ADMIN_EMAIL') or 'the admin account'}: "
                  f"{password}  (shown once; change it after signing in)")

    if read_value(backend, "ADMIN_SETUP_CODE") in DEFAULT_SETUP_CODES and not db_file(backend).exists():
        code = secrets.token_urlsafe(12)
        backend = set_value(backend, "ADMIN_SETUP_CODE", code)
        print(f"[configure_env] Admin setup code (lets you create an admin account from the sign-in page): "
              f"{code}  (shown once; it is stored in backend/.env)")

    BACKEND_ENV.write_text(backend, encoding="utf-8")
    WORKSPACE_ENV.write_text(workspace, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
