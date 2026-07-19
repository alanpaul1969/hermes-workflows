import unittest

from plugins.engine import resolve_execution_order, validate_workflow


class DependencyResolutionTests(unittest.TestCase):
    def test_reports_malformed_steps_without_crashing(self):
        workflow = {
            "name": "invalid",
            "steps": [
                "not-a-step",
                {
                    "id": "valid",
                    "type": "subagent",
                    "context": "Valid",
                    "depends_on": 42,
                },
            ],
        }

        self.assertEqual(
            validate_workflow(workflow),
            [
                "steps[0]: must be a dictionary",
                "steps[1].depends_on: must be a step id or list of step ids",
            ],
        )

    def test_rejects_invalid_step_ids_and_dependency_items(self):
        workflow = {
            "name": "invalid",
            "steps": [
                {"id": [], "type": "subagent", "context": "Invalid"},
                {
                    "id": "valid",
                    "type": "subagent",
                    "context": "Valid",
                    "depends_on": [1],
                },
            ],
        }

        self.assertEqual(
            validate_workflow(workflow),
            [
                "steps[0]: field 'id' must be a non-empty string",
                "steps[1].depends_on: each step id must be a string",
            ],
        )

    def test_resolves_dependency_waves(self):
        steps = [
            {"id": "collect", "type": "skill", "skill": "source"},
            {
                "id": "report",
                "type": "subagent",
                "context": "Summarize",
                "depends_on": "collect",
            },
        ]

        self.assertEqual(resolve_execution_order(steps), [["collect"], ["report"]])

    def test_rejects_circular_dependencies(self):
        workflow = {
            "name": "cycle",
            "steps": [
                {
                    "id": "first",
                    "type": "subagent",
                    "context": "First",
                    "depends_on": "second",
                },
                {
                    "id": "second",
                    "type": "subagent",
                    "context": "Second",
                    "depends_on": "first",
                },
            ],
        }

        self.assertEqual(
            validate_workflow(workflow),
            ["Circular dependency among steps: first, second"],
        )


if __name__ == "__main__":
    unittest.main()
