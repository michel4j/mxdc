import unittest
import sys
import os


from mxdc.utils import datatools


class DataToolsTestCase(unittest.TestCase):
    def setUp(self):
        self.manager = datatools.NameManager(database={'test': 3, 'lysozyme': 0, 'thaumatin': 1})

    def test_1st_name(self):
        sample = 'thermolysin'
        name = self.manager.get(sample)

        self.assertEqual(
            sample, name,
            f'First new name does not match sample name {name=} != {sample=}'
        )

    def test_2nd_name(self):
        sample = 'lysozyme'
        name = self.manager.get(sample)
        expected = f'{sample}-1'

        self.assertEqual(
            name, expected,
            f'Second new name does not match expected {name=} != {expected=}'
        )

    def test_3rd_name(self):
        sample = 'lysozyme'
        name = self.manager.get(sample)
        expected = f'{sample}-1'

        self.assertEqual(
            name, expected,
            f'Second new name does not match expected {name=} != {expected=}'
        )

    def test_fixes(self):
        sample = 'insulin'
        names = ['insulin', 'insulin-1', 'insulin-8', 'insulin', 'insul']
        expected = ['insulin', 'insulin-1', 'insulin-8', 'insulin-9', 'insul']
        fixed = self.manager.fix(sample, *names)
        self.assertEqual(
            fixed, expected,
            f'Fixed names do not match expected {fixed=} != {expected=}'
        )
if __name__ == '__main__':
    unittest.main()