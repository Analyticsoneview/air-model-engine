import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.main import app, require_air_operator


class BrokerAccountOperatorAccessTests(unittest.TestCase):
    def test_regular_customer_is_not_an_operator(self):
        with patch.dict("os.environ", {"AIR_OPERATOR_CUSTOMER_IDS": "+919999999999"}):
            with self.assertRaises(HTTPException) as raised:
                require_air_operator("+918888888888")
        self.assertEqual(raised.exception.status_code, 403)

    def test_broker_account_mutation_routes_require_operator_dependency(self):
        protected_paths = {
            "/api/v1/customer/accounts",
            "/api/v1/customer/accounts/{broker}/{account_id}/credentials",
            "/api/v1/customer/accounts/{broker}/{account_id}",
            "/api/v1/operator/broker-accounts",
            "/api/v1/operator/broker-accounts/{customer_id}/{broker}/{account_id}/credentials",
            "/api/v1/operator/broker-accounts/{customer_id}/{broker}/{account_id}",
        }
        routes = {
            route.path: route for route in app.routes
            if getattr(route, "path", None) in protected_paths
        }
        self.assertEqual(set(routes), protected_paths)
        for path, route in routes.items():
            self.assertTrue(
                any(dependency.call is require_air_operator
                    for dependency in route.dependant.dependencies),
                f"{path} must require AIR operator authorization",
            )

    def test_configured_admin_identity_is_allowed(self):
        admin = "+919999999999"
        with patch.dict("os.environ", {"AIR_OPERATOR_CUSTOMER_IDS": admin}):
            self.assertEqual(require_air_operator(admin), admin)


if __name__ == "__main__":
    unittest.main()
