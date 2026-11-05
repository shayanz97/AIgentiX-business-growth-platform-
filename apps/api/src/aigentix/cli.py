"""Operational commands: `python -m aigentix.cli <command>`.

create-user   Create a user (password read from --password or the AIGENTIX_PASSWORD env var)
seed-dev      Create two demo tenants for local development and E2E tests (development/test only)
"""

import argparse
import getpass
import os
import sys

from sqlalchemy.orm import Session

from aigentix.core.config import get_settings
from aigentix.core.db import get_session_factory
from aigentix.platform.identity import service as identity
from aigentix.platform.identity.models import User
from aigentix.platform.organizations import service as orgs
from aigentix.platform.organizations.models import Role

DEMO_TENANTS = (
    ("owner@acme.example", "Acme Robotics", "Ada Owner"),
    ("owner@globex.example", "Globex Analytics", "Grace Owner"),
)
DEMO_MEMBER = "member@acme.example"


def _password(args: argparse.Namespace) -> str:
    password = args.password or os.environ.get("AIGENTIX_PASSWORD")
    if not password:
        password = getpass.getpass("Password: ")
    return str(password)


def _get_or_create_user(db: Session, email: str, password: str, full_name: str) -> tuple[User, bool]:
    existing = identity.get_user_by_email(db, email)
    if existing:
        return existing, False
    return identity.create_user(db, email=email, password=password, full_name=full_name), True


def cmd_create_user(args: argparse.Namespace) -> None:
    with get_session_factory()() as db:
        user = identity.create_user(db, email=args.email, password=_password(args), full_name=args.name or "")
        if args.organization:
            orgs.create_organization(db, name=args.organization, owner=user)
        db.commit()
        print(f"Created user {user.email}")


def cmd_seed_dev(args: argparse.Namespace) -> None:
    if get_settings().environment == "production":
        sys.exit("seed-dev is disabled in production")
    password = _password(args)
    with get_session_factory()() as db:
        acme_org = None
        for email, org_name, full_name in DEMO_TENANTS:
            user, created = _get_or_create_user(db, email, password, full_name)
            if created:
                membership = orgs.create_organization(db, name=org_name, owner=user)
                if acme_org is None:
                    acme_org = membership.organization
            print(f"{'Created' if created else 'Exists '} {email}")
        member, created = _get_or_create_user(db, DEMO_MEMBER, password, "Max Member")
        if created and acme_org is not None:
            orgs.add_member(db, organization=acme_org, user=member, role=Role.MEMBER)
        print(f"{'Created' if created else 'Exists '} {DEMO_MEMBER}")
        db.commit()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="aigentix.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p_user = sub.add_parser("create-user")
    p_user.add_argument("--email", required=True)
    p_user.add_argument("--name")
    p_user.add_argument("--password")
    p_user.add_argument("--organization", help="Also create this organization with the user as owner")
    p_user.set_defaults(func=cmd_create_user)

    p_seed = sub.add_parser("seed-dev")
    p_seed.add_argument("--password")
    p_seed.set_defaults(func=cmd_seed_dev)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
