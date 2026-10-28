import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contract_diff import catalog, diff, load_snapshot


def tool(schema=None, **extras):
    return {'name': 'search_notes', 'inputSchema': schema or {'type': 'object', 'properties': {'query': {'type': 'string'}}}, **extras}


def compare(a, b):
    return diff(catalog({'tools': a}), catalog({'tools': b}))


class ContractTests(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(compare([tool()], [tool()])['changes'], [])

    def test_removed_tool(self):
        self.assertEqual(compare([tool()], [])['summary']['risk'], 1)

    def test_added_tool(self):
        self.assertEqual(compare([], [tool()])['summary']['info'], 1)

    def test_new_requirement(self):
        old = tool()
        new = copy.deepcopy(old)
        new['inputSchema']['required'] = ['query']
        change = compare([old], [new])['changes'][0]
        self.assertEqual((change['level'], change['path']), ('risk', '/inputSchema/required'))

    def test_requirement_removed(self):
        self.assertEqual(compare([tool({'required': ['q']})], [tool({'required': []})])['summary']['info'], 1)

    def test_required_order_ignored(self):
        self.assertEqual(compare([tool({'required': ['a', 'b']})], [tool({'required': ['b', 'a']})])['changes'], [])

    def test_enum_narrowing_nested_array(self):
        a = {'type': 'array', 'items': {'enum': ['red', 'blue']}}
        b = {'type': 'array', 'items': {'enum': ['red']}}
        self.assertEqual(compare([tool(a)], [tool(b)])['changes'][0]['level'], 'risk')

    def test_enum_bool_number_distinct(self):
        self.assertEqual(compare([tool({'enum': [True]})], [tool({'enum': [1]})])['summary'], {'info': 1, 'review': 0, 'risk': 1})

    def test_const_bool_number_change(self):
        self.assertEqual(compare([tool({'const': True})], [tool({'const': 1})])['summary']['review'], 1)

    def test_type_change_not_certified(self):
        self.assertEqual(compare([tool({'type': 'integer'})], [tool({'type': 'number'})])['summary']['review'], 1)

    def test_unknown_constraint_is_reviewed(self):
        self.assertEqual(compare([tool({'minLength': 2})], [tool({'minLength': 5})])['summary']['review'], 1)

    def test_pointer_escape_and_property_removal(self):
        a = {'properties': {'a/b~c': {'type': 'string'}}}
        b = {'properties': {}}
        self.assertEqual(compare([tool(a)], [tool(b)])['changes'][0]['path'], '/inputSchema/properties/a~1b~0c')

    def test_description_info_output_review(self):
        report = compare([tool(description='a')], [tool(description='b', outputSchema={'type': 'object'})])
        self.assertEqual(report['summary'], {'info': 1, 'review': 1, 'risk': 0})

    def test_duplicate_name_and_bad_required_rejected(self):
        for tools in ([tool(), tool()], [tool({'required': [1]})]):
            with self.assertRaises(ValueError):
                catalog({'tools': tools})

    def test_pagination_and_errors_rejected(self):
        for data in ({'tools': [], 'nextCursor': 'next'}, {'error': {'message': 'oops'}}):
            with self.assertRaises(ValueError):
                catalog(data)
        self.assertEqual(catalog({'jsonrpc': '2.0', 'id': 1, 'result': {'tools': []}}), {})

    def test_duplicate_json_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'bad.json'
            p.write_text('{"tools":[],"tools":[]}', encoding='utf-8')
            with self.assertRaises(ValueError):
                load_snapshot(p)

    def test_cli_gates_and_preserves_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b, report = [Path(tmp) / n for n in ('a.json', 'b.json', 'report.json')]
            original = json.dumps({'tools': [tool()]})
            a.write_text(original)
            b.write_text('{"tools": []}')
            base = [sys.executable, str(Path(__file__).with_name('contract_diff.py')), str(a), str(b)]
            run = subprocess.run(base + ['--json', str(report)], capture_output=True)
            self.assertEqual(run.returncode, 1)
            self.assertEqual(json.loads(report.read_text())['summary']['risk'], 1)
            self.assertEqual(subprocess.run(base + ['--fail-on', 'none'], capture_output=True).returncode, 0)
            self.assertEqual(subprocess.run(base + ['--json', str(a)], capture_output=True).returncode, 2)
            self.assertEqual(a.read_text(), original)


if __name__ == '__main__':
    unittest.main()
