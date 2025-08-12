CREATE TABLE IF NOT EXISTS trials (
  id            BIGSERIAL PRIMARY KEY,
  email         TEXT NOT NULL,
  machine_ip    INET,
  ativo         CHAR(1) NOT NULL DEFAULT 'N',  -- 'S' ou 'N'
  expires_at    TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trials_ativo ON trials (ativo);
CREATE UNIQUE INDEX IF NOT EXISTS ux_trials_email ON trials (email);

-- Exemplo: já deixar um registro seu
INSERT INTO trials (email, machine_ip, ativo, expires_at)
VALUES ('arthur@exemplo.com', '127.0.0.1', 'S', NOW() + INTERVAL '7 days')
ON CONFLICT (email) DO NOTHING;
