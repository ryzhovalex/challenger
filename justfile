set shell := ["nu", "-c"]
python := ".venv/Scripts/python.exe"

run:
    @ {{python}} main.py

migrate *t:
    @ dbmate --url "sqlite:///D:/users/thed4/appdata/roaming/challenger/data.db" -d "migration/revision" -s "migration" {{t}}

