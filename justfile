set shell := ["nu", "-c"]
python := ".venv/Scripts/python.exe"

run host="localhost" port="3500":
    @ {{python}} main.py -host {{host}} -port {{port}}

migrate *t:
    @ dbmate --url "sqlite:///C:/Users/thed4/AppData/Roaming/challenger/data.db" -d "migration/revision" -s "migration" {{t}}

build_css:
    @ tailwind --minify -i main.css -o share/main.min.css

build_css_watch:
    @ tailwind --watch --minify -i main.css -o share/main.min.css
