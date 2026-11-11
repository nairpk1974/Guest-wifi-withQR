"""Operator CLI.  docker compose exec backend python -m app.cli <command>

  create-superadmin <username> "<Full Name>"   create the first Super Administrator (prints temp password)
  reset-mfa <username>                          clear MFA for a locked-out administrator
"""
import secrets
import sys

from sqlalchemy import select

from .db import SessionLocal
from .models import AuditLog, Role, User
from .security import hash_password


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    db = SessionLocal()
    cmd = argv[1]
    if cmd == "create-superadmin" and len(argv) == 4:
        username = argv[2].lower()
        if db.scalar(select(User).where(User.username == username)):
            print("User already exists")
            return 1
        temp = "Tmp-" + secrets.token_urlsafe(12) + "9a"
        db.add(User(username=username, full_name=argv[3], role=Role.super_admin, password_hash=hash_password(temp),
                    must_change_password=True))
        db.add(AuditLog(action="user.created_cli", entity_type="user", details={"username": username}))
        db.commit()
        print(f"Created super admin '{username}'. Temporary password: {temp}")
        print("You will be asked to change it and enrol MFA at first sign-in.")
        return 0
    if cmd == "reset-mfa" and len(argv) == 3:
        u = db.scalar(select(User).where(User.username == argv[2].lower()))
        if not u:
            print("No such user")
            return 1
        u.mfa_enabled = False
        u.mfa_secret_enc = None
        db.add(AuditLog(action="user.mfa_reset_cli", entity_type="user", entity_id=str(u.id)))
        db.commit()
        print("MFA cleared; user must enrol again at next sign-in.")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
