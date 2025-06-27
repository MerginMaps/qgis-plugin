# -*- coding: utf-8 -*-

# GPLv3 license
# Copyright Lutra Consulting Limited


import sys
import unittest


def _run_tests(test_suite, package_name):
    count = test_suite.countTestCases()
    print("########")
    print("{} tests has been discovered in {}".format(count, package_name))
    print("########")

    unittest.TextTestRunner(verbosity=3, stream=sys.stdout).run(test_suite)


def test_all(package="."):
    test_loader = unittest.defaultTestLoader
    test_suite = test_loader.discover(package)
    _run_tests(test_suite, package)


if __name__ == "__main__":
    test_all()
