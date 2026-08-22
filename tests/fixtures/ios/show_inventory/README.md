# `show inventory` fixtures

`c9300_iosxe_pager_backspace.txt` is a sanitized regression fixture derived from a real
IOS/IOS-XE `show inventory` capture. Identifiers and serial numbers are synthetic.
The terminal pager artifact is intentionally preserved: `--More--`, backspace control
bytes, and erase spaces remain in the fixture so parser tests exercise the same RAW
shape observed in production.
