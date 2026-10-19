-- The gateway's own database on the shared instance; it creates its tables there at start.
-- Runs only when the data volume is empty: on an existing volume, `make down` then `make up`.
CREATE DATABASE litellm;
