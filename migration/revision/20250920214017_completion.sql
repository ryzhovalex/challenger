-- migrate:up
CREATE TABLE completion (
    id INTEGER PRIMARY KEY,  -- id represents timestamp
    completion FLOAT NOT NULL,
    completed INTEGER NOT NULL,
    total INTEGER NOT NULL
);

-- migrate:down

