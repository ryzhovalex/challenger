set shell := ["nu", "-c"]
python := ".venv/Scripts/python.exe"

run:
    @ {{python}} main.py

migrate *t:
    @ dbmate --url "sqlite:///C:/Users/thed4/AppData/Roaming/challenger/data.db" -d "migration/revision" -s "migration" {{t}}

