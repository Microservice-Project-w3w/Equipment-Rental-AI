from datetime import datetime, timedelta, timezone

import jwt

from app.services.permission_service import PermissionService


def test_extracts_real_identity_claim_shape():
    token = jwt.encode(
        {
            "sub": "10",
            "userId": 10,
            "roles": ["MANAGER"],
            "permissions": [
                "rental.quotation.read",
                "rental.quotation.approve",
            ],
            "organizationId": 1,
            "branchIds": [2, 3],
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        "test-secret-with-at-least-32-bytes-long",
        algorithm="HS256",
    )

    context = PermissionService.extract_user_context(token)

    assert context.user_id == 10
    assert context.roles == ("MANAGER",)
    assert context.organization_id == 1
    assert context.branch_ids == (2, 3)
    assert PermissionService.can_access_tool(
        context,
        "get_pending_quotations",
    )
    assert not PermissionService.can_access_tool(context, "get_customer_info")
