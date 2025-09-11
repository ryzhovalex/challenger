set shell := ["nu", "-c"]
python := ".venv/Scripts/python.exe"

run:
    @ {{python}} main.py
