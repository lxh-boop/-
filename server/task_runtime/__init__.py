"""Durable long-task runtime.

Keep package initialization side-effect free: Worker subprocesses import this package
and must not create a second TaskManager that marks their own task interrupted.
"""

__all__: list[str] = []
