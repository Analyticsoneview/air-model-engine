import os
import unittest
from unittest.mock import patch

from app.deployment_profiles import (
    DeploymentProfileError,
    load_profile,
    validate_profile,
)


class DeploymentProfileTests(unittest.TestCase):
    def test_all_three_deployment_profiles_are_valid_and_include_rabbitmq(self):
        for profile_id in ("onprem-single", "aws-private-single", "aws-saas-multi"):
            profile = load_profile(profile_id)
            self.assertTrue(profile["services"]["rabbitmq"])
            self.assertTrue(profile["services"]["fastapi"])
            self.assertTrue(profile["services"]["workflow_engine"])

    def test_rabbitmq_cannot_be_disabled(self):
        profile = load_profile("onprem-single")
        profile["services"]["rabbitmq"] = False
        with self.assertRaisesRegex(DeploymentProfileError, "rabbitmq"):
            validate_profile(profile)

    def test_saas_profile_must_be_multi_tenant_and_tenant_scoped(self):
        profile = load_profile("aws-saas-multi")
        profile["deployment"]["tenancy"] = "single"
        with self.assertRaisesRegex(DeploymentProfileError, "multi-tenant"):
            validate_profile(profile)

    def test_private_aws_profile_requires_dedicated_infrastructure(self):
        profile = load_profile("aws-private-single")
        profile["infrastructure"]["isolation"] = "tenant_scoped"
        with self.assertRaisesRegex(DeploymentProfileError, "dedicated"):
            validate_profile(profile)

    def test_aws_region_is_required_before_cloud_provisioning(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(DeploymentProfileError, "AWS_REGION"):
                load_profile("aws-private-single", require_cloud_env=True)
        with patch.dict(os.environ, {"AWS_REGION": "ap-south-1"}, clear=True):
            self.assertEqual(
                load_profile("aws-private-single", require_cloud_env=True)["profile_id"],
                "aws-private-single",
            )

    def test_onprem_never_requires_aws_region(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                load_profile("onprem-single", require_cloud_env=True)["deployment"]["provider"],
                "on_prem",
            )


if __name__ == "__main__":
    unittest.main()
