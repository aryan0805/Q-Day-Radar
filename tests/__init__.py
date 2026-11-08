"""Makes tests/ a regular package, on purpose.

textstat (a dependency since the Phase 5 readability gate) ships its own top-level `tests`
package in site-packages. Python prefers a regular package anywhere on sys.path over a namespace
package, so without this file `from tests.phase4 import reference` imported textstat's empty
package and failed with "No module named 'tests.phase4'". With it, the repo's `tests` is a
regular package and, found first through pytest's pythonpath = ["."], wins.
"""
