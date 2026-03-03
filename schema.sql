CREATE TABLE IF NOT EXISTS pastes (
        id TEXT NOT NULL,
        user_id BIGINT NOT NULL,
        message_id BIGINT NOT NULL,
        safety_token TEXT NOT NULL,
        CONSTRAINT pk_id_user PRIMARY KEY (id, user_id)
);


CREATE TABLE IF NOT EXISTS paste_blocks (
    message_id BIGINT PRIMARY KEY
);