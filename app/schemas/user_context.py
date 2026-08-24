from dataclasses import dataclass


@dataclass(frozen=True)
class UserContext:
    user_id: int
    roles: tuple[str, ...]
    permissions: frozenset[str]
    organization_id: int | None
    branch_ids: tuple[int, ...]
    customer_id: int | None

    @property
    def is_admin(self) -> bool:
        return "ADMIN" in self.roles
