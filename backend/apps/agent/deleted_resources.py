"""Read-only access to server-recorded deletion receipts in terminal history."""

from apps.catalog.models import DataResource
from apps.catalog.permissions import user_can_bypass_owner_only

TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}


def readable_receipt(receipt, user, policy, project_id, resource_id):
    if (
        type(resource_id) is not int
        or receipt.get("platformDeletion") is not True
        or receipt.get("status") != "deleted"
        or receipt.get("formerResourceId") != resource_id
        or receipt.get("projectTagId") != project_id
        or receipt.get("dataType") not in policy["dataTypes"]
        or DataResource._base_manager.filter(pk=resource_id).exists()
    ):
        return False
    return not receipt.get("ownerOnly") or (
        receipt.get("maintainerId") == user.id or user_can_bypass_owner_only(user)
    )


def historical_deletion(record, user, policy, resource_id):
    """A missing or inaccessible resource alone never authorizes old content."""
    if (
        record.status not in TERMINAL
        or record.owner_id != user.id
        or type(resource_id) is not int
        or DataResource._base_manager.filter(pk=resource_id).exists()
    ):
        return None
    state = getattr(record, "execution_state", None)
    if state is None:
        state = record.plan
    for receipt in state.get("deletedResources", []):
        if receipt.get("historyReadableByOwner") is not True or not readable_receipt(
            receipt, user, policy, record.project_tag_id, resource_id
        ):
            continue
        return receipt
    return None
