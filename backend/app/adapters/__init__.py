"""Driver-pattern abstractions per docs/TechStack.md §15.

Each adapter has env-switched implementations that land in later phases.
Business code must depend on these interfaces, never on provider internals
or NODE_ENV-style branches.
"""
