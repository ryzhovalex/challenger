-- migrate:up
CREATE TABLE completion_insert_modification (
    id INTEGER PRIMARY KEY,

    -- which table was affected
    target_table TEXT NOT NULL,

    -- `select *` state converted to json after the moment of insertion
    payload TEXT NOT NULL,

    completion_id INTEGER,
    FOREIGN KEY (completion_id) REFERENCES completion(id) ON DELETE CASCADE
);

CREATE TABLE completion_update_modification (
    id INTEGER PRIMARY KEY,

    -- which table was affected
    target_table TEXT NOT NULL,
    -- which column was affected
    target_column TEXT NOT NULL,

    old_value BLOB NOT NULL,
    new_value BLOB NOT NULL,

    completion_id INTEGER,
    FOREIGN KEY (completion_id) REFERENCES completion(id) ON DELETE CASCADE
);

-- migrate:down

