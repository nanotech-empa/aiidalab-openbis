import os
import sys
import unittest
from unittest.mock import MagicMock

# Add repo root to sys.path
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

# Mock external packages that might not be installed or configured in the test
# environment. Restore sys.modules after importing the unit under test so these
# collection-time mocks cannot leak into unrelated AiiDA/ASE/widget tests.
_mocked_modules = [
    "rdkit",
    "rdkit.Chem",
    "rdkit.Chem.AllChem",
    "rdkit.Chem.Draw",
    "rdkit.Chem.rdMolDescriptors",
    "pandas",
    "bs4",
    "ipywidgets",
    "IPython",
    "IPython.display",
    "traitlets",
    "scipy",
    "sklearn",
    "pybis",
]
_missing = object()
_original_modules = {name: sys.modules.get(name, _missing) for name in _mocked_modules}
for mod in _mocked_modules:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

# Mock get_interface_config_info before widgets import it
from src import utils

_original_get_interface_config_info = utils.get_interface_config_info
utils.get_interface_config_info = MagicMock(
    return_value={
        "object_types": {"Process": "PROCESS", "Process Step": "PROCESS_STEP"},
        "object_types_codes": {"Process": "PROC", "Process Step": "STEP"},
        "actions_types": {},
        "actions_types_codes": {},
        "actions_types_icons": {},
        "actions_use_instrument": {},
        "slabs_types": {},
        "slabs_types_codes": {},
        "slabs_concepts_types": {},
        "slabs_concepts_codes": {},
        "instruments_types": {},
    }
)

from src.sample_preparation_widgets import (
    format_process_step_name,
    split_icons_and_name,
    strip_step_number,
    validate_and_sort_process_steps,
)

utils.get_interface_config_info = _original_get_interface_config_info
for _name, _module in _original_modules.items():
    if _module is _missing:
        sys.modules.pop(_name, None)
    else:
        sys.modules[_name] = _module


class MockOpenBISObject:
    def __init__(self, perm_id, name):
        self.permId = perm_id
        self.props = {"name": name}


