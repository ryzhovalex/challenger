-- migrate:up
CREATE TABLE sync (
    id INTEGER PRIMARY KEY,
    last_timestamp INTEGER DEFAULT 0
);
INSERT INTO sync (last_timestamp) VALUES (0);

-- migrate:down

