"""`make help` is generated from `## description` comments; every public target must have one."""

import os
import re
import unittest

MAKEFILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'makefile')


class MakefileHelpTests(unittest.TestCase):
    def test_every_phony_target_has_a_help_description(self):
        with open(MAKEFILE, encoding='utf-8') as f:
            text = f.read()
        phony = set(re.findall(r'^\.PHONY:\s*(.+)$', text, re.MULTILINE))
        phony = {name for line in phony for name in line.split()}
        described = set(re.findall(r'^([a-zA-Z_-]+):.*## \S', text, re.MULTILINE))

        self.assertTrue(phony)
        self.assertEqual(sorted(phony - described), [], 'add a `## description` to these targets')


if __name__ == '__main__':
    unittest.main()
