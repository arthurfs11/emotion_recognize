CREATE TABLE IF NOT EXISTS trials (
  id         SERIAL PRIMARY KEY,
  email      TEXT UNIQUE NOT NULL,
  ip         INET,
  ativo      BOOLEAN NOT NULL DEFAULT FALSE,
  expira_em  TIMESTAMP NOT NULL DEFAULT (NOW() + INTERVAL '30 minutes'),
  criado_em  TIMESTAMP NOT NULL DEFAULT NOW(),
  obs        TEXT
);

-- usuário padrão já tem acesso pois é o dono do DB
GRANT SELECT, INSERT, UPDATE ON trials TO ${POSTGRES_USER};
