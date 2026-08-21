# Cisco Switch Assessment Framework

Python framework for automated, read-only assessments of Cisco switches.

Initial scope: Cisco IOS and IOS-XE, with an architecture prepared for future NX-OS support.

Core pipeline:

`inventory -> collector -> raw -> parsers -> normalized models -> assessment -> reporting`

Current MVP vertical slice: SSH collection of `show version` with byte-preserving RAW storage.