class TestProcessStepsTemplateOrder(unittest.TestCase):
    def test_split_icons_and_name(self):
        # Plain text
        prefix, rest = split_icons_and_name("Delamination of Au")
        self.assertEqual(prefix, "")
        self.assertEqual(rest, "Delamination of Au")

        # Single icon with space
        prefix, rest = split_icons_and_name("[⚙️] Delamination of Au")
        self.assertEqual(prefix, "[⚙️] ")
        self.assertEqual(rest, "Delamination of Au")

        # Multiple icons
        prefix, rest = split_icons_and_name("[⚙️🔬] Sputtering and Annealing")
        self.assertEqual(prefix, "[⚙️🔬] ")
        self.assertEqual(rest, "Sputtering and Annealing")

        # Single icon without space
        prefix, rest = split_icons_and_name("[⚙️]Delamination")
        self.assertEqual(prefix, "[⚙️] ")
        self.assertEqual(rest, "Delamination")

        # Icon with existing number
        prefix, rest = split_icons_and_name("[⚙️] 01 - Delamination of Au")
        self.assertEqual(prefix, "[⚙️] ")
        self.assertEqual(rest, "01 - Delamination of Au")

        # None and empty
        prefix, rest = split_icons_and_name("")
        self.assertEqual(prefix, "")
        self.assertEqual(rest, "")

        prefix, rest = split_icons_and_name(None)
        self.assertEqual(prefix, "")
        self.assertEqual(rest, "")

    def test_format_process_step_name(self):
        # Plain name, idx 1 -> zero-padded 01
        self.assertEqual(
            format_process_step_name(1, "Delamination of Au"),
            "01 - Delamination of Au",
        )

        # Name with icon, idx 1 -> number comes after icons
        self.assertEqual(
            format_process_step_name(1, "[⚙️] Delamination of Au"),
            "[⚙️] 01 - Delamination of Au",
        )

        # Re-saving step 1 as step 2 (existing number replaced)
        self.assertEqual(
            format_process_step_name(2, "[⚙️] 01 - Delamination of Au"),
            "[⚙️] 02 - Delamination of Au",
        )

        # Step 10 formatting
        self.assertEqual(
            format_process_step_name(10, "[⚙️🔬] Annealing"),
            "[⚙️🔬] 10 - Annealing",
        )

        # Plain name with existing number replaced
        self.assertEqual(
            format_process_step_name(3, "01 - Step C"),
            "03 - Step C",
        )

        # Empty name
        self.assertEqual(
            format_process_step_name(1, ""),
            "01",
        )
        self.assertEqual(
            format_process_step_name(1, "[⚙️] "),
            "[⚙️] 01",
        )

    def test_strip_step_number(self):
        # Plain name with number prefix stripped
        self.assertEqual(
            strip_step_number("01 - Delamination of Au"),
            "Delamination of Au",
        )

        # Name with icon and number prefix
        self.assertEqual(
            strip_step_number("[⚙️] 01 - Delamination of Au"),
            "[⚙️] Delamination of Au",
        )

        # Name with multiple icons and number prefix
        self.assertEqual(
            strip_step_number("[⚙️🔬] 10 - Sputtering and Annealing"),
            "[⚙️🔬] Sputtering and Annealing",
        )

        # Name with no number prefix remains untouched
        self.assertEqual(
            strip_step_number("[⚙️] Delamination of Au"),
            "[⚙️] Delamination of Au",
        )
        self.assertEqual(
            strip_step_number("Delamination of Au"),
            "Delamination of Au",
        )

        # Number only
        self.assertEqual(strip_step_number("01"), "")
        self.assertEqual(strip_step_number("[⚙️] 01"), "[⚙️]")

        # Empty / None
        self.assertEqual(strip_step_number(""), "")
        self.assertEqual(strip_step_number(None), "")

    def test_validate_and_sort_process_steps_success(self):
        # Create mock steps in non-sequential order
        step1 = MockOpenBISObject("id-1", "[🔥] 01 - Delamination of Au")
        step2 = MockOpenBISObject("id-2", "02 - Annealing")
        step3 = MockOpenBISObject("id-3", "[⚙️] 03 - Characterization")

        mock_objects = {
            "id-3": step3,
            "id-1": step1,
            "id-2": step2,
        }

        mock_session = MagicMock()
        mock_session.get_object.side_effect = lambda sample_ident: mock_objects.get(
            sample_ident
        )

        # Input in arbitrary order: 3, 1, 2
        sorted_steps, err = validate_and_sort_process_steps(
            "Test Recipe", ["id-3", "id-1", "id-2"], mock_session
        )

        self.assertIsNone(err)
        self.assertIsNotNone(sorted_steps)
        self.assertEqual(len(sorted_steps), 3)
        self.assertEqual(sorted_steps[0].permId, "id-1")
        self.assertEqual(sorted_steps[1].permId, "id-2")
        self.assertEqual(sorted_steps[2].permId, "id-3")

    def test_validate_and_sort_missing_number(self):
        # User removed number in openBIS from step 1
        step1 = MockOpenBISObject("id-1", "[⚙️] Delamination of Au")
        step2 = MockOpenBISObject("id-2", "[🔥] 02 - Annealing")

        mock_objects = {"id-1": step1, "id-2": step2}
        mock_session = MagicMock()
        mock_session.get_object.side_effect = lambda sample_ident: mock_objects.get(
            sample_ident
        )

        sorted_steps, err = validate_and_sort_process_steps(
            "Test Recipe", ["id-1", "id-2"], mock_session
        )

        self.assertIsNone(sorted_steps)
        self.assertIsNotNone(err)
        self.assertIn("Cannot load process template 'Test Recipe'", err)
        self.assertIn("does not have a number at the beginning of its name", err)
        self.assertIn("[⚙️] Delamination of Au", err)

    def test_validate_and_sort_duplicate_number(self):
        # User changed step 2 number to 01 in openBIS
        step1 = MockOpenBISObject("id-1", "[⚙️] 01 - Delamination of Au")
        step2 = MockOpenBISObject("id-2", "[🔥] 01 - Annealing")

        mock_objects = {"id-1": step1, "id-2": step2}
        mock_session = MagicMock()
        mock_session.get_object.side_effect = lambda sample_ident: mock_objects.get(
            sample_ident
        )

        sorted_steps, err = validate_and_sort_process_steps(
            "Test Recipe", ["id-1", "id-2"], mock_session
        )

        self.assertIsNone(sorted_steps)
        self.assertIsNotNone(err)
        self.assertIn("Cannot load process template 'Test Recipe'", err)
        self.assertIn("Step number 01 is used by multiple process steps", err)
        self.assertIn("[⚙️] 01 - Delamination of Au", err)
        self.assertIn("[🔥] 01 - Annealing", err)

    def test_validate_and_sort_multiple_errors(self):
        # Step 1 missing number, Step 2 and Step 3 duplicate number 02
        step1 = MockOpenBISObject("id-1", "Plain Delamination")
        step2 = MockOpenBISObject("id-2", "02 - Annealing A")
        step3 = MockOpenBISObject("id-3", "02 - Annealing B")

        mock_objects = {"id-1": step1, "id-2": step2, "id-3": step3}
        mock_session = MagicMock()
        mock_session.get_object.side_effect = lambda sample_ident: mock_objects.get(
            sample_ident
        )

        sorted_steps, err = validate_and_sort_process_steps(
            "Test Recipe", ["id-1", "id-2", "id-3"], mock_session
        )

        self.assertIsNone(sorted_steps)
        self.assertIsNotNone(err)
        # Verify both errors are reported in the bullet points
        self.assertIn("Plain Delamination", err)
        self.assertIn("does not have a number at the beginning of its name", err)
        self.assertIn("Step number 02 is used by multiple process steps", err)

    def test_validate_and_sort_step_not_found(self):
        mock_session = MagicMock()
        mock_session.get_object.return_value = None

        sorted_steps, err = validate_and_sort_process_steps(
            "Test Recipe", ["non-existent-id"], mock_session
        )

        self.assertIsNone(sorted_steps)
        self.assertIsNotNone(err)
        self.assertIn("was not found in openBIS", err)

    def test_validate_and_sort_empty_list(self):
        mock_session = MagicMock()
        sorted_steps, err = validate_and_sort_process_steps(
            "Test Recipe", [], mock_session
        )

        self.assertIsNone(sorted_steps)
        self.assertIsNotNone(err)
        self.assertIn("contains no process steps", err)


if __name__ == "__main__":
    unittest.main()
