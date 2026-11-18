from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANAGER = ROOT / "scripts" / "air_manager.py"


class DeploymentOrchestratorSelectorTests(unittest.TestCase):
    def run_manager(self, *args):
        env = os.environ.copy()
        env.pop("AWS_REGION", None)
        env.pop("AWS_DEFAULT_REGION", None)
        return subprocess.run(
            [sys.executable, str(MANAGER), *args],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
        )

    def test_onprem_defaults_to_compose_without_prompt(self):
        result = self.run_manager("--profile", "onprem-single", "validate")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout)["orchestrator"], "compose")

    def test_onprem_accepts_explicit_swarm_selection(self):
        result = self.run_manager(
            "--profile", "onprem-single", "--orchestrator", "swarm", "validate"
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["orchestrator"], "swarm")
        self.assertEqual(payload["deployment_status"], "READY_FOR_LOCAL_PREFLIGHT")

    def test_aws_profiles_keep_ecs_orchestrator(self):
        for profile in ("aws-private-single", "aws-saas-multi"):
            with self.subTest(profile=profile):
                result = self.run_manager("--profile", profile, "validate")
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                payload = json.loads(result.stdout)
                self.assertIn(payload["orchestrator"], ("ecs_fargate", "ecs_ec2"))
                self.assertEqual(
                    payload["deployment_status"], "DEFERRED_UNTIL_AWS_ENVIRONMENT"
                )

    def test_docker_orchestrator_override_is_rejected_for_aws(self):
        result = self.run_manager(
            "--profile", "aws-saas-multi", "--orchestrator", "compose", "validate"
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--orchestrator is only supported for on-premises", result.stdout)

    def test_shell_wrapper_forwards_swarm_selection(self):
        result = subprocess.run(
            [
                "bash",
                str(ROOT / "AIRDEPLOY.sh"),
                "onprem-single",
                "validate",
                "--orchestrator",
                "swarm",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout)["orchestrator"], "swarm")


if __name__ == "__main__":
    unittest.main()
