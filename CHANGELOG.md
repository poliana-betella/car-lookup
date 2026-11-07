# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/) e [Semantic Versioning](https://semver.org/).

## [1.0.1] - 2026-11-07

### Segurança
- Removido o modo de conexão "sem_verificacao", que aceitava certificados TLS inválidos como último recurso e passava a usá-lo como padrão nas consultas seguintes. Agora todos os modos de compatibilidade verificam o certificado e o nome do servidor.
- Modo SSL salvo por versões anteriores que não exista mais é descartado automaticamente.
- Quando o certificado do geoserviço não pode ser verificado, o plugin agora avisa e pergunta se o usuário quer continuar sem verificação. A autorização vale só para a sessão atual do QGIS e nunca é salva.

### Alterado
- Removidos import e variável de ícone não utilizados.

## [1.0.0] - 2026-09-16

### Adicionado
- Consulta ao geoserviço público WFS do SICAR pelo código do imóvel (com ou sem pontuação).
- Extração automática da UF a partir do código e descoberta automática da camada correspondente via `GetCapabilities`.
- Tentativa automática dos nomes de campo mais comuns usados nas bases do SICAR até encontrar o que retorna resultado.
- Cache local (QgsSettings) da camada e do campo descobertos por UF, com comando de menu para limpar e redetectar.
- Contorno automático de incompatibilidades de TLS comuns em geoserviços de governo, testando níveis de compatibilidade em sequência.
- Download da geometria como `.geojson` e carregamento direto da camada no projeto do QGIS.
