"""Live execution: signed exchange clients and the central execution engine.

There is deliberately no withdrawal, transfer or deposit-address code in this
package (tests/test_security.py enforces it). Keys whose permissions include
withdrawals are refused before any order is sent.
"""
