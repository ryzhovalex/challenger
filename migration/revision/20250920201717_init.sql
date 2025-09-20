-- migrate:up
CREATE TABLE xuser (
    id INTEGER PRIMARY KEY,
    steam_id INTEGER NOT NULL UNIQUE,
    profile_url TEXT NOT NULL,
    avatar32 TEXT NOT NULL,
    avatar64 TEXT NOT NULL,
    avatar184 TEXT NOT NULL,
    username TEXT NOT NULL,
    fullname TEXT NOT NULL,
    current_game_id INTEGER DEFAULT 0,
    current_game_name TEXT DEFAULT '',
    registered_timestamp INTEGER DEFAULT 0
);

CREATE TABLE achievement (
    id INTEGER PRIMARY KEY,
    steam_id TEXT NOT NULL,  -- steam id of achievement not necessary to be unique
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    icon TEXT NOT NULL,
    completed BOOLEAN NOT NULL,
    unlock_timestamp INTEGER NOT NULL,
    game_id INTEGER,
    FOREIGN KEY (game_id) REFERENCES game(id) ON DELETE CASCADE
);

CREATE TABLE game (
    id INTEGER PRIMARY KEY,
    steam_id INTEGER NOT NULL UNIQUE,
    name TEXT NOT NULL,
    play_time INTEGER NOT NULL,
    last_play_time INTEGER NOT NULL,
    icon TEXT NOT NULL
);

-- migrate:down

