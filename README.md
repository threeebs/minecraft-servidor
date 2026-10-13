1. Descer todos os serviços
docker compose \
  -f compose.yaml \
  -f compose.panel.yaml \
  down


  2. Subir todos os serviços
  docker compose \
  -f compose.yaml \
  -f compose.panel.yaml \
  up -d

3. Verificar o status
  docker compose \
  -f compose.yaml \
  -f compose.panel.yaml \
  ps

  4. Reiniciar apenas o Minecraft
  docker compose \
  -f compose.yaml \
  -f compose.panel.yaml \
  restart minecraft
