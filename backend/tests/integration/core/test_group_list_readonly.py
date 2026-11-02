"""Reading roles must not synchronize built-ins or acquire SQLite write locks."""

import json
from unittest.mock import patch

from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext

from apps.core.admin_api import group_list
from apps.core.initialization import SUPERADMIN_GROUP_NAME, ensure_superadmin_defaults


def test_group_list_does_not_initialize_principals_or_write_models():
    manager, _ = ensure_superadmin_defaults()
    request = RequestFactory().get("/api/groups/")
    request.user = manager
    with (
        patch("apps.core.admin_api.ensure_superadmin_defaults") as initialize_roles,
        patch("apps.core.initialization.ensure_guest_user") as initialize_guest,
        CaptureQueriesContext(connection) as queries,
    ):
        response = group_list(request)
    assert response.status_code == 200
    assert SUPERADMIN_GROUP_NAME in {
        item["name"] for item in json.loads(response.content)["items"]
    }
    initialize_roles.assert_not_called()
    initialize_guest.assert_not_called()
    write_statements = {
        "INSERT",
        "UPDATE",
        "DELETE",
        "REPLACE",
        "CREATE",
        "ALTER",
        "DROP",
    }
    assert not [
        item["sql"]
        for item in queries.captured_queries
        if item["sql"].lstrip().split(None, 1)[0].upper() in write_statements
    ]
